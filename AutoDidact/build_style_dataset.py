#!/usr/bin/env python3
"""Prepare short HF JSONL inputs, collect local teacher outputs, export SFT candidates.

Uses only Python's standard library. Run with --help for the three stages.
Generated files live under saved_data/ (git-ignored); nothing is published.
"""

import argparse
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import unicodedata
from urllib.parse import quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


DEFAULT_DIR = Path(__file__).resolve().parent / "saved_data" / "milady_style"


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize(text):
    return " ".join(unicodedata.normalize("NFC", text).split())


def dump(path, value):
    with path.open("x", encoding="utf-8") as out:
        json.dump(value, out, ensure_ascii=False, indent=2)
        out.write("\n")


def write_row(out, row):
    out.write(json.dumps(row, ensure_ascii=False) + "\n")


def read_rows(path):
    with path.open(encoding="utf-8") as stream:
        for number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except ValueError as error:
                    raise ValueError(f"invalid JSONL at {path}:{number}; preserve and repair the partial line before resuming") from error


@contextmanager
def lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("another dataset process is using this output directory") from error
        yield


def get_json(url, payload=None, timeout=120):
    request = Request(url, headers={"Content-Type": "application/json"})
    if payload is not None:
        request.data = json.dumps(payload).encode("utf-8")
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def select_inputs(rows, source, field, min_chars, max_chars, limit, seed):
    """Use complete normalized texts; never chop a longer sentence to fit."""
    unique = {}
    counts = Counter()
    for row_index, row in enumerate(rows):
        counts["source_rows"] += 1
        value = row.get(field)
        if not isinstance(value, str):
            counts["missing_text"] += 1
            continue
        text = normalize(value)
        if not min_chars <= len(text) <= max_chars:
            counts["outside_character_range"] += 1
            continue
        counts["short_rows"] += 1
        key = text.casefold()
        if key in unique:
            counts["duplicates"] += 1
            continue
        # CoEdIT stores instruction: original_text in src. Keep edits of the
        # same original together. Exact duplicate targets are removed globally.
        original = row.get("src", text)
        if source["dataset"] == "grammarly/coedit":
            original = original.partition(": ")[2] or original
        group = digest(normalize(original).casefold())
        unique[key] = {
            "id": digest(key), "input": text,
            "split": "validation" if int(group[:8], 16) % 100 < 2 else "train",
            "group_id": group,
            "source": {**source, "row_index": row_index,
                       "row_id": str(row.get("_id", row_index)),
                       "task": row.get("task"), "field": field},
        }
    counts["unique_short"] = len(unique)
    chosen = sorted(unique.values(), key=lambda row: digest(f"{seed}:{row['id']}"))
    if limit:
        chosen = chosen[:limit]
    counts["selected"] = len(chosen)
    counts.update({"selected_" + k: v for k, v in Counter(row["split"] for row in chosen).items()})
    return chosen, dict(counts)


def prepare(args):
    if any((args.directory / name).exists() for name in ("inputs.jsonl", "source.json")):
        raise ValueError("inputs already exist; use generate to resume, or choose a new --directory")
    repo = quote(args.dataset, safe="/")
    info = get_json(f"https://huggingface.co/api/datasets/{repo}/revision/{quote(args.revision, safe='')}")
    revision = info["sha"]
    source = {"dataset": args.dataset, "revision": revision, "file": args.file,
              "split": args.file.split(".")[0],
              "declared_license": (info.get("cardData") or {}).get("license")}
    url = f"https://huggingface.co/datasets/{repo}/resolve/{revision}/{quote(args.file, safe='/')}"
    sha = hashlib.sha256()
    with urlopen(url, timeout=120) as response:
        def rows():
            for line in response:
                sha.update(line)
                if line.strip():
                    yield json.loads(line)
        selected, stats = select_inputs(rows(), source, args.field, args.min_chars,
                                        args.max_chars, args.limit, args.seed)
    if not selected:
        raise ValueError("no inputs match the requested field and character range")
    with (args.directory / "inputs.jsonl").open("x", encoding="utf-8") as out:
        for row in selected:
            write_row(out, row)
    dump(args.directory / "source.json", {
        **source, "url": url, "download_sha256": sha.hexdigest(), "field": args.field,
        "min_chars": args.min_chars, "max_chars": args.max_chars, "sample_seed": args.seed,
        "stats": stats, "validation_policy": "2% by normalized original text hash; exact target dedup; near-duplicates need review",
    })
    print(json.dumps(stats, indent=2))


def quality_flags(text, output, finish_reason):
    """Conservative mechanical screens, NOT a semantic correctness judge."""
    flags = []
    if finish_reason != "stop":
        flags.append("truncated" if finish_reason == "length" else "abnormal_finish")
    if not output.strip():
        flags.append("empty")
    if len(output) > max(320, 4 * len(text)):
        flags.append("excessive_length")
    # Catch emoji parades even when individual emoji differ.
    symbol_run = 0
    for char in output:
        if unicodedata.category(char).startswith("S"):
            symbol_run += 1
        elif char.isalnum():
            symbol_run = 0
        if symbol_run >= 12:
            flags.append("symbol_run")
            break
    words = re.findall(r"\w+", output.casefold())
    grams = Counter(tuple(words[i:i + 3]) for i in range(len(words) - 2))
    if grams and max(grams.values()) >= 3:
        flags.append("repeated_phrase")
    numbers = lambda s: set(re.findall(r"\b\d+(?:[.,]\d+)*\b", s.replace("<3", "")))
    if numbers(text) != numbers(output):
        flags.append("numbers_changed")
    urls = lambda s: set(re.findall(r"https?://\S+", s))
    if urls(text) != urls(output):
        flags.append("urls_changed")
    return flags


def generation_config(args):
    config = {
        "base_url": args.base_url.rstrip("/"), "model": args.model,
        "max_tokens": args.max_tokens, "temperature": args.temperature,
        "top_p": 0.95, "repetition_penalty": args.repetition_penalty,
        "seed": 42, "stop": ["\n", "\r"], "prompt_policy": "raw input as single user message; server chat template adds persona",
    }
    if args.teacher_directory:
        teacher = args.teacher_directory
        config["teacher_files"] = {
            path.name: {"bytes": path.stat().st_size,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in sorted(teacher.glob("*.json")) if path.name != "tokenizer.json"
        }
        config["teacher_weights"] = {
            path.name: {"bytes": path.stat().st_size, "mtime_ns": path.stat().st_mtime_ns}
            for path in sorted(teacher.glob("*.safetensors"))
        }
        if not config["teacher_weights"]:
            raise ValueError("teacher directory contains no safetensors weights")
    return config


def generate(args):
    inputs = list(read_rows(args.directory / "inputs.jsonl"))
    source = json.loads((args.directory / "source.json").read_text())
    if len(inputs) != source["stats"]["selected"]:
        raise ValueError("input file does not match the completed preparation manifest")
    config = generation_config(args)
    config["inputs_sha256"] = hashlib.sha256((args.directory / "inputs.jsonl").read_bytes()).hexdigest()
    manifest = args.directory / "generation.json"
    if manifest.exists():
        if json.loads(manifest.read_text()) != config:
            raise ValueError("generation settings or inputs changed; use the original settings or a new directory")
    else:
        dump(manifest, config)
    run_id = digest(json.dumps(config, sort_keys=True))
    log = args.directory / "pairs.jsonl"
    seen = set()
    if log.exists():
        if log.stat().st_size:
            with log.open("rb") as stream:
                stream.seek(-1, os.SEEK_END)
                if stream.read(1) != b"\n":
                    raise ValueError("pairs.jsonl has an incomplete trailing line; preserve and repair it before resuming")
        for row in read_rows(log):
            if row["generation_id"] != run_id or row["id"] in seen:
                raise ValueError("mixed generation settings or duplicate IDs in pairs.jsonl")
            seen.add(row["id"])
    # Fail before spending time generating if the server/model is unavailable.
    models = get_json(config["base_url"] + "/models")
    if args.model not in {m["id"] for m in models["data"]}:
        raise ValueError(f"server does not advertise model {args.model!r}")

    def infer(row):
        payload = {key: config[key] for key in ("model", "max_tokens", "temperature", "top_p", "repetition_penalty", "seed", "stop")}
        payload["messages"] = [{"role": "user", "content": row["input"]}]
        start = time.monotonic()
        for attempt in range(3):
            try:
                response = get_json(config["base_url"] + "/chat/completions", payload,
                                    timeout=getattr(args, "timeout", 300))
                break
            except (URLError, TimeoutError, ConnectionError) as error:
                if isinstance(error, HTTPError) and error.code not in (429, 500, 502, 503, 504):
                    raise
                if attempt == 2:
                    raise
                time.sleep(2 ** attempt)
        choice = response["choices"][0]
        output = choice["message"].get("content") or ""
        flags = quality_flags(row["input"], output, choice.get("finish_reason"))
        return {**row, "output": output, "generation_id": run_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "response_id": response.get("id"), "server_fingerprint": response.get("system_fingerprint"),
                "finish_reason": choice.get("finish_reason"), "stop_reason": choice.get("stop_reason"),
                "usage": response.get("usage"), "seconds": round(time.monotonic() - start, 3),
                "quality_flags": flags, "review_status": "unreviewed"}

    remaining = [row for row in inputs if row["id"] not in seen]
    if args.limit:
        remaining = remaining[:args.limit]
    iterator = iter(remaining)
    concurrency = getattr(args, "concurrency", 1)
    processed = 0
    started = time.monotonic()
    failures = []
    with log.open("a", encoding="utf-8") as out, ThreadPoolExecutor(max_workers=concurrency) as pool:
        pending = {}

        def submit_one():
            row = next(iterator, None)
            if row is not None:
                pending[pool.submit(infer, row)] = row["id"]

        for _ in range(concurrency):
            submit_one()
        while pending:
            completed, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in completed:
                row_id = pending.pop(future)
                try:
                    record = future.result()
                except Exception as error:
                    failures.append(f"{row_id}: {error}")
                    print(f"inference failed: {failures[-1]}", file=sys.stderr, flush=True)
                    continue
                # Only this thread writes. Persist successful in-flight replies
                # even after a peer fails; restart retries the missing IDs.
                write_row(out, record)
                out.flush()
                os.fsync(out.fileno())
                processed += 1
                rate = processed / max(time.monotonic() - started, 0.001)
                print(f"{len(seen) + processed}/{len(inputs)} {row_id[:10]}: {','.join(record['quality_flags']) or 'mechanical_checks_passed'} ({rate:.2f} rows/s)", flush=True)
            if not failures:
                for _ in range(concurrency - len(pending)):
                    submit_one()
    elapsed = time.monotonic() - started
    summary = {"new_pairs": processed, "existing_pairs": len(seen), "seconds": round(elapsed, 3),
               "rows_per_second": round(processed / max(elapsed, 0.001), 4), "concurrency": concurrency,
               "generation_id": run_id, "failures": failures,
               "created_at": datetime.now(timezone.utc).isoformat()}
    with (args.directory / "runs.jsonl").open("a", encoding="utf-8") as run_log:
        write_row(run_log, summary)
    print(json.dumps(summary), flush=True)
    if failures:
        raise RuntimeError("inference failed; successful responses saved. Restart to retry missing inputs")
    print(f"Saved {processed} new pairs; {len(seen)} existing pairs skipped.")


def export(args):
    only_passing = getattr(args, "only_passing", False)
    suffix = "candidates" if only_passing else "sft"
    outputs = {split: args.directory / f"{split}.{suffix}.jsonl" for split in ("train", "validation")}
    if args.export_directory:
        outputs = {split: args.export_directory / path.name for split, path in outputs.items()}
        args.export_directory.mkdir(parents=True, exist_ok=True)
    if any(path.exists() for path in outputs.values()):
        raise ValueError("candidate exports already exist at destination")
    stats = Counter()
    flags = Counter()
    with outputs["train"].open("x", encoding="utf-8") as train, outputs["validation"].open("x", encoding="utf-8") as validation:
        for row in read_rows(args.directory / "pairs.jsonl"):
            stats["generated"] += 1
            flags.update(row["quality_flags"])
            if row["quality_flags"]:
                stats["flagged"] += 1
                if only_passing:
                    continue
            prompt = [{"role": "user", "content": row["input"]}]
            record = {"id": row["id"], "input": row["input"], "output": row["output"],
                      "prompt": prompt, "completion": row["output"],
                      "messages": prompt + [{"role": "assistant", "content": row["output"]}],
                      "source": row["source"], "quality_flags": row["quality_flags"],
                      "finish_reason": row["finish_reason"], "review_status": "unreviewed"}
            write_row(train if row["split"] == "train" else validation, record)
            stats[row["split"]] += 1
    print(json.dumps({"counts": dict(stats), "quality_flags": dict(flags),
                      "selection": "only_passing" if only_passing else "all_raw_outputs"}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare", help="download pinned HF JSONL, filter, deduplicate and sample")
    prep.add_argument("--dataset", default="grammarly/coedit")
    prep.add_argument("--revision", default="e9a255c33ef910bc33a9d2b522653fa87521583e")
    prep.add_argument("--file", default="train.jsonl")
    prep.add_argument("--field", default="tgt")
    prep.add_argument("--min-chars", type=int, default=20)
    prep.add_argument("--max-chars", type=int, default=160)
    prep.add_argument("--limit", type=int, default=0, help="selected inputs; 0 = all eligible (default)")
    prep.add_argument("--seed", type=int, default=42)
    gen = commands.add_parser("generate", help="resume concurrent teacher calls, appending each raw pair immediately")
    gen.add_argument("--base-url", default="http://127.0.0.1:18030/v1")
    gen.add_argument("--model", default="milady")
    gen.add_argument("--teacher-directory", type=Path)
    gen.add_argument("--max-tokens", type=int, default=160)
    gen.add_argument("--temperature", type=float, default=0.7)
    gen.add_argument("--repetition-penalty", type=float, default=1.15)
    gen.add_argument("--limit", type=int, default=20, help="NEW calls this invocation; 0 = all remaining")
    gen.add_argument("--concurrency", type=int, default=1, help="bounded simultaneous requests for server batching")
    gen.add_argument("--timeout", type=float, default=300, help="request timeout including queue time")
    exp = commands.add_parser("export", help="export all pairs in SFT/chat JSONL formats")
    exp.add_argument("--only-passing", action="store_true", help="optionally exclude quality-flagged rows")
    exp.add_argument("--export-directory", type=Path)
    for command in (prep, gen, exp):
        command.add_argument("--directory", type=Path, default=DEFAULT_DIR)
    args = parser.parse_args()
    if getattr(args, "limit", 0) < 0:
        parser.error("--limit cannot be negative")
    if args.command == "prepare" and not 0 < args.min_chars <= args.max_chars:
        parser.error("require 0 < min-chars <= max-chars")
    if args.command == "generate" and (args.max_tokens < 1 or args.temperature < 0 or args.repetition_penalty <= 0 or args.concurrency < 1 or args.timeout <= 0):
        parser.error("invalid generation settings")
    try:
        with lock(args.directory):
            {"prepare": prepare, "generate": generate, "export": export}[args.command](args)
    except (OSError, ValueError, KeyError, IndexError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
