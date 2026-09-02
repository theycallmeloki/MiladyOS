#!/usr/bin/env bash
# run_r2_sft.sh — SFT cold-start (tool-call syntax warmup) on the A4000.
#
# Usage: ./run_r2_sft.sh [NAME] [RUN_NAME]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
NAME="${1:-autodidact-r2-sft}"
RUN="${2:-nano-milady-r2-sft}"

docker rm -f "$NAME" >/dev/null 2>&1 || true

docker run -d --name "$NAME" --gpus device=1 \
  -e WANDB_PROJECT=milady-autodidact \
  -e WANDB_MODE=online \
  -e DATA=/app/saved_data/r2_warmup.jsonl \
  -e OUT=/app/r2_training/sft \
  -e RUN_NAME="$RUN" \
  -v "$HOME/.netrc:/root/.netrc:ro" \
  -v "$HERE/train_r2_sft.py:/app/train_r2_sft.py:ro" \
  -v "$HERE/saved_data:/app/saved_data" \
  -v "$HERE/r2_training:/app/r2_training" \
  -v /media/laneone/storage/models/hf-cache-user:/root/.cache/huggingface \
  autodidact-rl:r1-1.5b \
  python3 -u /app/train_r2_sft.py

echo "container $NAME started; follow with: docker logs -f $NAME"
