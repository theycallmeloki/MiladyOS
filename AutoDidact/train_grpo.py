"""train_grpo.py — the A4000's GRPO round, on our own stack.

This replaces `train_r1.py` + the vendored `UnslothGRPOTrainerTemp.py` (1399
lines patching TRL 0.14 internals, which cannot run against TRL 1.x) and the
Docker runner that never worked on this host. What we own: the recipe, the reward
stack (`r1_rewards`), the dataset *by registry name* rather than by path, and the
provenance of the round. What we depend on: maintained transformers / peft /
bitsandbytes / trl — no unsloth, no in-process vLLM, no fork.

The agentic tool loop, when it comes, plugs into TRL's `rollout_func` (a
supported seam) instead of a patched `generate`.

Usage (the launcher sets the GPU; never point this at the sensei's GPU):
    CUDA_VISIBLE_DEVICES=1 runtime/venv/bin/python train_grpo.py \
        --dataset r1.train.grounded --max-steps 101 --out r1_training
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
DEFAULT_DATASET = "r1.train.grounded"
REQUIRED_KEYS = ("prompt", "answer")


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", default=os.environ.get("DATA", DEFAULT_DATASET),
                    help="registry dataset id (not a path)")
    ap.add_argument("--base-model", default=os.environ.get("BASE_MODEL", DEFAULT_MODEL))
    ap.add_argument("--out", default=os.environ.get("OUT", os.path.join(HERE, "r1_training")))
    ap.add_argument("--max-steps", type=int, default=int(os.environ.get("MAX_STEPS", "101")))
    ap.add_argument("--num-generations", type=int, default=int(os.environ.get("NUM_GENERATIONS", "4")))
    ap.add_argument("--batch-size", type=int, default=int(os.environ.get("BATCH_SIZE", "2")))
    ap.add_argument("--grad-accum", type=int, default=int(os.environ.get("GRAD_ACCUM", "1")))
    ap.add_argument("--max-completion-length", type=int,
                    default=int(os.environ.get("MAX_COMPLETION_LENGTH", "1024")))
    ap.add_argument("--lr", type=float, default=float(os.environ.get("LR", "5e-6")))
    ap.add_argument("--lora-rank", type=int, default=int(os.environ.get("LORA_RANK", "32")))
    ap.add_argument("--report-to", default=os.environ.get("REPORT_TO", "none"),
                    help="'none' by default: a round must not need a wandb account")
    ap.add_argument("--run-name", default=os.environ.get("RUN_NAME", "nanomilady-grpo"))
    ap.add_argument("--round", default=os.environ.get("ROUND_TAG"),
                    help="round record to open/finish (rounds/<tag>/round.json)")
    ap.add_argument("--exclude-source", action="append", default=[],
                    metavar="SOURCE",
                    help="drop records whose 'source' matches (repeatable). Used "
                         "while a slice is being regenerated, so a round cannot "
                         "train on data that is about to change")
    ap.add_argument("--dry-run", action="store_true",
                    help="load everything and build the trainer, then stop before training")
    return ap.parse_args(argv)


def load_dataset_records(dataset_id, exclude_sources=()):
    """Records from the registry, schema-checked before a single GPU byte moves.

    `exclude_sources` drops slices by their `source` field, so a round can be
    explicit about what it refuses to train on (e.g. a dataset being regenerated).
    """

    """Records from the registry, schema-checked before a single GPU byte moves."""
    records = registry.load(dataset_id)
    if not records:
        raise SystemExit(f"{dataset_id} is empty — run the pipeline first")
    missing = [k for k in REQUIRED_KEYS if k not in records[0]]
    if missing:
        raise SystemExit(f"{dataset_id}: records lack {missing}; has "
                         f"{sorted(records[0])} (schema drift, fix the producer)")
    if exclude_sources:
        before = len(records)
        records = [r for r in records if r.get("source") not in exclude_sources]
        dropped = before - len(records)
        print(f"excluded sources {sorted(exclude_sources)}: dropped {dropped} "
              f"record(s), {len(records)} left", flush=True)
    questions = sum(1 for r in records if r.get("prompt") and r.get("answer"))
    if questions != len(records):
        raise SystemExit(f"{dataset_id}: {len(records) - questions} records have an "
                         f"empty prompt/answer")
    return records


def check_batch_shape(args):
    """Fail with guidance, not with TRL's one-line complaint.

    TRL generates `num_generations` completions per prompt and requires the
    generation batch (per_device_batch x grad_accum) to divide by it, so the
    cheapest valid shapes are batch=4/accum=1 or batch=2/accum=2 with four
    generations. The cost is real: one step consumes
    (per_device_batch x grad_accum) x num_generations completions.
    """
    generation_batch = args.batch_size * args.grad_accum
    if generation_batch % args.num_generations:
        raise SystemExit(
            f"batch_size({args.batch_size}) x grad_accum({args.grad_accum}) = "
            f"{generation_batch} must be divisible by num_generations"
            f"({args.num_generations}); e.g. --batch-size 4 --grad-accum 1, or "
            f"--batch-size 2 --grad-accum 2 with --num-generations 4")
    completions = generation_batch * args.num_generations
    print(f"batch: {args.batch_size}p x {args.grad_accum}a x "
          f"{args.num_generations}g = {completions} completions/step, "
          f"<= {args.max_completion_length} tokens each", flush=True)
    if args.max_completion_length < 768:
        print("warning: a completion budget under ~768 tokens truncates the "
              "think block on this student — answers never terminate and the "
              "format/correctness rewards stay flat", file=sys.stderr)


def build_trainer(args, records):
    import torch
    from datasets import Dataset
    from peft import LoraConfig
    from transformers import AutoTokenizer, BitsAndBytesConfig
    from trl import GRPOConfig, GRPOTrainer

    from r1_rewards import (correctness_reward, milady_voice_reward,
                            r1_format_reward, r1_format_soft)

    tokenizer = AutoTokenizer.from_pretrained(args.base_model)
    quantization = BitsAndBytesConfig(
        load_in_4bit=True, bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
    peft_config = LoraConfig(
        r=args.lora_rank, lora_alpha=args.lora_rank, lora_dropout=0.0, bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"])

    config = GRPOConfig(
        output_dir=args.out,
        run_name=args.run_name,
        max_steps=args.max_steps,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        num_generations=args.num_generations,
        max_completion_length=args.max_completion_length,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_steps=max(1, args.max_steps // 10),
        optim="paged_adamw_8bit",
        weight_decay=0.1,
        max_grad_norm=0.1,
        logging_steps=1,
        save_strategy="no",
        bf16=True,
        gradient_checkpointing=True,
        report_to=args.report_to,
        use_vllm=False,
        temperature=1.0,
        beta=0.04,
    )
    trainer = GRPOTrainer(
        model=args.base_model,
        reward_funcs=[r1_format_reward, r1_format_soft, correctness_reward,
                      milady_voice_reward],
        args=config,
        train_dataset=Dataset.from_list(records),
        processing_class=tokenizer,
        quantization_config=quantization,
        peft_config=peft_config,
    )
    return trainer, tokenizer


def write_provenance(args, records, started):
    """The round's own record: which dataset, which hash, which stack, which knobs."""
    meta = registry.meta(args.dataset)
    record = {
        "dataset": args.dataset,
        "dataset_sha256": meta.get("sha256"),
        "dataset_records": len(records),
        "base_model": args.base_model,
        "reward_funcs": ["r1_format_reward", "r1_format_soft", "correctness_reward",
                         "milady_voice_reward"],
        "dataset_filters": meta.get("filters", []),
        "params": {
            "max_steps": args.max_steps, "num_generations": args.num_generations,
            "batch_size": args.batch_size, "grad_accum": args.grad_accum,
            "max_completion_length": args.max_completion_length, "lr": args.lr,
            "lora_rank": args.lora_rank, "beta": 0.04, "bf16": True,
        },
        "graders": {"judge": "sensei (JUDGE_API / MILADY_SENSEI_URL)"},
        "git": registry.git_sha(),
        "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(started)),
        "seconds": round(time.time() - started, 1),
        "run_name": args.run_name,
    }
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "run.json"), "w") as fh:
        json.dump(record, fh, indent=1)
        fh.write("\n")
    return record


def main(argv=None):
    args = parse_args(argv)
    started = time.time()
    import torch

    print(f"dataset: {args.dataset} (registry) | base: {args.base_model} | "
          f"cuda devices visible: {torch.cuda.device_count()}", flush=True)
    if torch.cuda.device_count() != 1:
        print("warning: more than one GPU is visible — the launcher should pin "
              "CUDA_VISIBLE_DEVICES so a round cannot touch the sensei",
              file=sys.stderr, flush=True)
    check_batch_shape(args)
    records = load_dataset_records(args.dataset, args.exclude_source)
    if args.round:
        from bus import round as round_record
        round_record.open_round(args.round, dataset=args.dataset, base_model=args.base_model,
                          recipe={"max_steps": args.max_steps,
                                  "num_generations": args.num_generations,
                                  "batch_size": args.batch_size,
                                  "grad_accum": args.grad_accum,
                                  "max_completion_length": args.max_completion_length,
                                  "learning_rate": args.lr,
                                  "lora_rank": args.lora_rank,
                                  "excluded_sources": sorted(args.exclude_source)},
                          champion_reference=(round_record.champion() or {}).get("tag"))
    print(f"{len(records)} records, {registry.meta(args.dataset)['sha256'][:23]}…",
          flush=True)
    trainer, tokenizer = build_trainer(args, records)
    if args.dry_run:
        print("dry run: trainer built, nothing trained", flush=True)
        return 0
    trainer.train()
    lora_dir = os.path.join(args.out, "lora")
    trainer.save_model(lora_dir)
    tokenizer.save_pretrained(lora_dir)
    record = write_provenance(args, records, started)
    if args.round:
        from bus import round as round_record
        log = getattr(trainer.state, "log_history", []) or []
        metrics = {k: v for k, v in (log[-1] if log else {}).items()
                   if k in ("train_loss", "epoch", "reward", "reward_std",
                            "grad_norm", "num_tokens", "train_runtime",
                            "completions/mean_length", "completions/clipped_ratio")}
        round_record.finish_training(args.round, metrics=metrics, lora_dir=lora_dir,
                                     seconds=record["seconds"])
    print(f"round complete in {record['seconds']}s — LoRA at {lora_dir}", flush=True)
    print(f"provenance: {os.path.join(args.out, 'run.json')}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
