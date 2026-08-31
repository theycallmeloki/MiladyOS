#!/bin/sh
# Ensure the MiladyOS container image is loaded from the ISO payload.
# Idempotent: skips if image already present (covers live + installed).
set -e

IMAGE="${MILADYOS_IMAGE:-ogmiladyloki/miladyos:latest}"

if docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "miladyos-ensure-image: $IMAGE already present"
    exit 0
fi

# payload lives on the ISO medium in live mode; on disk after install
for d in /run/live/medium/payload /lib/live/mount/medium/payload \
         /opt/miladyos/payload /payload; do
    if [ -f "$d/miladyos-image.tar.zst" ]; then
        echo "miladyos-ensure-image: loading from $d" > /dev/console 2>/dev/null || true
        zstd -dc "$d/miladyos-image.tar.zst" | docker load
        echo "miladyos-ensure-image: image loaded OK" > /dev/console 2>/dev/null || true
        exit 0
    fi
done

echo "miladyos-ensure-image: no payload found; will pull from registry if reachable"
docker pull "$IMAGE" || echo "miladyos-ensure-image: pull failed — image unavailable"
