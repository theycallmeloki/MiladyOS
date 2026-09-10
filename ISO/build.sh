#!/usr/bin/env bash
# MiladyOS ISO build — orchestration (host side).
#
#   ISO/build.sh [--no-payload] [--version X.Y.Z.W.V] [--image ogmiladyloki/miladyos:latest]
#
# Pipeline (dockerized, deterministic — no host deps beyond docker + zstd):
#   1. stage payload: docker save ogmiladyloki/miladyos | zstd -> out/payload/
#   2. build builder image (debian:13.4 + live-build)
#   3. run lb config + lb build in container -> out/miladyos-<version>.iso
#
# Env overrides: MILADYOS_IMAGE, VERSION, OUT_DIR, MILADY_BOOTAPPEND_LIVE
# (extra live kernel cmdline, e.g. "milady.auto=1" for unattended install tests).
set -euo pipefail

ISO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$ISO_DIR/.." && pwd)"
CACHE_DIR="${CACHE_DIR:-$ISO_DIR/.cache}"
OUT_DIR="${OUT_DIR:-$ISO_DIR/out}"
VERSION="${VERSION:-$(bash "$ISO_DIR/version.sh")}"

MILADYOS_IMAGE="${MILADYOS_IMAGE:-ogmiladyloki/miladyos:latest}"
BUILDER_TAG="milady-iso-builder:13.4"
MILADYOS_ROLE="${MILADYOS_ROLE:-server}"   # seed node.conf: server|agent|desktop
MILADY_DEV="${MILADY_DEV:-0}"             # 1 = keep dev entry paths (root serial
                                          # autologin + baked SSH key)

# --- registry-as-cache images (optional) -----------------------------------
# The ISO build bus (ISO/woodpecker/iso-build.yml) builds/pushes these with
# the cluster registry as the cache; a bus run pulls them instead of
# rebuilding. Unset => the historical local-only behaviour.
MILADY_BUILDER_IMAGE="${MILADY_BUILDER_IMAGE:-}"  # registry/milady-iso-builder:<rev>
MILADY_CACHE_IMAGE="${MILADY_CACHE_IMAGE:-}"      # registry/milady-iso-cache:<rev>
MILADY_CACHE_PUSH="${MILADY_CACHE_PUSH:-0}"       # 1 = publish CACHE_DIR as an image

NO_PAYLOAD=0
[[ "${1:-}" == "--no-payload" ]] && NO_PAYLOAD=1

mkdir -p "$OUT_DIR/payload"

# --- 1. payload ------------------------------------------------------------
if [ "$NO_PAYLOAD" -eq 0 ]; then
    PAYLOAD_TAR="$OUT_DIR/payload/miladyos-image.tar.zst"
    if [ -f "$PAYLOAD_TAR" ]; then
        echo "payload exists: $PAYLOAD_TAR (rm to rebuild)"
    else
        echo "staging payload: $MILADYOS_IMAGE"
        # docker save -> zstd. pv if present for progress, else quiet.
        if command -v pv >/dev/null 2>&1; then
            docker save "$MILADYOS_IMAGE" | pv -s "$(docker image inspect "$MILADYOS_IMAGE" --format '{{.Size}}')" | zstd -T0 -3 -o "$PAYLOAD_TAR"
        else
            docker save "$MILADYOS_IMAGE" | zstd -T0 -3 -o "$PAYLOAD_TAR"
        fi
        echo "payload staged: $(du -h "$PAYLOAD_TAR" | cut -f1)"
    fi
fi

mkdir -p "$OUT_DIR" "$CACHE_DIR"

# --- warm cache from the registry (cold host) ------------------------------
# A local CACHE_DIR always wins (faster than a pull); the image is the
# portable copy of debootstrap + apt archives + the k3s binary/installer.
if [ -n "$MILADY_CACHE_IMAGE" ] && [ ! -e "$CACHE_DIR/.seeded" ]; then
    echo "cache: seeding from $MILADY_CACHE_IMAGE"
    if docker pull "$MILADY_CACHE_IMAGE" >/dev/null 2>&1; then
        cid=$(docker create "$MILADY_CACHE_IMAGE")
        docker cp "$cid:/." "$CACHE_DIR/" >/dev/null 2>&1 || true
        docker rm -f "$cid" >/dev/null 2>&1 || true
        touch "$CACHE_DIR/.seeded"
    else
        echo "cache: $MILADY_CACHE_IMAGE unavailable — cold build"
    fi
fi

# --- 2. builder image ------------------------------------------------------
# The builder is itself a build-bus artifact: a Kaniko-built image in the
# registry whose layers are the cache. Prefer it when given.
if [ -n "$MILADY_BUILDER_IMAGE" ]; then
    echo "builder: pulling $MILADY_BUILDER_IMAGE (build-bus artifact)"
    docker pull "$MILADY_BUILDER_IMAGE"
    BUILDER_TAG="$MILADY_BUILDER_IMAGE"
else
    docker build -t "$BUILDER_TAG" -f "$ISO_DIR/builder/Dockerfile" "$ISO_DIR/builder"
fi
docker run --rm --privileged \
    -v "$ISO_DIR":/iso:ro \
    -v "$REPO_DIR/milady":/milady:ro \
    -v "$OUT_DIR":/out \
    -v "$CACHE_DIR":/build/cache \
    -e VERSION="$VERSION" \
    -e MILADYOS_IMAGE="$MILADYOS_IMAGE" \
    -e NO_PAYLOAD="$NO_PAYLOAD" \
    -e MILADYOS_ROLE="$MILADYOS_ROLE" \
    -e MILADY_DEV="$MILADY_DEV" \
    -e K3S_VERSION="${K3S_VERSION:-}" \
    -e MILADY_COMMIT="$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || echo unknown)" \
    -e MILADY_BOOTAPPEND_LIVE="${MILADY_BOOTAPPEND_LIVE:-}" \
    "$BUILDER_TAG"

# --- publish the cache image (build-bus warm cache) -------------------------
# docker import/export carries the directory tree as an image; the registry
# then holds debootstrap + apt archives + k3s so a cold host skips the
# downloads entirely.
if [ "$MILADY_CACHE_PUSH" = 1 ] && [ -n "$MILADY_CACHE_IMAGE" ]; then
    echo "cache: publishing $MILADY_CACHE_IMAGE"
    tar -C "$CACHE_DIR" --exclude=.seeded -cf - . | docker import - "$MILADY_CACHE_IMAGE"
    docker push "$MILADY_CACHE_IMAGE"
fi

echo "done: $(ls -lh "$OUT_DIR"/*.iso 2>/dev/null | awk '{print $9, $5}')"
