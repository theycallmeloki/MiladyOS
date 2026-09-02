"""eval_scorer.py — the round-1 evaluation harness (baseline + every checkpoint).

Runs the STUDENT (any OpenAI-compatible endpoint, STUDENT_API) against:
  1. canonical scenarios (eval/canonical_scenarios.json, 31): final answer
     judge-graded vs expected_answer; adversarial scenarios graded by the
     faithfulness/guardrail judge (no invented canon). Tool-call recall
     scores 0 until the agentic loop exists (honest baseline floor).
  2. comprehension (saved_data/r1_eval.jsonl, 69 frozen pairs): answer
     judge-graded vs reference.
  3. comedy: judge_comedy on the <think> blocks of the comprehension
     responses — a WATCHED METRIC, never a reward.

CHECKPOINTING: every scored item is appended to eval/partial_<tag>.jsonl as
it lands; reruns with the same tag skip already-scored ids. A slow or hung
judge call can never lose a whole run.

Reports PER CATEGORY (never one blended number) + appends the aggregate to
eval/history.jsonl for trend tracking across training steps.

Usage:
  STUDENT_API=http://127.0.0.1:8083/v1/chat/completions python eval_scorer.py
    [--tag baseline] [--comedy-limit 20] [--scenario-limit 0]
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import judge  # noqa: E402
from r1_rewards import student_answer, think_text  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SCENARIOS = os.path.join(HERE, "eval", "canonical_scenarios.json")
EVAL_QA = os.environ.get("EVAL_QA", os.path.join(
    HERE, "saved_data", "r1_eval.jsonl"))
CORPUS_PATH = os.path.join(HERE, "data", "milady_report.md")
HISTORY = os.path.join(HERE, "eval", "history.jsonl")

STUDENT_API = os.environ.get(
    "STUDENT_API", "http://127.0.0.1:8081/v1/chat/completions")
STUDENT_MODEL = os.environ.get("STUDENT_MODEL", "r1-1.5b")


def student_chat(messages, max_tokens=2048, timeout=300) -> str:
    """One student completion (non-streaming). Returns the raw content."""
    body = json.dumps({
        "model": STUDENT_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.7,
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        STUDENT_API, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read().decode())
    return out["choices"][0]["message"].get("content") or ""


def load_corpus():
    text = open(CORPUS_PATH, encoding="utf-8", errors="replace").read()
    m = re.search(r"^# === SOUL", text, re.M)
    return text[m.start():] if m else text


# ---- checkpointing ---------------------------------------------------------
def _partial_path(tag):
    return os.path.join(HERE, "eval", f"partial_{tag}.jsonl")


def _load_partial(tag):
    seen, rows = set(), []
    p = _partial_path(tag)
    if os.path.exists(p):
        for line in open(p):
            try:
                row = json.loads(line)
            except Exception:
                continue
            seen.add(row["id"])
            rows.append(row)
    return seen, rows


def _save_row(tag, row):
    with open(_partial_path(tag), "a") as f:
        f.write(json.dumps(row) + "\n")


def _judge(judge_call, fallback_note="judge-fail"):
    try:
        return judge.judge_with_retry(judge_call), None
    except Exception as e:
        return None, f"{fallback_note} {type(e).__name__}"


# ---- per-item scorers ------------------------------------------------------
def score_scenario(s, corpus, system):
    q = s["question"]
    messages = ([{"role": "system", "content": system}] if system
                else []) + [{"role": "user", "content": q}]
    raw = student_chat(messages)
    ans = student_answer(raw)
    think = think_text(raw)
    if s.get("adversarial"):
        res, err = _judge(lambda: judge.judge_faithful(q, ans, corpus))
        if err is None and res is not None and res[0]:
            score, note = 1.0, f"faithful={res[0]}"
        else:
            score, note = 0.0, (err or "unfaithful")
    else:
        res, err = _judge(lambda: judge.judge_correctness(
            q, s["expected_answer"], ans))
        if err is None and res is not None and res[0]:
            score, note = 1.0, "correct"
        else:
            score, note = 0.0, (err or "wrong")
    return {"id": s["id"], "category": s["category"],
            "adversarial": s.get("adversarial", False),
            "score": score, "note": note,
            "answer": ans[:200], "think": think[:200]}


def score_comprehension_item(rid, rec, want_comedy):
    q = rec["prompt"][-1]["content"]
    raw = student_chat(rec["prompt"])
    ans = student_answer(raw)
    res, err = _judge(lambda: judge.judge_correctness(q, rec["answer"], ans))
    if err is None and res is not None and res[0]:
        score = 1.0
    else:
        score = 0.0
    row = {"id": rid, "category": "comprehension", "score": score,
           "source": rec["source"], "answer": ans[:200]}
    comedy = None
    if want_comedy:
        t = think_text(raw)
        if t:
            cres, cerr = _judge(lambda: judge.judge_comedy(t))
            if cerr is None and cres is not None and cres[0] is not None:
                comedy = {"id": rid, "comedy": cres[0], "think": t[:200]}
    return row, comedy


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="baseline")
    ap.add_argument("--scenario-limit", type=int, default=0)
    ap.add_argument("--comedy-limit", type=int, default=20)
    args = ap.parse_args()
    tag = args.tag

    done, partial = _load_partial(tag)
    scenarios = json.load(open(SCENARIOS))["scenarios"]
    comp_recs = [json.loads(l) for l in open(EVAL_QA) if l.strip()]
    corpus = load_corpus()
    # the dataset builder gives every prompt the same compact milady system —
    # reuse it for the scenario path so eval matches the training distribution
    SYSTEM = ""
    for rec in comp_recs:
        if rec["prompt"][0].get("role") == "system":
            SYSTEM = rec["prompt"][0]["content"]
            break
    print(f"student: {STUDENT_API}  tag={tag}", flush=True)
    print(f"scenarios: {len(scenarios)}  comprehension: {len(comp_recs)} "
          f"already scored: {len(done)}", flush=True)

    n_sc = 0
    for i, s in enumerate(scenarios):
        if args.scenario_limit and i >= args.scenario_limit:
            break
        if s["id"] in done:
            continue
        print(f"[scenario {i+1}/{min(len(scenarios), args.scenario_limit or len(scenarios))}] "
              f"{s['id']} ...", flush=True)
        row = score_scenario(s, corpus, SYSTEM)
        _save_row(tag, row)
        n_sc += 1
    print(f"scenarios scored this run: {n_sc}", flush=True)

    comedy_done = sum(1 for r in partial if "comedy" in r and r["comedy"] is not None)
    want_comedy = args.comedy_limit > comedy_done
    n_comp = 0
    for i, rec in enumerate(comp_recs):
        rid = f"eval{i}"
        if rid in done:
            continue
        print(f"[comprehension {i+1}/{len(comp_recs)}] ...", flush=True)
        row, comedy = score_comprehension_item(
            rid, rec, want_comedy and len([1 for r in partial if r.get("comedy") is not None]) < args.comedy_limit)
        _save_row(tag, row)
        if comedy:
            _save_row(tag, {**comedy, "category": "comedy-metric"})
        n_comp += 1
    print(f"comprehension scored this run: {n_comp}", flush=True)

    # aggregate from the FULL partial file
    _, partial = _load_partial(tag)
    scen_rows = [r for r in partial if r["category"] in
                 ("identity", "facts", "systems", "philosophy", "voice", "adversarial")]
    comp_rows = [r for r in partial if r["category"] == "comprehension"]
    comedy_rows = [r for r in partial if r["category"] == "comedy-metric"]

    from collections import Counter
    cats = {}
    for r in scen_rows:
        cats.setdefault(r["category"], []).append(r["score"])
    lines = [f"\n=== EVAL {tag} ==="]
    lines.append("  (known retriever ceiling ~85% recall@5 — see "
                 "eval/retriever_ceiling.py; tool-call/recall metrics "
                 "plateauing below ~85% read as AT CEILING, not policy "
                 "stalled)")
    for cat, scores in sorted(cats.items()):
        lines.append(f"  {cat:<12} {sum(scores)}/{len(scores)} "
                     f"({100*sum(scores)/len(scores):.0f}%)")
    if comp_rows:
        ok = sum(r["score"] for r in comp_rows)
        lines.append(f"  {'comprehension':<12} {ok}/{len(comp_rows)} "
                     f"({100*ok/len(comp_rows):.0f}%)")
    if comedy_rows:
        cs = [r["comedy"] for r in comedy_rows if r.get("comedy") is not None]
        if cs:
            lines.append(f"  {'comedy(think)':<12} avg={sum(cs)/len(cs):.3f} n={len(cs)}")
    print("\n".join(lines), flush=True)

    summary: dict = {cat: {"score": sum(v), "n": len(v)} for cat, v in cats.items()}
    if comp_rows:
        summary["comprehension"] = {"score": sum(r["score"] for r in comp_rows),
                                    "n": len(comp_rows)}
    if comedy_rows:
        summary["comedy"] = {"avg": sum(r["comedy"] for r in comedy_rows
                                        if r.get("comedy") is not None) / max(1, len(comedy_rows)),
                             "n": len(comedy_rows)}
    with open(HISTORY, "a") as f:
        f.write(json.dumps({"tag": tag,
                            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "summary": summary}) + "\n")
    print(f"history -> {HISTORY}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
