"""merge_lora.py — merge a trained LoRA into the bf16 base for serving/eval.

Runs on the host runtime (runtime/venv: transformers + peft + torch). The device
comes from MILADY_MERGE_DEVICE (default cuda:0, or cpu when no GPU is visible).
Plain HF merge (no unsloth/4bit API needed): the adapters trained on the
4-bit base merge into the bf16 base of the same weights, and vllm 0.7.2 can
serve the resulting bf16 model (it cannot serve bnb-4bit).

Usage:
  docker run --gpus device=1 -v $PWD:/work -v <hf-cache-user>:/root/.cache/huggingface \
    autodidact-rl:r1-1.5b python3 -u /work/merge_lora.py /work/r1_training/lora /work/r1_training/merged-r1c
"""

import os
import sys

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

BASE = os.environ.get("BASE_MODEL", "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B")
# A merge is memory-bound, not compute-bound: `cpu` is a perfectly good choice and
# leaves both GPUs to whatever else is running (set MILADY_MERGE_DEVICE=cuda:0 to
# use the 3090, or 1 for the A4000).
DEVICE = os.environ.get("MILADY_MERGE_DEVICE",
                        "cuda:0" if torch.cuda.is_available() else "cpu")
lora_path, out_dir = sys.argv[1], sys.argv[2]

print(f"loading bf16 base {BASE} on {DEVICE}...", flush=True)
model = AutoModelForCausalLM.from_pretrained(
    BASE, torch_dtype=torch.bfloat16, device_map=DEVICE)
print(f"loading LoRA {lora_path}...", flush=True)
model = PeftModel.from_pretrained(model, lora_path)
print("merging + unloading...", flush=True)
model = model.merge_and_unload()
os.makedirs(out_dir, exist_ok=True)
model.save_pretrained(out_dir, safe_serialization=True)
tok = AutoTokenizer.from_pretrained(BASE)
tok.save_pretrained(out_dir)
print(f"merged model saved to {out_dir}", flush=True)
