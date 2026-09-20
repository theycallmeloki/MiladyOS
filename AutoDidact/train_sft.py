"""train_sft.py — the SFT cold-start, on our own stack.

This is the step the round evidence demands. Round 0001's GRPO run scored
`correctness_reward/mean = 0` for all 24 steps: the bare 1.5B cannot answer
grounded lore questions, so every group had uniform rewards and zero advantage —
no gradient at all. GRPO cannot bootstrap a 0 % base rate; a capability has to be
*shown* first, which is what this trainer does with `r2.warmup` (684 rows that
demonstrate `<think>` → `<tool>{...}</tool>` → answer-from-result).

Replaces `train_r2_sft.py` — the last unsloth import in the tree — with the same
maintained stack as `train_grpo.py`: transformers + peft + bitsandbytes + TRL.

Usage (the launcher pins the GPU; never point this at the sensei's GPU):
    CUDA_VISIBLE_DEVICES=1 runtime/venv/bin/python train_sft.py \
        --dataset r2.warmup --max-steps 120 --out r2_training
"""

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from bus import registry  # noqa: E402

DEFAULT_MODEL = "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B"
DEFAULT_DATASET = "r2.warmup"
REQUIRED_KEYS = ("prompt", "completion")


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", default=os.environ.get("DATA", DEFAULT_DATASET),
                    help="registry dataset id (not a path)")
    ap.add_argument("--base-model", default=os.environ.get("BASE_MODEL", DEFAULT_MODEL))
    ap.add_argument("--out", default=os.environ.get("OUT", os.path.join(HERE, "r2_training")))
    ap.add_argument("--max-steps", type=int, default=int(os.environ.get("MAX_STEPS", "120")))
    ap.add_argument("--batch-size", type=int, default=int(os.environ.get("BATCH_SIZE", "4")))
    ap.add_argument("--grad-accum", type=int, default=int(os.environ.get("GRAD_ACCUM", "2")))
    ap.add_argument("--lr", type=float, default=float(os.environ.get("LR", "2e-4")))
    ap.add_argument("--lora-rank", type=int, default=int(os.environ.get("LORA_RANK", "32")))
    ap.add_argument("--max-length", type=int, default=int(os.environ.get("MAX_LENGTH", "2048")))
    ap.add_argument("--report-to", default=os.environ.get("REPORT_TO", "none"))
    ap.add_argument("--run-name", default=os.environ.get("RUN_NAME", "nanomilady-sft"))
    ap.add_argument("--round", default=os.environ.get("ROUND_TAG"),
                    help="round record to open/finish (rounds/<tag>/round.json)")
    ap.add_argument("--dry-run", action="store_true",
                    help="load everything and build the trainer, then stop")
    return ap.parse_args(argv)


def load_dataset_records(dataset_id):
    records = registry.load(dataset_id)
    if not records:
        raise SystemExit(f"{dataset_id} is empty — run the pipeline first")
    missing = [k for k in REQUIRED_KEYS if k not in records[0]]
    if missing:
        raise SystemExit(f"{dataset_id}: records lack {missing}; has "
                         f"{sorted(records[0])} (schema drift, fix the producer)")
    return records


def render(records, tokenizer):
    """Chat prompt + demonstrated completion, as raw text.

    The prompt is rendered with `add_generation_prompt=True` so the SFT text is
    exactly the serving shape; the completion (including its tool call and the
    result) is appended verbatim.
    """
    texts = []
    for record in records:
        prompt = tokenizer.apply_chat_template(
            record["prompt"], tokenize=False, add_generation_prompt=True)
        texts.append({"text": prompt + record["completion"]})
    return texts


def build_trainer(args, records):
    import torch
    from datasets import Dataset
    from peft import LoraConfig
    from transformers import AutoTokenizer, BitsAndBytesConfig
    from trl import SFTConfig, SFTTrainer

    tokenizer = AutoTokenizer.from_pretrained(args.base_model)
    texts = render(records, tokenizer)
    quantization = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
    peft_config = LoraConfig(
        r=args.lora_rank, lora_alpha=args.lora_rank, lora_dropout=0.0, bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"])
    config = SFTConfig(
        output_dir=args.out,
        run_name=args.run_name,
        max_steps=args.max_steps,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_steps=max(1, args.max_steps // 10),
        optim="paged_adamw_8bit",
        weight_decay=0.1,
        max_grad_norm=0.3,
        logging_steps=1,
        save_strategy="no",
        bf16=True,
        gradient_checkpointing=True,
        report_to=args.report_to,
        dataset_text_field="text",
        max_length=args.max_length,
        packing=False,
    )
    trainer = SFTTrainer(
        model=args.base_model,
        args=config,
        train_dataset=Dataset.from_list(texts),
        processing_class=tokenizer,
        quantization_config=quantization,
        peft_config=peft_config,
    )
    return trainer, tokenizer


def main(argv=None):
    args = parse_args(argv)
    started = time.time()
    import torch

    print(f"dataset: {args.dataset} (registry) | base: {args.base_model} | "
          f"cuda devices visible: {torch.cuda.device_count()}", flush=True)
    if torch.cuda.device_count() != 1:
        print("warning: more than one GPU is visible — the launcher should pin "
              "CUDA_VISIBLE_DEVICES so a run cannot touch the sensei",
              file=sys.stderr, flush=True)
    records = load_dataset_records(args.dataset)
    print(f"{len(records)} rows, {registry.meta(args.dataset)['sha256'][:23]}…",
          flush=True)
    if args.round:
        from bus import round as round_record
        round_record.open_round(args.round, dataset=args.dataset,
                                base_model=args.base_model,
                                recipe={"kind": "sft", "max_steps": args.max_steps,
                                        "batch_size": args.batch_size,
                                        "grad_accum": args.grad_accum,
                                        "lr": args.lr, "lora_rank": args.lora_rank,
                                        "max_length": args.max_length},
                                champion_reference=(round_record.champion() or {}).get("tag"))
    trainer, tokenizer = build_trainer(args, records)
    if args.dry_run:
        print("dry run: trainer built, nothing trained", flush=True)
        return 0

    trainer.train()
    lora_dir = os.path.join(args.out, "lora")
    trainer.save_model(lora_dir)
    tokenizer.save_pretrained(lora_dir)
    seconds = round(time.time() - started, 1)
    log = getattr(trainer.state, "log_history", []) or []
    metrics = {k: v for k, v in (log[-1] if log else {}).items()
               if k in ("train_loss", "grad_norm", "learning_rate", "epoch",
                        "num_tokens", "train_runtime")}
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "run.json"), "w") as fh:
        json.dump({"kind": "sft", "dataset": args.dataset,
                   "dataset_sha256": registry.meta(args.dataset).get("sha256"),
                   "dataset_records": len(records), "base_model": args.base_model,
                   "params": {"max_steps": args.max_steps, "lr": args.lr,
                              "batch_size": args.batch_size,
                              "grad_accum": args.grad_accum,
                              "lora_rank": args.lora_rank,
                              "max_length": args.max_length},
                   "git": registry.git_sha(), "seconds": seconds,
                   "run_name": args.run_name}, fh, indent=1)
        fh.write("\n")
    if args.round:
        from bus import round as round_record
        round_record.finish_training(args.round, metrics=metrics, lora_dir=lora_dir,
                                     seconds=seconds)
    print(f"SFT complete in {seconds}s — LoRA at {lora_dir}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
