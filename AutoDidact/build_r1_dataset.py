"""build_r1_dataset.py — round-1 dataset for DeepSeek-R1-Distill-Qwen-1.5B.

Turns the judge-verified QA (667 windowed + 35 identity) into a GRPO-ready
HuggingFace dataset for the official-notebook-style trainer:
  {prompt: [system (compact milady voice), user (question)], answer: reference}

- windowed pairs carry chunk_id + target window (chunk_id +/- 1) so a later
  tool-call round can score retrieval recall without re-deriving targets
- identity pairs are marked (no single target chunk; synthesis answers)
- frozen eval split (10%, seed 42) across BOTH sources so progress is
  comparable across rounds — never regenerate the split
- outputs: saved_data/r1_train.json, r1_eval.json (JSONL, HF-loadable)

Usage: python build_r1_dataset.py
"""

import json
import os
import pickle
import random
import re
import sys

from bus import identity as node_identity  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FILTERED = os.path.join(HERE, "saved_data", "questions.filtered.json")
IDENTITY = os.path.join(HERE, "saved_data", "identity_questions.json")
CHUNKS = os.path.join(HERE, "saved_data", "chunks.pkl")
IDENTITY_REPORT = os.path.join(HERE, "saved_data", "identity_report.json")
TRAIN_OUT = os.path.join(HERE, "saved_data", "r1_train.jsonl")
EVAL_OUT = os.path.join(HERE, "saved_data", "r1_eval.jsonl")

# ONE training prompt, shared with serving: run_agent.SYSTEM_AGENTIC (persona +
# strict format + the tool catalogue). This used to be a compact persona with no
# format spec — fine for pure QA, but round 0002's SFT reused these prompts for
# rows whose completions DO use the tool format, and the gate serves the agentic
# prompt. A model trained under prompt A and evaluated under prompt B is being
# tested on something it was never taught, so the datasets carry the prompt the
# student actually receives.
from run_agent import SYSTEM_AGENTIC as SYSTEM  # noqa: E402


def window_for(chunk_id, n_chunks):
    lo = max(0, chunk_id - 1)
    hi = min(n_chunks, chunk_id + 2)
    return list(range(lo, hi))


def main():
    filtered = json.load(open(FILTERED))
    identity = json.load(open(IDENTITY))
    n_chunks = len(pickle.load(open(CHUNKS, "rb")))
    print(f"sources: {len(filtered)} windowed + {len(identity)} identity", flush=True)

    recs = []
    for q in filtered:
        recs.append({
            "prompt": [{"role": "system", "content": SYSTEM},
                       {"role": "user", "content": q["question"]}],
            "answer": q["answer"],
            "source": "windowed",
            "chunk_id": q["chunk_id"],
            "target_window": window_for(q["chunk_id"], n_chunks),
            "difficulty": q.get("difficulty"),
        })
    for q in identity:
        recs.append({
            "prompt": [{"role": "system", "content": SYSTEM},
                       {"role": "user", "content": q["question"]}],
            "answer": q["answer"],
            "source": "identity",
            "chunk_id": None,
            "target_window": [],
            "difficulty": q.get("difficulty"),
        })

    # Node identity must never reach the weights: rewrite this machine's real
    # values to a fictional cast, then refuse to write anything if a real value
    # survived. A node's facts are runtime context, not canon (bus/identity.py).
    recs, identity_report = node_identity.sanitize_records(recs)
    leftover = node_identity.audit_records(recs)
    if leftover:
        raise SystemExit(f"refusing to publish a training set: real identity "
                         f"values remain {leftover}")
    with open(IDENTITY_REPORT, "w") as fh:
        json.dump(identity_report, fh, indent=1)
        fh.write("\n")
    print(f"identity: {len(identity_report['real_values'])} node values found, "
          f"{sum(identity_report['substitutions'].values())} occurrences "
          f"rewritten to a fictional cast "
          f"({len(identity_report['substitutions'])} distinct)", flush=True)

    # frozen stratified split: 10% eval, seed 42, by source so both types
    # appear in eval
    rng = random.Random(42)
    eval_ids = set()
    for src in ("windowed", "identity"):
        idxs = [i for i, r in enumerate(recs) if r["source"] == src]
        keep = rng.sample(idxs, max(1, len(idxs) // 10))
        eval_ids.update(keep)
    train = [r for i, r in enumerate(recs) if i not in eval_ids]
    ev = [r for i, r in enumerate(recs) if i in eval_ids]

    with open(TRAIN_OUT, "w") as f:
        for r in train:
            f.write(json.dumps(r) + "\n")
    with open(EVAL_OUT, "w") as f:
        for r in ev:
            f.write(json.dumps(r) + "\n")
    print(f"train: {len(train)}  eval: {len(ev)}", flush=True)
    print(f"eval sources: windowed={sum(1 for r in ev if r['source']=='windowed')} "
          f"identity={sum(1 for r in ev if r['source']=='identity')}", flush=True)
    print(f"wrote {TRAIN_OUT} and {EVAL_OUT}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
