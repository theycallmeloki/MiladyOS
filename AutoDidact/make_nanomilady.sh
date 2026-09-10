#!/usr/bin/env bash
# make_nanomilady.sh — produce a servable nano-milady from a trained LoRA.
#
# This is the missing final step of the pipeline: train (run_r1.sh / GRPO or
# run_r2_sft.sh / SFT) -> LoRA -> MERGE into the bf16 base -> nanomilady.
#
# Why it exists: merge_lora.py was only ever invoked by hand, so "always have
# a nanomilady" depended on remembering the exact docker incantation. This
# wraps it and picks sane defaults. The Docker runners hang on this host
# (overlayfs on btrfs), so the default here is a HOST run using the
# era-pinned AutoDidact venv.
#
# Usage:
#   ./make_nanomilady.sh [LORA_DIR] [OUT_DIR]
#     LORA_DIR  default: ./r1_training/lora
#     OUT_DIR   default: ./nanomilady
#
# Env overrides:
#   PYTHON      interpreter with peft+transformers (default: ./.venv/bin/python)
#   HF_HOME     HF cache root (default: the shared storage-drive cache)
#   BASE_MODEL  bf16 base to merge into (must match the LoRA's training base)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
LORA="${1:-$HERE/r1_training/lora}"
OUT="${2:-$HERE/nanomilady}"
PYTHON="${PYTHON:-$HERE/.venv/bin/python}"

# The shared cache already holds unsloth/DeepSeek-R1-Distill-Qwen-1.5B (bf16),
# which is exactly the base merge_lora.py needs.
export HF_HOME="${HF_HOME:-/run/media/laneone/storage/models/hf-cache-user}"
export BASE_MODEL="${BASE_MODEL:-unsloth/DeepSeek-R1-Distill-Qwen-1.5B}"

if [[ ! -d "$LORA" ]]; then
  echo "no LoRA at $LORA — train first (run_r1.sh / run_r2_sft.sh)" >&2
  exit 1
fi
if [[ ! -x "$PYTHON" ]]; then
  echo "no interpreter at $PYTHON — set PYTHON=<venv with peft+transformers>" >&2
  exit 1
fi

echo "merging $LORA -> $OUT (base $BASE_MODEL)"
"$PYTHON" -u "$HERE/merge_lora.py" "$LORA" "$OUT"
echo "nanomilady ready at $OUT"
echo "serve:  vllm serve $OUT --served-model-name nanomilady --port 8081"
