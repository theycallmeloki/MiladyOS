"""train_r2_sft.py — SFT cold-start for the round-2 agentic GRPO.

Trains the base R1-1.5B to (a) emit a well-formed lore_search tool call
and (b) answer grounded in the returned passage, using the r2_warmup
trajectories (judge-verified, true-window-injected).

Runs inside autodidact-rl:r1-1.5b on the A4000. Raw-text SFT (rows already
carry the full rendered string incl. the template-seeded <think>).

Usage (docker):
  docker run --rm --gpus device=1 -v $PWD:/app \
    -e HF_HOME=/root/.cache/huggingface \
    autodidact-rl:r1-1.5b python3 -u /app/train_r2_sft.py
Env: DATA (default /app/saved_data/r2_warmup.jsonl),
     OUT (default /app/r2_training/sft), RUN_NAME, EPOCHS, LR
"""

import json
import os
import sys

import torch
from datasets import Dataset
from trl import SFTConfig, SFTTrainer
from unsloth import FastLanguageModel, is_bfloat16_supported

BASE_MODEL = os.environ.get(
    "BASE_MODEL", "unsloth/DeepSeek-R1-Distill-Qwen-1.5B-unsloth-bnb-4bit")
DATA = os.environ.get("DATA", "/app/saved_data/r2_warmup.jsonl")
OUT = os.environ.get("OUT", "/app/r2_training/sft")
EPOCHS = float(os.environ.get("EPOCHS", "2"))
LR = float(os.environ.get("LR", "2e-4"))
RUN_NAME = os.environ.get("RUN_NAME", "nano-milady-r2-sft")


def main() -> int:
    print(f"Loading {BASE_MODEL}...", flush=True)
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=BASE_MODEL,
        max_seq_length=2048,
        load_in_4bit=True,
        fast_inference=False,          # SFT: no vLLM needed
        max_lora_rank=32,
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

    print(f"Loading {DATA}...", flush=True)
    rows = [json.loads(l) for l in open(DATA) if l.strip()]
    print(f"{len(rows)} rows", flush=True)

    def render(row):
        from transformers import AutoTokenizer
        tok = tokenizer
        msgs = row["prompt"]
        text = tok.apply_chat_template(
            msgs, tokenize=False, add_generation_prompt=True)
        return {"text": text + row["completion"]}

    dataset = Dataset.from_list([render(r) for r in rows])
    print(f"dataset size {len(dataset)}", flush=True)

    args = SFTConfig(
        output_dir=OUT,
        num_train_epochs=EPOCHS,
        per_device_train_batch_size=4,
        gradient_accumulation_steps=2,
        learning_rate=LR,
        warmup_ratio=0.05,
        lr_scheduler_type="cosine",
        optim="paged_adamw_8bit",
        logging_steps=1,
        bf16=is_bfloat16_supported(),
        fp16=not is_bfloat16_supported(),
        report_to="wandb",
        run_name=RUN_NAME,
        max_seq_length=2048,
        save_strategy="no",
        dataset_text_field="text",
    )
    trainer = SFTTrainer(
        model=model,
        args=args,
        train_dataset=dataset,
        processing_class=tokenizer,
    )
    print("Starting SFT...", flush=True)
    trainer.train()
    print("SFT done — saving LoRA", flush=True)
    os.makedirs(OUT, exist_ok=True)
    model.save_lora(os.path.join(OUT, "lora"))
    print(f"LoRA saved to {OUT}/lora", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
