#!/usr/bin/env bash
# serve_student.sh — serve a candidate GGUF on :8091, the port everything expects.
#
# This is the student the gate scores and the model a node would actually run:
# llama.cpp, the same engine as the sensei's, so a gate result measures the thing
# that would ship rather than a training-time approximation.
#
#   ./serve_student.sh rounds/round-0002-sft/gguf/round-0002-sft-Q8_0.gguf
#   GPU=1 ./serve_student.sh ...        # if you would rather use the A4000
#   PORT=8092 ./serve_student.sh ...    # to compare two candidates side by side
#
# GPU 0 by default: the A4000 is the trainer, and a quantized 1.5B fits in the
# room left beside the sensei. Stop it with the process manager (hub stop) or
# Ctrl-C; nothing here is daemonized on purpose.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
MODEL="${1:?usage: serve_student.sh <model.gguf>}"
PORT="${PORT:-8091}"
GPU="${GPU:-0}"
CTX="${CTX:-16384}"

# Find a llama-server: explicit override, then PATH, then the known local build.
LLAMA="${LLAMA_SERVER:-}"
if [ -z "$LLAMA" ]; then
    for candidate in "$HOME/Documents/Bonsai-demo/bin/cuda/llama-server" \
                     "$(command -v llama-server 2>/dev/null || true)"; do
        [ -n "$candidate" ] && [ -x "$candidate" ] && LLAMA="$candidate" && break
    done
fi
[ -n "$LLAMA" ] && [ -x "$LLAMA" ] || {
    echo "no llama-server found; set LLAMA_SERVER=/path/to/llama-server" >&2
    exit 1
}
[ -f "$MODEL" ] || { echo "no such model: $MODEL" >&2; exit 1; }

if curl -s --max-time 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    echo "something already serves :$PORT — refusing to start a second one" >&2
    exit 1
fi

echo "--- serving $MODEL on :$PORT (GPU $GPU, ctx $CTX) with $LLAMA"
export CUDA_VISIBLE_DEVICES="$GPU"
exec "$LLAMA" -m "$MODEL" \
    --host 127.0.0.1 --port "$PORT" \
    -ngl 99 -fa on -c "$CTX" --jinja
