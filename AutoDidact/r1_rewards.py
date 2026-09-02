"""r1_rewards.py — round-1 reward functions for DeepSeek-R1-Distill-Qwen-1.5B.

Pure stdlib + judge imports ONLY (no unsloth/trl) so the reward logic is
unit-testable on the host. train_r1.py imports these.

SPAN CONTRACT (reviewer-verified requirement): correctness_reward grades ONLY
the post-</think> answer region. The <think> content is never fed to the
judge and never scored — GRPO still shapes thinking implicitly through the
answer reward (the comedy-as-side-effect experiment), but no reward term
reads the think text directly.
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
