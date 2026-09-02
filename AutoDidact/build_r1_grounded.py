"""build_r1_grounded.py — grounded comprehension dataset for round-1c.

The dead-run diagnosis: question-only prompts + judge-graded correctness
cannot bootstrap lore MEMORIZATION (the model never outputs a fact it
doesn't know → correctness ~0 → group-uniform rewards → no gradient).

Fix: give each windowed question its target chunk window IN-CONTEXT so the
answer is extractable — correctness becomes dense and learnable, and the
model is trained to answer FROM its corpus (the behavior the retrieval
workstream will later teach it to FIND).

Shape (judge-safe): the context is a SEPARATE user message BEFORE the
question; correctness_reward's question_text() takes the LAST user message,
so the 27B judge still receives the clean question. Identity rows
(target_window == []) stay question-only — they ground in the whole corpus
and cannot be windowed.

Usage: python build_r1_grounded.py   # writes saved_data/r1_train_grounded.jsonl
"""

import json
import os
import pickle

HERE = os.path.dirname(os.path.abspath(__file__))
TRAIN = os.path.join(HERE, "saved_data", "r1_train.jsonl")
CHUNKS = os.path.join(HERE, "saved_data", "chunks.pkl")
OUT = os.path.join(HERE, "saved_data", "r1_train_grounded.jsonl")

CONTEXT_LABEL = ("Corpus excerpt — ground your answer in this lore "
                 "excerpt:\n\n")


def main() -> int:
    chunks = pickle.load(open(CHUNKS, "rb"))
    recs = [json.loads(l) for l in open(TRAIN) if l.strip()]
    n_windowed = n_grounded = n_identity = 0
    with open(OUT, "w") as f:
        for r in recs:
            tw = r.get("target_window") or []
            if tw:
                n_windowed += 1
                excerpt = "\n\n".join(
                    chunks[i] for i in tw if 0 <= i < len(chunks))
                if excerpt:
                    # context as an EARLIER user message: the reward's
                    # question_text() reads the LAST user turn (the clean
                    # question) and never sends this blob to the judge
                    msgs = list(r["prompt"])
                    ctx_msg = {"role": "user", "content": CONTEXT_LABEL + excerpt}
                    msgs.insert(-1, ctx_msg)
                    r["prompt"] = msgs
                    r["context_chars"] = len(excerpt)
                    n_grounded += 1
                else:
                    # indices out of range — leave as-is rather than corrupt
                    n_identity += 1
            else:
                n_identity += 1
            f.write(json.dumps(r) + "\n")
    print(f"wrote {OUT}")
    print(f"windowed: {n_windowed}  grounded: {n_grounded}  "
          f"question-only (identity): {n_identity}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
