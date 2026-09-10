#!/usr/bin/env bash
# One-time setup for the sandman ISO-build pipeline on the worker host
# (miladyos-42). No root needed — Docker creates the host-mirrored volume.
#
#   ISO/sandman/seed-worker.sh            # dirs + payload cache + runner image
#   NO_PAYLOAD=1 ISO/sandman/seed-worker.sh
#
# Then create the pipeline (see docs/SANDMAN-BUILD.md).
set -euo pipefail

ISO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# The build volume must exist at the SAME path on the host and inside the job:
# the job drives the host Docker, and the host daemon resolves the nested
# `docker -v` arguments — /sandman/volumes/milady-iso has to mean the same
# directory on both sides. Docker creates it root-owned.
VOL=/sandman/volumes/milady-iso

echo "== creating $VOL"
docker run --rm -v "$VOL":/v alpine:3 mkdir -p /v/src /v/cache /v/out/payload

if [ "${NO_PAYLOAD:-0}" != 1 ] && [ -f "$ISO_DIR/out/payload/miladyos-image.tar.zst" ]; then
    echo "== warming payload cache from $ISO_DIR/out/payload (large, one time)"
    docker run --rm -v "$VOL":/v -v "$ISO_DIR/out/payload":/src:ro alpine:3 \
        sh -c 'cp -f /src/miladyos-image.tar.zst /v/out/payload/ && ls -lh /v/out/payload/'
else
    echo "== payload cache not seeded (--no-payload builds do not need it)"
fi

echo "== building runner image milady-iso-runner:1"
docker build -t milady-iso-runner:1 "$ISO_DIR/sandman"

echo "== warming the get.k3s.io script into the cache"
docker run --rm -v "$VOL":/v milady-iso-runner:1 \
    sh -c 'mkdir -p /v/cache/k3s && curl -fsSL https://get.k3s.io -o /v/cache/k3s/k3s-install.sh' \
    || echo "   (skipped: could not fetch get.k3s.io — the builder will fetch it)"

cat <<EOF

worker seeded.
  volume  $VOL   (host-mirrored: src/ cache/ out/)
  image   milady-iso-runner:1
  doc     $ISO_DIR/docs/SANDMAN-BUILD.md

create + trigger:
  sandman pipeline create -f $ISO_DIR/sandman/iso-build.pipeline.json
  sandman pipeline run-cron miladyos-iso-build
  sandman logs pipeline miladyos-iso-build --follow

tracking (the pipeline commits manifest.json + builds.jsonl to its output repo):
  sandman repo list | grep miladyos-iso
EOF
