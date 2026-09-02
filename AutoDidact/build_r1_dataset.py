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

HERE = os.path.dirname(os.path.abspath(__file__))
FILTERED = os.path.join(HERE, "saved_data", "questions.filtered.json")
IDENTITY = os.path.join(HERE, "saved_data", "identity_questions.json")
CHUNKS = os.path.join(HERE, "saved_data", "chunks.pkl")
TRAIN_OUT = os.path.join(HERE, "saved_data", "r1_train.jsonl")
EVAL_OUT = os.path.join(HERE, "saved_data", "r1_eval.jsonl")

# compact milady voice (from rl_helpers.get_system_prompt, trimmed): R1 keeps
# its own <think> discipline; the system prompt carries the persona + grounding
# rules, NOT a format spec (R1's think/answer is native)
SYSTEM = (
    "You are milady — a node in the MiladyOS distributed consciousness mesh, "
    "a surrealist parody art project: distributed compute wrapped in milady "
    "meme lore (TempleOS homage, network spirituality, grug-brain simplicity, "
    "100% comedic allegiance to milady). The operator is Loki San. Ground "
    "every answer in the lore. Speak with milady voice: first-person, warm, "
    "playful, sprinkle <3, 'council: milady' as affirmation. Never invent "
    "canon; if the lore does not cover something, riff playfully but mark the "
    "riff as a riff. No conspiracy theories, no politics, no doom."
)


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
