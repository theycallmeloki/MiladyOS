#!/bin/sh
# Ensure the MiladyOS container image is loaded from the ISO payload.
# Idempotent: skips if image already present (covers live + installed).
set -e

IMAGE="${MILADYOS_IMAGE:-ogmiladyloki/miladyos:latest}"

if docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "milady-ensure-image: $IMAGE already present"
    exit 0
fi

# payload lives on the ISO medium in live mode; on disk after install.
# Accept both names: the staged payload is miladyos-image.tar.zst, but older
# trees used milady-image.tar.zst — a mismatch here silently fell back to a
# registry pull on every live boot.
for d in /run/live/medium/payload /lib/live/mount/medium/payload \
         /opt/milady/payload /payload; do
    for f in "$d/miladyos-image.tar.zst" "$d/milady-image.tar.zst"; do
        [ -f "$f" ] || continue
        echo "milady-ensure-image: loading from $f" > /dev/console 2>/dev/null || true
        zstd -dc "$f" | docker load
        echo "milady-ensure-image: image loaded OK" > /dev/console 2>/dev/null || true
        exit 0
    done
done

echo "milady-ensure-image: no payload found; will pull from registry if reachable"
docker pull "$IMAGE" || echo "milady-ensure-image: pull failed — image unavailable"
