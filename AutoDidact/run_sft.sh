#!/usr/bin/env bash
# run_sft.sh — the SFT cold-start on the A4000 (GPU 1).
#
# Use this before GRPO when a capability has a 0 % base rate: round 0001 showed
# the bare student scoring correctness 0/24 steps, so every GRPO group had
# uniform rewards and no gradient. Demonstration data first, then GRPO.
#
#   ./run_sft.sh --dry-run                 # build the trainer, train nothing
#   ./run_sft.sh --max-steps 120           # a real cold-start
#   ./run_sft.sh --round round-0002-sft    # write the round record as it goes
#
# GPU 1 = the A4000 = the trainer. The sensei is not needed (SFT has no judge),
# so this runs happily while data generation uses the 3090.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="$HERE/runtime/venv"

export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-1}"
export HF_HUB_DISABLE_XET=1

DATASET="${DATASET:-r2.warmup}"
OUT="${OUT:-$HERE/r2_training}"

[ -x "$VENV/bin/python" ] || {
    echo "no runtime at $VENV — see run_grpo.sh for the build lines" >&2
    exit 1
}

exec "$VENV/bin/python" -u "$HERE/train_sft.py" \
    --dataset "$DATASET" --out "$OUT" "$@"
