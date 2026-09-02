"""build_r2_warmup.py — SFT cold-start data for the round-2 agentic GRPO.

The probe verdict (2026-09-02): the untouched base R1-1.5B NEVER emits a
tool call (0/9 rollouts across temps 0.9-1.1, hard+soft system prompts) —
it narrates searching inside <think> and hallucinates answers. GRPO cannot
bootstrap a 0%-base-rate syntax (uniform no-call groups -> zero advantage),
so per the OPD two-stage recipe (cold-start SFT -> OPD/GRPO) we first SFT
the base on grounded tool trajectories.

Each warmup row is a DEMO of the correct behavior for a judge-verified
windowed question:
  think (short, why search) -> <tool>lore_search</tool> call
  -> <result> = the TRUE target window (guaranteed grounded: the reference
     answer was judged against exactly this window)
  -> final answer = the judge-verified reference

The injected result is always the true window (not live retrieval) so every
example is internally consistent; GRPO's retrieval reward teaches real
query->hit mapping afterwards. Completion text is written to follow the
tokenizer's SEEDED "<think>\n" (never opens its own think tag).

Output: saved_data/r2_warmup.jsonl  {text: <full rendered training string>}
"""

import json
import os
import pickle
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from run_agent import RESULT_OPEN, RESULT_CLOSE, SYSTEM_AGENTIC  # noqa: E402

TRAIN = os.path.join(HERE, "saved_data", "r1_train.jsonl")
CHUNKS = os.path.join(HERE, "saved_data", "chunks.pkl")
OUT = os.path.join(HERE, "saved_data", "r2_warmup.jsonl")

THINKS = [
    "I do not know this from memory — the lore corpus holds the answer. "
    "Search for it.",
    "This is a lore fact I have not memorized. Retrieve the passage.",
    "Not in my weights. Ask the corpus.",
    "The lore has this; my memory does not. Go find it.",
]


def main() -> int:
    recs = [json.loads(l) for l in open(TRAIN) if l.strip()]
    chunks = pickle.load(open(CHUNKS, "rb"))
    windowed = [r for r in recs if r["source"] == "windowed"]
    rng = random.Random(7)
    print(f"{len(windowed)} windowed train rows", flush=True)

    rows = []
    for r in windowed:
        q = r["prompt"][-1]["content"]
        window = [chunks[i] for i in r["target_window"] if 0 <= i < len(chunks)]
        passage = "\n\n".join(window)
        query = q[:100].strip()
        think = rng.choice(THINKS)
        call = ('<tool>{"tool": "lore_search", "query": "%s"}</tool>' % query)
        completion = (
            f"{think}\n</think>\n{call}\n\n{RESULT_OPEN}{passage}\n{RESULT_CLOSE}\n\n"
            f"{r['answer']}"
        )
        rows.append({"prompt": r["prompt"], "completion": completion,
                     "question": q, "chunk_id": r["chunk_id"],
                     "answer": r["answer"]})

    with open(OUT, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    print(f"wrote {OUT}: {len(rows)} rows", flush=True)

    # sample render for eyeballing
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(
        "unsloth/DeepSeek-R1-Distill-Qwen-1.5B-unsloth-bnb-4bit")
    row = rows[0]
    msgs = row["prompt"]
    text = tok.apply_chat_template(
        msgs, tokenize=False, add_generation_prompt=True) + row["completion"]
    print("\n=== SAMPLE RENDER (first 900 chars) ===\n", text[:900], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
