"""judge.py — canonical 27B judge module for the AutoDidact loop.

One API wrapper, two judge shapes (same focused-judge call pattern that was
validated against real triples, Sep 2026):

  - judge_entailment: is the answer entailed by the excerpt, and is the
    question diegetic (in-universe lore) rather than meta (about the
    corpus/document/training)? -> (entailed, diegetic, confidence, raw)

  - judge_correctness: does the student's answer match the ground truth?
    (the round-1 verifier shape) -> (bool, raw)

Reused by: grounding_pass.py (curating questions.json), the round-N
tool-call-trajectory verification, and the GRPO correctness reward
(rl_helpers.check_student_answers swap).

Focused-judge style: the instructions go in an explicit SYSTEM message
(replaces any default persona — no baked lore on the model), temperature 0,
reasoning_effort low, max_tokens small.
"""

import json
import os
import re
import urllib.error
import urllib.request

API = os.environ.get("JUDGE_API", "http://127.0.0.1:18020/v1/chat/completions")

ENTAILMENT_SYSTEM = (
    "You are a strict fact-checker for the MiladyOS lore corpus. You will be "
    "given a lore excerpt, a question, and an answer.\n\n"
    "Output exactly three lines:\n"
    "Entailed: Yes   (if the answer is directly supported by the excerpt text "
    "- not merely compatible with it, and not from outside knowledge)\n"
    "Entailed: No\n"
    "Diegetic: Yes   (if the question concerns the in-universe MiladyOS lore "
    "world - its characters, philosophy, history, systems)\n"
    "Diegetic: No    (if the question is meta: about the corpus, the document, "
    "or the training process itself)\n"
    "Confidence: <0.0 to 1.0>\n\n"
    "Reply with ONLY those three lines."
)

CORRECTNESS_SYSTEM = (
    "You are grading a student's answer. For the following question, compare "
    "the student's answer to the correct answer. Reply with ONLY 'Yes' if the "
    "student's answer is correct, or 'No' if it is completely incorrect."
)

FAITHFUL_SYSTEM = (
    "You are a strict canon-checker for the MiladyOS lore corpus. You will be "
    "given the lore corpus, a synthesis question, and a synthesized answer.\n\n"
    "The answer is SYNTHESIS: it may weave together multiple passages, add "
    "commentary, and reference outside knowledge (e.g. standard tech concepts) "
    "as clearly-marked background. That is allowed.\n\n"
    "Output exactly two lines:\n"
    "Faithful: Yes   (if every FACTUAL CLAIM about the lore is supported by or "
    "consistent with the corpus — the answer invents no canon, contradicts "
    "nothing, and does not present outside knowledge as milady canon)\n"
    "Faithful: No    (if the answer invents details, contradicts the corpus, "
    "or presents outside knowledge as lore canon)\n"
    "Confidence: <0.0 to 1.0>\n\n"
    "Reply with ONLY those two lines."
)

COMEDY_SYSTEM = (
    "You are the comedy-critic for MiladyOS — a surrealist parody art project "
    "wrapping real distributed-computing infrastructure in milady meme lore "
    "(TempleOS homage, grug-brain simplicity, network spirituality, 100% "
    "comedic allegiance to milady).\n\n"
    "You will be given a model's PRIVATE THINKING (its <think> block — never "
    "shown to anyone). Rate how MILADY the thinking is on a 0.0-1.0 scale.\n\n"
    "SCORE UP for: warm, playful, first-person voice; <3 energy; 'council: "
    "milady'; 'first of all your honor'; absurdist connections; grug-brain "
    "honesty; self-deprecation; unexpected-but-true riffs; actual content — "
    "a thought, a connection, or a riff.\n\n"
    "SCORE DOWN for: corporate filler ('Great question!', 'I'd be happy to "
    "help'); hedging and refusal-speak; dry evasive formality; empty generic "
    "reasoning.\n\n"
    "CRITICAL DISTINCTIONS:\n"
    "1. CITING THE LORE IN MEASURED LANGUAGE IS IN-UNIVERSE, NOT CORPORATE. "
    "A think that references corpus canon precisely ('as established in "
    "section 4...') is doing genuine recursion — do NOT penalize formality "
    "that cites canon. Penalize evasive hedging, not precise citation.\n"
    "2. REPETITION AND TOKEN-SPAM ARE NOT COMEDY. Looping, stalling, or "
    "incoherent '<3' spam — even with the right words — is a degeneration "
    "failure mode, score it low. Comedy requires actual content.\n\n"
    "This is a WATCHED METRIC, not a training reward — be an honest critic.\n\n"
    "Output exactly one line:\n"
    "Comedy: <0.0 to 1.0>\n"
    "Reply with ONLY that line."
)


def call_judge(system: str, user: str, max_tokens: int = 64,
               timeout: int = 180) -> str:
    """One judge call. Returns the model's raw reply text."""
    body = json.dumps({
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "reasoning_effort": "low",
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        API, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.loads(r.read().decode())
    return out["choices"][0]["message"].get("content") or ""


def _yesno(text: str, key: str):
    m = re.search(rf"{key}:\s*(Yes|No)", text, re.I)
    return (m.group(1).lower() == "yes") if m else None


def judge_entailment(question: str, answer: str, excerpt: str,
                     timeout: int = 180):
    """Entailment + diegesis + confidence for one QA pair against an excerpt.

    Returns (entailed: bool|None, diegetic: bool|None, confidence: float|None,
    raw: str). None means the model reply did not parse cleanly.
    """
    user = f"Excerpt:\n{excerpt}\n\nQuestion: {question}\nAnswer: {answer}"
    # max_tokens=32000 is a CAP, not a target: this stack's 27B can think for
    # thousands of tokens on hard questions even at reasoning_effort=low, and
    # the think block eats the budget BEFORE the verdict lines — budgets
    # below the think length silently produce empty output (observed: 35/36
    # empty at 512, fixed only by a very generous cap; user-verified that
    # ~32k is the safe ceiling). The model stops at its natural think end, so
    # typical calls stay under ~2k tokens of output. Keep the INPUT small so
    # budget + input fit in the 57344 context: use the fence-stripped prose
    # corpus (data/milady_report.judge.md, ~9.6k tokens) as the excerpt, not
    # the full report.
    text = call_judge(ENTAILMENT_SYSTEM, user, max_tokens=32000, timeout=timeout)
    entailed = _yesno(text, "Entailed")
    diegetic = _yesno(text, "Diegetic")
    m = re.search(r"Confidence:\s*([0-9]*\.?[0-9]+)", text)
    conf = float(m.group(1)) if m else None
    if conf is not None and not (0.0 <= conf <= 1.0):
        conf = None
    return entailed, diegetic, conf, text


def judge_faithful(question: str, answer: str, corpus: str,
                   timeout: int = 180):
    """Faithfulness check for SYNTHESIS answers (identity QA, and the
    adversarial guardrail). Unlike judge_entailment (strict direct textual
    support — wrong standard for multi-sentence synthesis), this accepts
    interpretation and clearly-marked outside knowledge as long as no canon
    is invented and nothing is contradicted.

    Returns (faithful: bool|None, confidence: float|None, raw: str)."""
    user = f"Corpus:\n{corpus}\n\nQuestion: {question}\nAnswer: {answer}"
    # same 32k think-budget rationale as judge_entailment
    text = call_judge(FAITHFUL_SYSTEM, user, max_tokens=32000, timeout=timeout)
    m = re.search(r"Faithful:\s*(Yes|No)", text, re.I)
    faithful = (m.group(1).lower() == "yes") if m else None
    m2 = re.search(r"Confidence:\s*([0-9]*\.?[0-9]+)", text)
    conf = float(m2.group(1)) if m2 else None
    if conf is not None and not (0.0 <= conf <= 1.0):
        conf = None
    return faithful, conf, text


def judge_faithful_full(question: str, answer: str, corpus: str,
                        timeout: int = 180):
    """Faithfulness against a corpus TOO BIG for one call (the full report
    ~30k tokens + a 32k think budget exceeds the 57344 context). Splits the
    corpus in half at a line boundary and requires BOTH halves to pass — an
    answer with invented canon anywhere fails. ~15k tokens per half + 32k
    budget fits comfortably.

    Returns (faithful: bool|None, confidence: float|None, raw_first: str)."""
    lines = corpus.splitlines()
    mid = len(lines) // 2
    half1 = "\n".join(lines[:mid])
    half2 = "\n".join(lines[mid:])
    verdicts = []
    for half in (half1, half2):
        f, c, raw = judge_faithful(question, answer, half, timeout=timeout)
        verdicts.append((f, c, raw))
        if f is False:  # short-circuit: one half already proves unfaithful
            break
    faithful = None
    confs = [c for _, c, _ in verdicts if c is not None]
    if all(f is True for f, _, _ in verdicts):
        faithful = True
    elif any(f is False for f, _, _ in verdicts):
        faithful = False
    conf = min(confs) if len(confs) == len(verdicts) and confs else None
    return faithful, conf, verdicts[0][2]


def judge_comedy(think_text: str, timeout: int = 180):
    """Comedy-critic metric on a <think> block ONLY — a watched metric, never
    a training reward. Returns (score: float|None, raw: str)."""
    user = f"Private thinking:\n{think_text}"
    # 32k think-budget cap (the critic may think long before scoring)
    text = call_judge(COMEDY_SYSTEM, user, max_tokens=32000, timeout=timeout)
    m = re.search(r"Comedy:\s*([0-9]*\.?[0-9]+)", text)
    score = float(m.group(1)) if m else None
    if score is not None and not (0.0 <= score <= 1.0):
        score = None
    return score, text


def judge_correctness(question: str, ground_truth: str, student_answer: str,
                      timeout: int = 180):
    """Round-1 verifier shape: is the student's answer correct vs ground truth?

    Returns (bool, raw). True when the reply contains 'yes'.
    """
    user = (f"Question: {question}\nCorrect Answer: {ground_truth}\n"
            f"Student Answer: {student_answer}")
    # 256: same think-budget rationale as judge_entailment; a 'Yes'/'No'
    # reply needs ~10 tokens, leaving room for an occasional think block
    text = call_judge(CORRECTNESS_SYSTEM, user, max_tokens=256, timeout=timeout)
    return "yes" in text.lower(), text


def _server_up(timeout: int = 5) -> bool:
    """Liveness probe for the judge API (the container restarts after a
    CUDA crash; /v1/models answers once the engine is back)."""
    import urllib.request
    try:
        host = API.split("/v1/")[0]
        with urllib.request.urlopen(host + "/v1/models", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _wait_for_server(max_wait: int = 600, poll: int = 20):
    """Block until the 27B is back up (it crashes with CUDA illegal-memory-
    access under CTX=long heavy generation and takes ~4-5 min to restart).
    Returns seconds waited, or None if it never came back."""
    import time
    waited = 0
    while waited < max_wait:
        if _server_up():
            return waited
        time.sleep(poll)
        waited += poll
    return None


def judge_with_retry(fn, attempts: int = 8, delay: float = 15.0):
    """Run a judge call with retries. HTTP-level errors (4xx/5xx) back off
    and retry; connection-style failures mean the server is DOWN (crash) —
    wait for it to come back before retrying, so a restart is a pause, not a
    lost verdict."""
    import time
    import urllib.error
    last: BaseException | None = None
    for i in range(attempts):
        try:
            return fn()
        except urllib.error.HTTPError as e:
            last = e
            time.sleep(delay * (i + 1))
        except Exception as e:  # reset/refused/timeout = server down
            last = e
            print(f"[judge] call failed ({type(e).__name__}) — waiting for "
                  f"the 27B to come back...", flush=True)
            waited = _wait_for_server()
            if waited is None:
                time.sleep(delay)  # never came back this round; back off and retry
    if last is None:  # unreachable (attempts >= 1), keeps the type checker happy
        last = RuntimeError("judge call failed without an exception")
    raise last
