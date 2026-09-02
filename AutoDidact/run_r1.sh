#!/usr/bin/env bash
# run_r1.sh — launch round-1 GRPO (R1-1.5B, comprehension mode) on the A4000.
#
# Requires:
#   - autodidact-rl:r1-1.5b image built (docker build -f Dockerfile.rl_training -t autodidact-rl:r1-1.5b .)
#   - the 27B judge serving on the 3090 (:18020) — JUDGE_API targets the docker bridge gateway
#   - saved_data/r1_train.jsonl built (build_r1_dataset.py)
#
# Usage: ./run_r1.sh            # foreground-ish container run
#        ./run_r1.sh --name NAME  # custom run name
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
NAME="${1:-autodidact-r1}"
RUN="${2:-nano-milady-r1-r1}"

docker rm -f "$NAME" >/dev/null 2>&1 || true

docker run -d --name "$NAME" --gpus device=1 \
  -e WANDB_PROJECT=milady-autodidact \
  -e WANDB_MODE=online \
  -e JUDGE_API=http://172.17.0.1:18020/v1/chat/completions \
  -e DATA=/app/saved_data/r1_train_grounded.jsonl \
  -e RUN_NAME="$RUN" \
  -v "$HOME/.netrc:/root/.netrc:ro" \
  -v "$HERE/train_r1.py:/app/train_r1.py:ro" \
  -v "$HERE/r1_rewards.py:/app/r1_rewards.py:ro" \
  -v "$HERE/judge.py:/app/judge.py:ro" \
  -v "$HERE/saved_data:/app/saved_data" \
  -v "$HERE/r1_training:/app/r1_training" \
  -v /media/laneone/storage/models/hf-cache-user:/root/.cache/huggingface \
  autodidact-rl:r1-1.5b \
  python3 -u /app/train_r1.py

echo "container $NAME started; follow with: docker logs -f $NAME"
