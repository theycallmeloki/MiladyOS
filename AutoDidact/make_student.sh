#!/usr/bin/env bash
# make_student.sh — LoRA (or merged HF dir) -> a servable GGUF, in one step.
#
# The missing half of Phase E's "serve nanomilady via llama.cpp": merge the
# adapter into the bf16 base, convert with llama.cpp's own converter, quantize.
# The converter is VENDORED (vendor/llamacpp/, taken from the miladyos image's
# /llamacpp at build 10709 — the same build as the llama-server that serves it),
# so this step needs no network and no container.
#
#   ./make_student.sh r2_training/lora rounds/round-0002-sft
#   QUANT=Q5_K_M ./make_student.sh ...        # smaller file
#
# Output: <out_dir>/merged/  (bf16 HF, what a later round trains on top of)
#         <out_dir>/gguf/<name>-<QUANT>.gguf  (what a node serves)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="$HERE/runtime/venv"
CONVERTER="$HERE/vendor/llamacpp/convert_hf_to_gguf.py"

LORA="${1:?usage: make_student.sh <lora_dir> <out_dir>}"
OUT="${2:?usage: make_student.sh <lora_dir> <out_dir>}"
QUANT="${QUANT:-Q8_0}"
NAME="$(basename "$OUT")"
MERGED="$OUT/merged"
GGUF_DIR="$OUT/gguf"
GGUF="$GGUF_DIR/$NAME-f16.gguf"
FINAL="$GGUF_DIR/$NAME-$QUANT.gguf"

[ -x "$VENV/bin/python" ] || { echo "no runtime at $VENV" >&2; exit 1; }
[ -f "$CONVERTER" ] || { echo "no converter at $CONVERTER" >&2; exit 1; }

# Quantizer: prefer one next to the llama-server we can find, else PATH.
QUANTIZE="${LLAMA_QUANTIZE:-}"
if [ -z "$QUANTIZE" ]; then
    for candidate in "$(dirname "${LLAMA_SERVER:-/nonexistent}")/llama-quantize" \
                     "$HOME/Documents/Bonsai-demo/bin/cuda/llama-quantize"; do
        [ -x "$candidate" ] && QUANTIZE="$candidate" && break
    done
fi
[ -n "$QUANTIZE" ] && [ -x "$QUANTIZE" ] || {
    echo "no llama-quantize found; set LLAMA_QUANTIZE=/path/to/llama-quantize" >&2
    exit 1
}

mkdir -p "$MERGED" "$GGUF_DIR"

if [ -f "$LORA/adapter_config.json" ]; then
    echo "--- merge: $LORA -> $MERGED"
    "$VENV/bin/python" "$HERE/merge_lora.py" "$LORA" "$MERGED"
else
    echo "--- $LORA is not a LoRA adapter dir; treating it as an already-merged model"
    [ -f "$LORA/config.json" ] || { echo "not a HF model dir either: $LORA" >&2; exit 1; }
    MERGED="$LORA"
fi

echo "--- convert: $MERGED -> $GGUF"
# The converter imports `gguf`, and llama.cpp's converter only works against the
# gguf-py that shipped with it — so the vendored binding wins over anything in
# site-packages. That is why PYTHONPATH is set here rather than pip-installing a
# PyPI gguf that may be a different vintage.
PYTHONPATH="$HERE/vendor/llamacpp/gguf-py${PYTHONPATH:+:$PYTHONPATH}" \
    "$VENV/bin/python" "$CONVERTER" "$MERGED" --outfile "$GGUF" --outtype f16

echo "--- quantize: $QUANT"
"$QUANTIZE" "$GGUF" "$FINAL" "$QUANT"

python3 - "$FINAL" <<'PY'
import sys, os
path = sys.argv[1]
print(f"--- ready: {path} ({os.path.getsize(path) / 2**30:.2f} GiB)")
print(f"    serve with: ./serve_student.sh {path}")
PY
