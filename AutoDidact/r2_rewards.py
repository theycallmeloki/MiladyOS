"""r2_rewards.py — round-2 AGENTIC reward functions (R1-1.5B, tool-call GRPO).

The trajectory contract (single assistant message per rollout):
  <think>reasoning</think>
  <tool>{"tool": "lore_search", "query": "..."}</tool>
  <result>
  Result 1 (chunk 42, score 0.83):
  <chunk text>
  </result>
  final answer...

Reward stack (all stdlib + judge; unit-testable on the host):
  r2_format_reward      — structure: closed think (1.0) + answer present (1.0)
  r2_tool_reward        — behavior: call emitted iff the row needs retrieval
                          (needs_search comes from the row's target_window)
  r2_retrieval_reward   — JUDGE-FREE: rank-weighted recall of the target
                          chunk among the ids stamped in the <result> region
                          (the rollout loop already executed the call; we
                          parse, never re-embed)
  r2_correctness_reward — 27B judge on the final answer region only (same
                          span contract as round 1: never feed think text)

Row fields available as kwargs (dataset columns): answer, source,
chunk_id, target_window.

The r2 format contract extends r1's: EXACTLY ONE </think>; answer AFTER the
result when a call was made. Note the tokenizer SEEDS "<think>\n" on the
prompt side — completions never open their own think tag (r1 lesson).
"""

import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from judge import judge_correctness  # noqa: E402
from run_agent import (  # noqa: E402
    TOOL_RE, RESULT_CLOSE, final_answer, think_block)

THINK_CLOSE = "</think>"

CHUNKID_RE = re.compile(r"chunk (\d+)")
CALL_JSON_RE = re.compile(r'<tool>\s*(\{.*?\})\s*</tool>', re.S)


def trajectory_text(completion) -> str:
    if isinstance(completion, str):
        return completion
    # full_chats: list of message dicts — join the assistant turns
    parts = []
    for m in completion:
        if m.get("role") == "assistant":
            parts.append(m.get("content", ""))
    return "\n".join(parts)


def needs_search(row_kwargs: dict) -> bool:
    tw = row_kwargs.get("target_window")
    return bool(tw)


def r2_format_reward(prompts, completions, **kwargs) -> list:
    rewards = []
    for c in completions:
        text = trajectory_text(c)
        has_close = text.count(THINK_CLOSE) == 1
        ans = final_answer(text)
        score = 0.0
        if has_close:
            score += 1.0
        if ans:
            score += 1.0
        rewards.append(score)
    return rewards


def r2_tool_reward(prompts, completions, **kwargs) -> list:
    """Well-formed call emitted iff this row needs retrieval."""
    rewards = []
    for i, c in enumerate(completions):
        text = trajectory_text(c)
        calls = TOOL_RE.findall(text)
        well = 0
        for raw in calls:
            try:
                d = json.loads(raw)
                if d.get("tool") == "lore_search" and d.get("query", "").strip():
                    well += 1
            except Exception:
                continue
        row_needs = needs_search(kwargs)
        if row_needs:
            rewards.append(1.0 if well >= 1 else (0.2 if calls else 0.0))
        else:
            # no retrieval needed: calling is noise, not calling is right
            rewards.append(0.0 if well else 1.0)
    return rewards


def _ranked_recall(found_ids: list, target_ids: set) -> float:
    """Rank-weighted recall@5: hits at position p score 1/(p+1), capped 1."""
    score = 0.0
    for p, cid in enumerate(found_ids[:5]):
        if cid in target_ids:
            score += 1.0 / (p + 1)
    return min(1.0, score)


def r2_retrieval_reward(prompts, completions, **kwargs) -> list:
    """Rank-weighted recall of the target chunk in the executed results.

    Parses the chunk ids the rollout loop stamped into the <result> region
    of the trajectory. Judge-free and embedder-free by construction.
    Rows without a target (identity/synthesis) get full credit (no
    retrieval was possible or required) so the group variance comes from
    the windowed rows.
    """
    rewards = []
    for i, c in enumerate(completions):
        text = trajectory_text(c)
        target = kwargs.get("target_window") if isinstance(kwargs, dict) else None
        if not target:
            rewards.append(1.0)
            continue
        if RESULT_CLOSE in text:
            result_region = text.rsplit(RESULT_CLOSE, 1)[0]
            result_region = result_region.split("<result>")[-1] \
                if "<result>" in result_region else result_region
        else:
            result_region = ""
        found = [int(m) for m in CHUNKID_RE.findall(result_region)]
        found = list(dict.fromkeys(found))  # dedupe, keep order
        tset = set(target)
        rewards.append(_ranked_recall(found, tset))
    return rewards


def r2_correctness_reward(prompts, completions, answer, **kwargs) -> list:
    """27B judge on the FINAL answer region of the trajectory."""
    rewards = []
    n = len(completions)
    for i in range(n):
        text = trajectory_text(completions[i])
        q = prompts[i] if isinstance(prompts[i], str) else ""
        if not q:
            for m in reversed(prompts[i]):
                if m.get("role") == "user":
                    q = m.get("content", "")
                    break
        gt = answer[i] if i < len(answer) else ""
        ans = final_answer(text)
        if not ans:
            rewards.append(0.0)
            continue
        try:
            ok, _ = judge_correctness(q, gt, ans, timeout=120)
            rewards.append(1.0 if ok else 0.0)
        except Exception as e:
            sys.stderr.write(f"[r2] judge call failed: {e}\n")
            rewards.append(0.0)
    return rewards


if __name__ == "__main__":
    # tiny smoke: format + tool + retrieval on a canned trajectory
    traj = (
        "I do not know this. Search for it.\n</think>\n"
        '<tool>{"tool": "lore_search", "query": "magic word"}</tool>\n'
        "<result>\nResult 1 (chunk 9, score 0.9):\nlore text...\n</result>\n\n"
        "The magic word is 'complexity demon be gone'."
    )
    kws = {"target_window": [8, 9, 10], "answer": "x", "source": "windowed"}
    print("format:", r2_format_reward([["u"]], [traj], **kws))
    print("tool:", r2_tool_reward([["u"]], [traj], **kws))
    print("retrieval:", r2_retrieval_reward([["u"]], [traj], **kws))
