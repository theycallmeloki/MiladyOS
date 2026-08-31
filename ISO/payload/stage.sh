#!/usr/bin/env bash
# Stage the MiladyOS container image as the ISO payload.
#
#   payload/stage.sh [image] [output.tar.zst]
#
# Defaults: image=ogmiladyloki/miladyos:latest, output=out/payload/miladyos-image.tar.zst
# docker save | zstd — idempotent (skips if output exists unless FORCE=1).
set -euo pipefail

ISO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${1:-ogmiladyloki/miladyos:latest}"
OUT="${2:-$ISO_DIR/out/payload/miladyos-image.tar.zst}"

if [ -f "$OUT" ] && [ "${FORCE:-0}" -ne 1 ]; then
    echo "payload exists: $OUT ($(du -h "$OUT" | cut -f1)) — FORCE=1 to rebuild"
    exit 0
fi

mkdir -p "$(dirname "$OUT")"
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "pulling $IMAGE..."
    docker pull "$IMAGE"
fi

echo "saving $IMAGE -> $OUT"
if command -v pv >/dev/null 2>&1; then
    docker save "$IMAGE" | pv -s "$(docker image inspect "$IMAGE" --format '{{.Size}}')" | zstd -T0 -3 -o "$OUT"
else
    docker save "$IMAGE" | zstd -T0 -3 -o "$OUT"
fi
echo "staged: $(du -h "$OUT" | cut -f1)"
