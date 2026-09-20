#!/usr/bin/env bash
# run_grpo.sh — the AutoDidact loop on the A4000 (GPU 1).
#
# One round: GRPO over a registry dataset, judged by the sensei on GPU 0.
# No docker, no unsloth — the runtime is runtime/venv (pinned in
# runtime/requirements.lock) and the trainer is train_grpo.py.
#
#   ./run_grpo.sh --dry-run                       # build the trainer, train nothing
#   ./run_grpo.sh --max-steps 101                 # a real round
#   DATASET=r1.train ./run_grpo.sh                # a different registry dataset
#   CUDA_VISIBLE_DEVICES=0 ./run_grpo.sh          # explicitly, if you must
#
# The judge endpoint comes from bus/config.py (MILADY_SENSEI_URL / JUDGE_API);
# this script deliberately sets no endpoint of its own.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="$HERE/runtime/venv"

# GPU 1 = the A4000 = the trainer. Pinned here so a round can never touch the
# sensei's GPU, and so train_grpo.py's device-count warning stays a warning.
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-1}"
# The xet downloader stalls on this box; the model is cached anyway.
export HF_HUB_DISABLE_XET=1

DATASET="${DATASET:-r1.train.grounded}"
OUT="${OUT:-$HERE/r1_training}"

[ -x "$VENV/bin/python" ] || {
    echo "no runtime at $VENV — build it with:" >&2
    echo "  uv venv --python 3.12 runtime/venv && \\" >&2
    echo "  uv pip install --python runtime/venv/bin/python \\" >&2
    echo "    torch transformers peft bitsandbytes trl accelerate datasets" >&2
    exit 1
}

exec "$VENV/bin/python" -u "$HERE/train_grpo.py" \
    --dataset "$DATASET" --out "$OUT" "$@"
