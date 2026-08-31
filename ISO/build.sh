#!/usr/bin/env bash
# MiladyOS ISO build — orchestration (host side).
#
#   ISO/build.sh [--no-payload] [--version X.Y.Z] [--image ogmiladyloki/miladyos:latest]
#
# Pipeline (dockerized, deterministic — no host deps beyond docker + zstd):
#   1. stage payload: docker save ogmiladyloki/miladyos | zstd -> out/payload/
#   2. build builder image (debian:13.4 + live-build)
#   3. run lb config + lb build in container -> out/miladyos-<version>.iso
#
# Env overrides: MILADYOS_IMAGE, VERSION, OUT_DIR, LB_* (extra lb args)
set -euo pipefail

ISO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$ISO_DIR/.." && pwd)"
CACHE_DIR="${CACHE_DIR:-$ISO_DIR/.cache}"
OUT_DIR="${OUT_DIR:-$ISO_DIR/out}"
VERSION="${VERSION:-$(git -C "$REPO_DIR" describe --tags --always 2>/dev/null || date +%Y%m%d)}"

MILADYOS_IMAGE="${MILADYOS_IMAGE:-ogmiladyloki/miladyos:latest}"
BUILDER_TAG="miladyos-iso-builder:13.4"
MILADYOS_ROLE="${MILADYOS_ROLE:-server}"   # seed node.conf: server|agent

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

# --- 2. builder image ------------------------------------------------------
docker build -t "$BUILDER_TAG" -f "$ISO_DIR/builder/Dockerfile" "$ISO_DIR/builder"

mkdir -p "$OUT_DIR" "$CACHE_DIR"
docker run --rm --privileged \
    -v "$ISO_DIR":/iso:ro \
    -v "$OUT_DIR":/out \
    -v "$CACHE_DIR":/build/cache \
    -e VERSION="$VERSION" \
    -e MILADYOS_IMAGE="$MILADYOS_IMAGE" \
    -e NO_PAYLOAD="$NO_PAYLOAD" \
    -e MILADYOS_ROLE="$MILADYOS_ROLE" \
    "$BUILDER_TAG"

echo "done: $(ls -lh "$OUT_DIR"/*.iso 2>/dev/null | awk '{print $9, $5}')"
