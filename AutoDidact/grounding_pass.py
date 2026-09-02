"""grounding_pass.py — run the entailment+diegetic judge over questions.json.

The first quality gate for the round-1 dataset. For each QA pair in
saved_data/questions.json, rebuilds the +/-1 chunk window the generator saw
(chunk_id indexes saved_data/chunks.pkl) and asks the 27B judge whether the
answer is entailed by that window and the question is diegetic (in-universe
lore, not meta corpus-talk).

Writes:
  saved_data/grounding_verdicts.jsonl  — one verdict per pair, appended as it
      lands (incremental: reruns skip pairs already judged, so interrupting
      and resuming is safe)
  saved_data/questions.filtered.json   — pairs that pass: entailed AND
      diegetic AND confidence >= threshold, annotated with the verdict
  saved_data/grounding_report.json     — per-pair table + summary stats
      (pass rates by difficulty, the dropped pairs and why)

Usage:
  python grounding_pass.py [--limit N] [--threshold 0.6] [--max-excerpt 6000]
"""

import argparse
import json
import os
import pickle
import sys

import judge

HERE = os.path.dirname(os.path.abspath(__file__))
QUESTIONS = os.path.join(HERE, "saved_data", "questions.json")
CHUNKS = os.path.join(HERE, "saved_data", "chunks.pkl")
VERDICTS = os.path.join(HERE, "saved_data", "grounding_verdicts.jsonl")
FILTERED = os.path.join(HERE, "saved_data", "questions.filtered.json")
REPORT = os.path.join(HERE, "saved_data", "grounding_report.json")


def load():
    with open(QUESTIONS) as f:
        qs = json.load(f)
    with open(CHUNKS, "rb") as f:
        chunks = pickle.load(f)
    return qs, chunks


def window_for(chunk_id, chunks, max_chars=6000):
    """The +/-1 window the generator saw (chunk_id is 1-based mid index),
    clamped at the edges and truncated to keep the judge call cheap."""
    i = chunk_id if isinstance(chunk_id, int) else 1
    lo = max(0, i - 1)
    hi = min(len(chunks), i + 2)
    excerpt = "\n\n".join(chunks[lo:hi])
    if len(excerpt) > max_chars:
        excerpt = excerpt[:max_chars]
    return excerpt


def pair_key(q, i):
    return f"{i}:{q.get('chunk_id')}:{q.get('question', '')[:60]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="judge only the first N pairs (test)")
    ap.add_argument("--threshold", type=float, default=0.6)
    ap.add_argument("--max-excerpt", type=int, default=6000)
    args = ap.parse_args()

    qs, chunks = load()
    print(f"loaded {len(qs)} pairs, {len(chunks)} chunks", flush=True)

    done = set()
    if os.path.exists(VERDICTS):
        with open(VERDICTS) as f:
            for line in f:
                try:
                    done.add(json.loads(line)["key"])
                except Exception:
                    pass
        print(f"resuming: {len(done)} pairs already judged", flush=True)

    kept, dropped = [], []
    n = 0
    for i, q in enumerate(qs):
        key = pair_key(q, i)
        if key in done:
            n += 1
            continue
        excerpt = window_for(q.get("chunk_id", 1), chunks, args.max_excerpt)
        try:
            ent, die, conf, raw = judge.judge_with_retry(
                lambda: judge.judge_entailment(q["question"], q["answer"], excerpt))
        except Exception as e:
            print(f"[{i}] JUDGE FAILED: {e} — skipping", flush=True)
            continue
        verdict = {
            "key": key, "idx": i, "chunk_id": q.get("chunk_id"),
            "question": q["question"], "answer": q["answer"],
            "difficulty": q.get("difficulty"),
            "entailed": ent, "diegetic": die, "confidence": conf,
            "raw": raw,
        }
        with open(VERDICTS, "a") as f:
            f.write(json.dumps(verdict) + "\n")
        n += 1
        if n % 25 == 0:
            print(f"... {n}/{len(qs)} judged", flush=True)
        if args.limit and n >= args.limit:
            break

    # --- summarize over ALL verdicts (including resumed ones) ---
    verdicts = []
    with open(VERDICTS) as f:
        for line in f:
            try:
                verdicts.append(json.loads(line))
            except Exception:
                pass

    def passes(v):
        return (v["entailed"] is True and v["diegetic"] is True
                and v["confidence"] is not None and v["confidence"] >= args.threshold)

    for v in verdicts:
        (kept if passes(v) else dropped).append(v)

    from collections import Counter
    print("\n=== SUMMARY ===", flush=True)
    print(f"judged: {len(verdicts)}   kept: {len(kept)}   dropped: {len(dropped)}",
          flush=True)
    print("by difficulty (kept/total):",
          dict((d, sum(1 for v in verdicts if v["difficulty"] == d and passes(v)))
               for d in Counter(v["difficulty"] for v in verdicts)), flush=True)
    bad = [v for v in verdicts if v["entailed"] is None or v["diegetic"] is None
           or v["confidence"] is None]
    print(f"unparseable judge replies: {len(bad)}", flush=True)

    if kept:
        by_q = {v["key"]: v for v in verdicts}
        kept_out = []
        for i, q in enumerate(qs):
            v = by_q.get(pair_key(q, i))
            if v and passes(v):
                kept_out.append({**q, "judge": {
                    "entailed": v["entailed"], "diegetic": v["diegetic"],
                    "confidence": v["confidence"]}})
        with open(FILTERED, "w") as f:
            json.dump(kept_out, f, indent=2)
        print(f"wrote {len(kept_out)} filtered pairs -> {FILTERED}", flush=True)

    with open(REPORT, "w") as f:
        json.dump({
            "threshold": args.threshold, "total_judged": len(verdicts),
            "kept": len(kept), "dropped": len(dropped),
            "dropped_pairs": [{k: v[k] for k in ("idx", "chunk_id", "question",
                                                 "answer", "entailed", "diegetic",
                                                 "confidence")} for v in dropped],
        }, f, indent=2)
    print(f"report -> {REPORT}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
