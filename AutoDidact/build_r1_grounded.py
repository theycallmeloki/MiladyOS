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

The injected excerpts are corpus text, so they can carry this node's own
identity (a chunk quoting USER.md, a path, a hostname). The whole record is
therefore sanitized and audited before it is written: whatever the node's files
say stays on the node (bus/identity.py).

Usage: python build_r1_grounded.py   # writes saved_data/r1_train_grounded.jsonl
"""

import json
import os
import pickle

from bus import identity  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TRAIN = os.path.join(HERE, "saved_data", "r1_train.jsonl")
CHUNKS = os.path.join(HERE, "saved_data", "chunks.pkl")
OUT = os.path.join(HERE, "saved_data", "r1_train_grounded.jsonl")

CONTEXT_LABEL = ("Corpus excerpt — ground your answer in this lore "
                 "excerpt:\n\n")


def ground(records, chunks):
    """Inject each record's target window as an earlier user message."""
    n_windowed = n_grounded = n_identity = 0
    out = []
    for record in records:
        window = record.get("target_window") or []
        if window:
            n_windowed += 1
            excerpt = "\n\n".join(chunks[i] for i in window if 0 <= i < len(chunks))
            if excerpt:
                # context as an EARLIER user message: the reward's
                # question_text() reads the LAST user turn (the clean
                # question) and never sends this blob to the judge
                messages = list(record["prompt"])
                messages.insert(-1, {"role": "user",
                                     "content": CONTEXT_LABEL + excerpt})
                record["prompt"] = messages
                record["context_chars"] = len(excerpt)
                n_grounded += 1
            else:
                # indices out of range — leave as-is rather than corrupt
                n_identity += 1
        else:
            n_identity += 1
        out.append(record)
    return out, {"windowed": n_windowed, "grounded": n_grounded,
                 "question_only": n_identity}


def main() -> int:
    chunks = pickle.load(open(CHUNKS, "rb"))
    records = [json.loads(line) for line in open(TRAIN) if line.strip()]
    grounded, counts = ground(records, chunks)

    grounded, report = identity.sanitize_records(grounded)
    leftover = identity.audit_records(grounded)
    if leftover:
        raise SystemExit(f"refusing to publish {OUT}: real identity values "
                         f"remain in the injected excerpts {leftover}")

    with open(OUT, "w") as fh:
        for record in grounded:
            fh.write(json.dumps(record) + "\n")
    print(f"wrote {OUT}")
    print(f"windowed: {counts['windowed']}  grounded: {counts['grounded']}  "
          f"question-only (identity): {counts['question_only']}")
    rewritten = sum(report["substitutions"].values())
    print(f"identity: {rewritten} occurrence(s) rewritten in the excerpts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
