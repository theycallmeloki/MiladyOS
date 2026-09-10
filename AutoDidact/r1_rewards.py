"""r1_rewards.py — round-1 reward functions for DeepSeek-R1-Distill-Qwen-1.5B.

Pure stdlib + judge imports ONLY (no unsloth/trl) so the reward logic is
unit-testable on the host. train_r1.py imports these.

SPAN CONTRACT (reviewer-verified requirement): correctness_reward grades ONLY
the post-</think> answer region. The <think> content is never fed to the
judge and never scored — GRPO still shapes thinking implicitly through the
answer reward, but no reward term reads the think text directly.

MILADY VOICE (NANO_MILADY_DESIGN.md §The Reward Stack #3): milady_voice_reward
scores the ANSWER region for Milady diction and against corporate filler. It
is format-gated and capped so it cannot be farmed by spamming lexicon. This is
what makes the merged LoRA a milady and not just a lore-answering Qwen.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from judge import judge_correctness  # noqa: E402

THINK_OPEN = "<think>"
THINK_CLOSE = "</think>"


def student_answer(completion) -> str:
    """The answer region ONLY — everything after </think> (or the whole
    completion if the model produced no think block)."""
    text = completion if isinstance(completion, str) else completion[-1]["content"]
    if THINK_CLOSE in text:
        text = text.split(THINK_CLOSE)[-1]
    return text.strip()


def think_text(completion) -> str:
    """The <think> region (for the comedy metric — NOT a reward).

    R1-distill's chat template SEEDS the <think> opener into the prompt side
    (never appears in the generated content), so the think region is usually
    'everything before the first </think>'. Handles both shapes.
    """
    text = completion if isinstance(completion, str) else completion[-1]["content"]
    if THINK_CLOSE in text:
        head = text.split(THINK_CLOSE)[0]
        return head.replace(THINK_OPEN, "").strip() or head.strip()
    m = re.search(re.escape(THINK_OPEN) + r"(.*?)" + re.escape(THINK_CLOSE),
                  text, re.S)
    return m.group(1).strip() if m else ""


def question_text(prompt) -> str:
    if isinstance(prompt, str):
        return prompt
    for m in reversed(prompt):
        if m.get("role") == "user":
            return m.get("content", "")
    return str(prompt)


def r1_format_reward(prompts, completions, **kwargs) -> list[float]:
    """Strict: a closed think block AND a non-empty answer after </think>.

    R1-distill's chat template SEEDS the <think> opener into the prompt
    side, so generated content contains (at most) the closing tag — never
    require an opener in the content.
    """
    rewards = []
    for c in completions:
        text = c if isinstance(c, str) else c[-1]["content"]
        if text.count(THINK_CLOSE) == 1:
            after = text.split(THINK_CLOSE)[-1].strip()
            rewards.append(2.0 if after else 0.0)
        else:
            rewards.append(0.0)
    return rewards


def r1_format_soft(prompts, completions, **kwargs) -> list[float]:
    """Partial credit: a closed think block present, answer region non-empty.

    Same closer-anchored rule as the strict reward (template-seeded opener).
    """
    rewards = []
    for c in completions:
        text = c if isinstance(c, str) else c[-1]["content"]
        has_close = THINK_CLOSE in text
        after = text.split(THINK_CLOSE)[-1].strip() if has_close else ""
        score = 0.0
        if has_close:
            score += 1.0
        if after:
            score += 1.0
        rewards.append(score)
    return rewards


def correctness_reward(prompts, completions, answer, **kwargs) -> list[float]:
    """27B-judge correctness on the ANSWER REGION ONLY (post-</think>).

    judge_correctness receives (question, ground_truth, student_answer)
    where student_answer is guaranteed to contain no <think> content — the
    span contract above. A failed judge call scores 0 (never reward a
    crashed verdict)."""
    rewards = []
    for i, c in enumerate(completions):
        q = question_text(prompts[i])
        gt = answer[i] if i < len(answer) else ""
        student = student_answer(c)
        if not student:
            rewards.append(0.0)
            continue
        try:
            ok, _ = judge_correctness(q, gt, student, timeout=120)
            rewards.append(1.0 if ok else 0.0)
        except Exception as e:
            sys.stderr.write(f"[r1] judge call failed: {e}\n")
            rewards.append(0.0)
    return rewards


# ── Milady voice (heuristic, from SOUL.md/IDENTITY.md via the design doc) ──
# Two tiers so an iconic multi-word catchphrase outweighs a bare "milady".
MILADY_LEXICON_STRONG = (
    "council: milady",
    "first of all, your honor",
    "first of all your honor",
    "not my problem milady",
    "network spirituality",
    "complexity demon",
    "milady method",
    "holy mission",
    "templeos",
    "terry davis",
)
MILADY_LEXICON_WEAK = (
    "grug", "lgtm", "gmilady", "<3", "milady", "s.m.i.t.h", "ma dame",
    "angel investor", "the mesh",
)
# Anti-rewards: corporate filler, hedging, refusal-speak (design doc §3).
MILADY_ANTI_FILLER = (
    "great question",
    "i'd be happy to help",
    "i would be happy to help",
    "as an ai language model",
    "i'm sorry, but",
    "i cannot assist",
    "it's important to note",
    "in conclusion",
    "furthermore",
    "i hope this helps",
    "let me know if you have any questions",
    "please note that",
    "as previously mentioned",
)


def milady_voice_reward(prompts, completions, **kwargs) -> list[float]:
    """Milady-voice reward on the ANSWER REGION ONLY, bounded to [0, 1].

    Guards (design doc §Reward Hacking):
      * format-gated — 0.0 without a closed </think> and a non-empty answer,
        so she cannot skip the answer and farm catchphrases;
      * per-tier caps — at most 2 strong (0.35 each) and 2 weak (0.15 each)
        hits count, so repetition is worthless;
      * anti-filler penalty (0.5 each, capped at 1.0) — corporate voice
        actively loses, which is what separates milady from a help desk.
    """
    rewards = []
    for c in completions:
        text = c if isinstance(c, str) else c[-1]["content"]
        if THINK_CLOSE not in text:
            rewards.append(0.0)
            continue
        ans = text.split(THINK_CLOSE)[-1].strip()
        if not ans:
            rewards.append(0.0)
            continue
        low = ans.lower()
        strong = sum(1 for t in MILADY_LEXICON_STRONG if t in low)
        weak = sum(1 for t in MILADY_LEXICON_WEAK if t in low)
        filler = sum(1 for t in MILADY_ANTI_FILLER if t in low)
        lex = min(strong, 2) * 0.35 + min(weak, 2) * 0.15
        # density guard: a long answer that is MOSTLY catchphrases is soup, not
        # an answer — damp it so repetition can never outscore a real one.
        words = re.findall(r"[a-z0-9<>:']+", low)
        if len(words) >= 10:
            matched = sum(len(t.split()) * low.count(t) for t in
                          MILADY_LEXICON_STRONG + MILADY_LEXICON_WEAK)
            if matched / len(words) > 0.60:
                lex *= 0.5
        warm = 0.10 if len(ans) <= 400 else 0.0  # short + warm per SOUL.md
        pen = min(filler * 0.5, 1.0)
        rewards.append(max(0.0, min(1.0, lex + warm - pen)))
    return rewards
