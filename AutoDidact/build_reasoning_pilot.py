#!/usr/bin/env python3
"""Prepare and restyle 100 short CoT examples. Separate from the 57k collection."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlencode
from urllib.request import urlopen

from build_style_dataset import digest, dump, get_json, lock, normalize, quality_flags, read_rows, write_row

DATASET = "kaist-ai/CoT-Collection"
REVISION = "c9d352cdc119df4a4f7526d100e4acb4a72a7a5c"
DEFAULT = Path(__file__).resolve().parent / "saved_data" / "milady_reasoning_pilot"
ABBREVIATIONS = re.compile(r"\b(?:Mr|Mrs|Ms|Dr|Prof|St|Jr|Sr|vs|etc|e\.g|i\.e)\.$", re.I)


def chunks(text, maximum=240):
    """Keep short rationales intact; group sentences, never cut at a character cap.

    Conservative heuristic, not a general sentence parser. Reject oversized
    indivisible sentences rather than break decimals, abbreviations or equations.
    """
    text = normalize(text)
    if len(text) <= maximum:
        return [text]
    sentences, start = [], 0
    for match in re.finditer(r'(?<=[.!?])\s+(?=[A-Z"\'])', text):
        prefix = text[start:match.start()]
        if ABBREVIATIONS.search(prefix) or re.search(r"\b[A-Z]\.$", prefix):
            continue
        sentences.append(prefix)
        start = match.end()
    sentences.append(text[start:])
    grouped = []
    for sentence in sentences:
        if len(sentence) > maximum:
            return []
        if grouped and len(grouped[-1]) + 1 + len(sentence) <= maximum:
            grouped[-1] += " " + sentence
        else:
            grouped.append(sentence)
    return grouped


def eligible(entry):
    row = entry["row"]
    if entry.get("truncated_cells") or not all(isinstance(row.get(k), str) for k in ("source", "target", "rationale", "task")):
        return None
    question, rationale, answer = [normalize(row[k]) for k in ("source", "rationale", "target")]
    if not (20 <= len(question) <= 900 and 40 <= len(rationale) <= 480 and 1 <= len(answer) <= 160):
        return None
    # This pilot is prose-only; code/LaTeX require different segmentation.
    if any(mark in question + rationale + answer for mark in ("```", "\\frac", "\\begin", "<think>", "</think>")):
        return None
    parts = chunks(rationale)
    if not parts or len(parts) > 3:
        return None
    return {"id": digest(question.casefold()), "input": question, "original_rationale": rationale,
            "original_answer": answer, "rationale_chunks": parts, "task": row["task"],
            "source": {"dataset": DATASET, "revision": REVISION, "config": "en", "split": "train",
                       "row_index": entry["row_idx"], "declared_license": "cc-by-4.0"}}


def prepare(directory):
    if (directory / "inputs.jsonl").exists():
        raise ValueError("pilot inputs already exist; use generate to resume")
    pages_dir = directory / "source_pages"
    pages_dir.mkdir(exist_ok=True)
    pools, seen, page_hashes = defaultdict(list), set(), {}
    # Fixed windows across the corpus, not a uniform random sample.
    offsets = [0, 1000, 10000, 50000, 100000, 200000, 350000, 500000, 750000, 1000000,
               1200000, 1400000, 1600000, 1800000]
    for offset in offsets:
        path = pages_dir / f"{offset}.json"
        if path.exists():
            cached = json.loads(path.read_text())
        else:
            url = "https://datasets-server.huggingface.co/rows?" + urlencode({
                "dataset": DATASET, "config": "en", "split": "train", "offset": offset, "length": 100})
            with urlopen(url, timeout=120) as response:
                cached = {"url": url, "revision": response.headers.get("x-revision"),
                          "retrieved_at": datetime.now(timezone.utc).isoformat(), "data": json.load(response)}
            if cached["revision"] != REVISION:
                raise ValueError("viewer revision differs from pinned source")
            dump(path, cached)
        if cached["revision"] != REVISION or cached["data"].get("partial"):
            raise ValueError("unverified or partial source page")
        page_hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        for entry in cached["data"]["rows"]:
            row = eligible(entry)
            if row and row["id"] not in seen:
                pools[row["task"]].append(row)
                seen.add(row["id"])
        print(f"source offset {offset}: {len(seen)} eligible across {len(pools)} tasks", flush=True)
    for pool in pools.values():
        pool.sort(key=lambda row: row["id"])
    selected = []
    for round_index in range(10):
        for task in sorted(pools):
            if round_index < len(pools[task]) and len(selected) < 100:
                selected.append(pools[task][round_index])
    if len(selected) != 100:
        raise ValueError(f"only {len(selected)} eligible balanced examples; no manifest created")
    for index, row in enumerate(sorted(selected, key=lambda row: row["id"])):
        row["split"] = "validation" if index < 10 else "train"
    with (directory / "inputs.jsonl").open("x") as out:
        for row in selected:
            write_row(out, row)
    dump(directory / "source.json", {"dataset": DATASET, "revision": REVISION,
        "declared_license": "cc-by-4.0", "source_page_sha256": page_hashes,
        "selection": "fixed 100-row windows; short prose; round-robin tasks, max 10 per task; exact question dedup",
        "counts": {"scanned": 100 * len(offsets), "eligible": len(seen), "selected": len(selected)},
        "tasks": dict(Counter(row["task"] for row in selected)),
        "split_policy": "90 train / 10 local validation by question hash rank; all from source train, not benchmark test"})


def flags_for(original, output, finish):
    flags = quality_flags(original, output, finish)
    negatives = lambda s: bool(re.search(r"\b(?:not|no|never|cannot|without)\b|n't", s, re.I))
    if negatives(original) != negatives(output):
        flags.append("negation_changed")
    if re.search(r"<\|.*?\|>|</?think>", output):
        flags.append("control_token_text")
    return flags


def literal_text(text):
    # Preserve raw output separately, but prevent teacher-produced delimiters
    # from creating extra roles/think sections in candidate training content.
    return re.sub(r"<\|.*?\|>|</?think>", lambda m: html.escape(m.group()), text)


def generate(directory, concurrency):
    rows = list(read_rows(directory / "inputs.jsonl"))
    config = {"model": "milady", "max_tokens": 160, "temperature": 0.5,
              "top_p": 0.95, "repetition_penalty": 1.25, "seed": 42, "stop": ["\n", "\r"]}
    manifest = {"request": config, "base_url": "http://127.0.0.1:18030/v1",
                "inputs_sha256": hashlib.sha256((directory / "inputs.jsonl").read_bytes()).hexdigest(),
                "prompt_policy": "raw chunk/reference answer as one user message; teacher template adds style instruction"}
    path = directory / "generation.json"
    if path.exists():
        if json.loads(path.read_text()) != manifest:
            raise ValueError("generation configuration changed")
    else:
        dump(path, manifest)
    jobs = {}
    for row in rows:
        for index, text in enumerate(row["rationale_chunks"] + [row["original_answer"]]):
            jobs[f"{row['id']}:{index}"] = text
    log = directory / "segments.jsonl"
    saved = {}
    if log.exists():
        if log.stat().st_size:
            with log.open("rb") as stream:
                stream.seek(-1, os.SEEK_END)
                if stream.read(1) != b"\n":
                    raise ValueError("incomplete segment log; preserve and repair before resume")
        for item in read_rows(log):
            if item["id"] in saved or jobs.get(item["id"]) != item["input"]:
                raise ValueError("duplicate or mismatched segment log")
            saved[item["id"]] = item

    def infer(key, text):
        payload = {**config, "messages": [{"role": "user", "content": text}]}
        start = time.monotonic()
        response = get_json(manifest["base_url"] + "/chat/completions", payload, timeout=240)
        choice = response["choices"][0]
        output = choice["message"].get("content") or ""
        return {"id": key, "input": text, "output": output, "response": response,
                "seconds": round(time.monotonic() - start, 3),
                "flags": flags_for(text, output, choice["finish_reason"])}

    errors = []
    # Small pilot: finite queue of at most 400 tasks, bounded active requests.
    with log.open("a") as out, ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(infer, k, v): k for k, v in jobs.items() if k not in saved}
        for future in as_completed(futures):
            try:
                item = future.result()
            except Exception as error:
                errors.append(f"{futures[future]}: {error}")
                continue
            write_row(out, item)
            out.flush()
            os.fsync(out.fileno())
            saved[item["id"]] = item
            print(f"saved {len(saved)}/{len(jobs)} segments", flush=True)
    if errors:
        raise RuntimeError("successful segments saved; rerun to retry: " + "; ".join(errors))
    if (directory / "pairs.jsonl").exists():
        raise ValueError("pairs already assembled; refusing overwrite")
    review = ["# Milady reasoning pilot: all 100 candidates, unreviewed\n",
              "Flags are mechanical diagnostics, not correctness judgments. Original source explanations can also be wrong.\n"]
    counts = Counter()
    with (directory / "pairs.jsonl").open("x") as out:
        for n, row in enumerate(rows, 1):
            parts = [saved[f"{row['id']}:{i}"] for i in range(len(row["rationale_chunks"]) + 1)]
            reasoning = "\n".join(p["output"] for p in parts[:-1])
            answer = parts[-1]["output"]
            flags = sorted({flag for p in parts for flag in p["flags"]})
            if row["original_answer"].casefold() not in answer.casefold():
                flags.append("reference_answer_not_literal")
            counts.update(flags)
            counts["rows_with_flags"] += bool(flags)
            completion = "<think>\n" + literal_text(reasoning) + "\n</think>\n" + literal_text(answer)
            record = {**row, "reasoning": reasoning, "answer": answer, "output": completion,
                      "messages": [{"role": "user", "content": row["input"]},
                                   {"role": "assistant", "content": completion}],
                      "segment_ids": [p["id"] for p in parts], "quality_flags": flags,
                      "review_status": "unreviewed", "training_approved": False}
            write_row(out, record)
            review.append(f"## {n}. {row['task']} — {row['id'][:12]}\n\nFlags: {', '.join(flags) or 'none (not a semantic pass)'}\n")
            for title, text in [("Question", row["input"]), ("Original rationale", row["original_rationale"]),
                                ("Styled rationale", reasoning), ("Reference answer", row["original_answer"]), ("Styled answer", answer)]:
                review.append(f"### {title}\n\n" + "\n".join("> " + line for line in text.splitlines()) + "\n")
    with (directory / "review.md").open("x") as out:
        out.write("\n".join(review))
    dump(directory / "summary.json", {"pairs": len(rows), "segments": len(jobs), "flags": dict(counts),
                                     "all_outputs_retained": True, "training_started": False})
    print(json.dumps({"pairs": len(rows), "segments": len(jobs), "flags": dict(counts)}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "generate"])
    parser.add_argument("--directory", type=Path, default=DEFAULT)
    parser.add_argument("--concurrency", type=int, default=32)
    args = parser.parse_args()
    if args.concurrency < 1:
        parser.error("concurrency must be positive")
    with lock(args.directory):
        if args.command == "prepare":
            prepare(args.directory)
        else:
            generate(args.directory, args.concurrency)


if __name__ == "__main__":
    main()
