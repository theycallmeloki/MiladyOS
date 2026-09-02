"""train_r1.py — round-1 GRPO for nano-milady on DeepSeek-R1-Distill-Qwen-1.5B.

Based on unsloth's official Feb-2025 GRPO notebook structure (the era-exact
base for this container's unsloth 2025.3.6 / vllm 0.7.2 / transformers 4.49
stack), adapted:
  - student: unsloth/DeepSeek-R1-Distill-Qwen-1.5B-unsloth-bnb-4bit (A4000)
  - dataset: saved_data/r1_train.jsonl (judge-verified lore QA, 633 pairs)
  - rewards (comprehension round): R1 format (<think>...</think> + answer)
    + correctness graded by the 27B judge (JUDGE_API, focused-judge style)
  - use_agentic_generate=False: plain GRPO rollouts (the search-tool loop is
    the next workstream; this round proves the GRPO + 27B-judge pipeline)

Run inside the rl_training container (era-locked), GPU 1 (A4000). The 27B
judge serves on the 3090 (GPU 0) — reachable from the container at the
docker bridge gateway (JUDGE_API=http://172.17.0.1:18020/v1/chat/completions).
"""

import json
import os
import re
import sys

import torch
from datasets import Dataset
from unsloth import FastLanguageModel, is_bfloat16_supported

sys.path.insert(0, "/app")  # vendored modules + mounted judge.py
from UnslothGRPOTrainerTemp import UnslothGRPOConfig, UnslothGRPOTrainer  # noqa: E402
from r1_rewards import (  # noqa: E402  (mounted /app/r1_rewards.py)
    correctness_reward, r1_format_reward, r1_format_soft)

BASE_MODEL = os.environ.get(
    "BASE_MODEL", "unsloth/DeepSeek-R1-Distill-Qwen-1.5B-unsloth-bnb-4bit")
DATA = os.environ.get("DATA", "/app/saved_data/r1_train.jsonl")
OUT = os.environ.get("OUT", "/app/r1_training")
MAX_STEPS = int(os.environ.get("MAX_STEPS", "101"))
RUN_NAME = os.environ.get("RUN_NAME", "nano-milady-r1-r1")


def load_data(path: str) -> Dataset:
    recs = [json.loads(l) for l in open(path) if l.strip()]
    return Dataset.from_list(recs)


def main() -> int:
    print(f"Loading {BASE_MODEL}...", flush=True)
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=BASE_MODEL,
        max_seq_length=4096,
        load_in_4bit=True,
        fast_inference=True,          # vLLM-backed generation
        max_lora_rank=32,
        gpu_memory_utilization=0.55,  # proven envelope on the 16GB A4000
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=32,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        lora_alpha=32,
        use_gradient_checkpointing="unsloth",
        random_state=3407,
    )

    print(f"Loading dataset from {DATA}...", flush=True)
    dataset = load_data(DATA)
    print(f"{len(dataset)} records", flush=True)

    training_args = UnslothGRPOConfig(
        use_vllm=True,
        use_agentic_generate=False,   # comprehension round: no tool loop yet
        learning_rate=5e-6,
        adam_beta1=0.9,
        adam_beta2=0.99,
        weight_decay=0.1,
        warmup_ratio=0.1,
        lr_scheduler_type="cosine",
        optim="paged_adamw_8bit",
        logging_steps=1,
        bf16=is_bfloat16_supported(),
        fp16=not is_bfloat16_supported(),
        per_device_train_batch_size=2,
        gradient_accumulation_steps=1,
        num_generations=4,
        max_prompt_length=2048,
        max_completion_length=1024,
        max_steps=MAX_STEPS,
        save_steps=50,
        max_grad_norm=0.1,
        report_to="wandb",
        run_name=RUN_NAME,
        output_dir=OUT,
    )
    trainer = UnslothGRPOTrainer(
        model=model,
        processing_class=tokenizer,
        reward_funcs=[r1_format_reward, r1_format_soft, correctness_reward],
        args=training_args,
        train_dataset=dataset,
    )

    print("Starting GRPO...", flush=True)
    trainer.train()
    print("Training complete — saving LoRA", flush=True)
    os.makedirs(OUT, exist_ok=True)
    model.save_lora(os.path.join(OUT, "lora"))
    print(f"LoRA saved to {OUT}/lora", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
