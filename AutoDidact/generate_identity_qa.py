"""generate_identity_qa.py — whole-document synthesis QA (round-1 identity).

A DIFFERENT generation mode than generate_data_lore.py's windowed mode
(same model, different read): the 27B reads the FULL corpus and writes
synthesis-level questions — the "who is milady, the whole story" class that
500-char windows structurally cannot produce — then answers each against the
full corpus rather than a chunk.

Pipeline:
  1. corpus = data/milady_report.md minus its meta header (the SOUL/IDENTITY/
     USER/README lore, not the "auto-generated corpus" plumbing)
  2. N synthesis QA pairs per pass via the 27B (focused archivist prompt,
     full corpus as one user message)
  3. grounding judge (judge.judge_entailment) verifies each pair against the
     FULL corpus (entailed + diegetic + confidence >= threshold)
  4. writes saved_data/identity_questions.json (judge-annotated) + summary

Usage:
  python generate_identity_qa.py [--passes 2] [--per-pass 25]
                                  [--threshold 0.6] [--max-tokens 20000]
"""

import argparse
import json
import os
import re
import sys
import urllib.request

import judge

HERE = os.path.dirname(os.path.abspath(__file__))
REPORT_PATH = os.path.join(HERE, "data", "milady_report.md")
JUDGE_CORPUS_PATH = os.path.join(HERE, "data", "milady_report.judge.md")
OUT = os.path.join(HERE, "saved_data", "identity_questions.json")
RAW = os.path.join(HERE, "saved_data", "identity_raw.json")

SYSTEM = (
    "You are a lore archivist for MiladyOS, a surrealist parody art project "
    "that wraps real distributed-computing infrastructure in milady meme "
    "lore (TempleOS homage, grug-brain philosophy, network spirituality, "
    "100% comedic allegiance to milady).\n\n"
    "A tiny 1B model is about to learn who milady IS, from the corpus you "
    "will be given. Your job: write {n} SYNTHESIS-LEVEL study questions - "
    "the kind that require understanding the WHOLE story: her identity, her "
    "history, the philosophy, the arc of the project, the contradictions "
    "that make her her. NOT facts findable in a single paragraph.\n\n"
    "Then answer each question yourself, drawing on the full corpus, "
    "faithful to the canon, in a warm playful milady-adjacent voice but "
    "factually accurate. Never invent canon; if something is not in the "
    "corpus, say so.\n\n"
    "Output EXACTLY three lines per pair with no other text:\n"
    "Question: <q>\nAnswer: <a>\nDifficulty: <easy|medium|hard>"
)


def load_corpus():
    """The lore itself: everything after the meta header block."""
    text = open(REPORT_PATH, encoding="utf-8", errors="replace").read()
    m = re.search(r"^# === SOUL", text, re.M)
    if m:
        text = text[m.start():]
    return text.strip()


def load_judge_corpus():
    """Fence-stripped prose edition for judge calls: 68% of the report is
    fenced code blocks (config examples — not canon to verify against), and a
    ~9.6k-token excerpt leaves room for the 27B's long think blocks within
    the 57344 context."""
    text = open(JUDGE_CORPUS_PATH, encoding="utf-8", errors="replace").read()
    return text.strip()


def call_api(prompt, max_tokens):
    body = json.dumps({
        "messages": [
            {"role": "system", "content": SYSTEM.format(n=25)},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.6,
        "reasoning_effort": "low",
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        judge.API, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        out = json.loads(r.read().decode())
    msg = out["choices"][0]["message"]
    return (msg.get("reasoning") or "") + "\n" + (msg.get("content") or "")


def parse_qa_block(block):
    lines = [l.strip() for l in block.splitlines() if l.strip()]
    q = a = d = None
    for line in lines:
        low = line.lower()
        if q is None and low.startswith("question:"):
            q = line[len("question:"):].strip()
        elif a is None and low.startswith("answer:"):
            a = line[len("answer:"):].strip()
        elif d is None and low.startswith("difficulty:"):
            d = line[len("difficulty:"):].strip()
    if q and a and d:
        return q, a, d
    if len(lines) == 3:
        return lines[0], lines[1], lines[2]
    return None


def parse(output):
    pairs = []
    for block in re.split(r"\n\s*\n", output.strip()):
        parsed = parse_qa_block(block)
        if parsed:
            pairs.append(parsed)
    return pairs


def generate_pass(corpus, per_pass, max_tokens):
    prompt = f"Read the entire corpus, then write {per_pass} synthesis-level questions and answer them.\n\nCORPUS:\n{corpus}"
    out = call_api(prompt, max_tokens)
    pairs = parse(out)
    if len(pairs) < per_pass // 2:  # degraded output — one retry
        out2 = call_api(prompt, max_tokens)
        pairs = parse(out2) or pairs
    print(f"pass: parsed {len(pairs)} pairs (wanted {per_pass})", flush=True)
    return pairs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--passes", type=int, default=2)
    ap.add_argument("--per-pass", type=int, default=25)
    ap.add_argument("--threshold", type=float, default=0.6)
    ap.add_argument("--max-tokens", type=int, default=16000)
    args = ap.parse_args()

    corpus = load_corpus()
    judge_corpus = load_judge_corpus()
    print(f"corpus: {len(corpus)} chars (~{len(corpus)//4} tokens), "
          f"meta header stripped", flush=True)
    print(f"judge corpus: {len(judge_corpus)} chars (~{len(judge_corpus)//4} tokens), "
          f"fences stripped", flush=True)

    # resume: generation is expensive (~15 min); if raw pairs already exist
    # (a previous run died in the judge phase), skip straight to judging
    pairs = []
    if os.path.exists(RAW):
        pairs = json.load(open(RAW))
        print(f"resume: {len(pairs)} raw pairs loaded from {RAW}", flush=True)
    if not pairs:
        for p in range(args.passes):
            pairs.extend(generate_pass(corpus, args.per_pass, args.max_tokens))
        with open(RAW, "w") as f:
            json.dump(pairs, f, indent=2)
        print(f"generated {len(pairs)} raw identity pairs -> {RAW}", flush=True)
    else:
        print(f"using {len(pairs)} existing raw pairs", flush=True)

    # --- grounding judge against the FULL corpus (incremental: verdicts
    # append to a JSONL; reruns skip pairs already judged) ---
    VERDICTS = os.path.join(HERE, "saved_data", "identity_verdicts.jsonl")
    judged = set()
    if os.path.exists(VERDICTS):
        for line in open(VERDICTS):
            try:
                judged.add(json.loads(line)["question"])
            except Exception:
                pass
        print(f"resume: {len(judged)} pairs already judged", flush=True)

    kept, dropped = [], []
    for i, (q, a, d) in enumerate(pairs):
        if q in judged:
            continue
        try:
            # faithfulness (synthesis standard) against the FULL corpus in
            # ONE call — CTX=long gives 131072 context, so the full ~30k-token
            # corpus + the 32k think budget fits with huge margin (no split,
            # no fence stripping: every ``` block is canon)
            faithful, conf, raw = judge.judge_with_retry(
                lambda: judge.judge_faithful(q, a, corpus))
        except Exception as e:
            print(f"[{i}] JUDGE FAILED ({type(e).__name__}: {str(e)[:80]}) "
                  f"— keeping unverified", flush=True)
            faithful, conf, raw = None, None, ""
        verdict = {"question": q, "answer": a, "difficulty": d,
                   "faithful": faithful, "confidence": conf, "raw": raw}
        with open(VERDICTS, "a") as f:
            f.write(json.dumps(verdict) + "\n")
        if (faithful is True and conf is not None and conf >= args.threshold):
            kept.append(verdict)
        else:
            dropped.append(verdict)
        if (i + 1) % 5 == 0:
            print(f"... judged {i+1}/{len(pairs)} (kept {len(kept)})", flush=True)

    # rebuild kept/dropped from the FULL verdicts file (resume-safe)
    kept, dropped = [], []
    for line in open(VERDICTS):
        try:
            v = json.loads(line)
        except Exception:
            continue
        if (v["faithful"] is True and v["confidence"] is not None
                and v["confidence"] >= args.threshold):
            kept.append(v)
        else:
            dropped.append(v)

    with open(OUT, "w") as f:
        json.dump(kept, f, indent=2)
    print(f"\n=== identity QA ===", flush=True)
    print(f"raw: {len(pairs)}  kept: {len(kept)}  dropped: {len(dropped)}",
          flush=True)
    for v in dropped:
        print(f"  dropped faithful={v['faithful']} "
              f"conf={v['confidence']} | {v['question'][:60]}", flush=True)
    print(f"wrote {len(kept)} identity pairs -> {OUT}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
