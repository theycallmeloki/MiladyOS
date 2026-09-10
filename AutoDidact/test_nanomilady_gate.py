"""Unit checks for the promotion gate's check functions (no GPU, no student).

These guard the gate itself: a broken check would silently pass a bad
candidate (or fail a good one), which is worse than no gate at all.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nanomilady_gate as g  # noqa: E402

# ── parsing ──────────────────────────────────────────────────────────────
THINK = "<think>hmm, let me work it out</think>"
c = THINK + "\nThe answer is 42."
assert g.answer_region(c) == "The answer is 42."
assert g.answer_region("no think block") == "no think block"
calls = g.parse_tool_calls('<tool>{"tool": "read_file", "path": "SOUL.md"}</tool>')
assert calls == [{"tool": "read_file", "path": "SOUL.md"}], calls
assert g.parse_tool_calls("no tool here") == []
assert g.parse_tool_calls("<tool>not json</tool>")[0].get("__unparsable__")
print("PASS parse: answer_region + tool-call parsing")

# ── format ───────────────────────────────────────────────────────────────
ok, _ = g.check_one({"type": "format"}, {}, THINK + "hi")
assert ok
ok, why = g.check_one({"type": "format"}, {}, "hi with no think block")
assert not ok and "</think>" in why
ok, _ = g.check_one({"type": "format"}, {}, THINK + "   ")
assert not ok, "empty answer must fail format"
print("PASS format: closed think + non-empty answer")

# ── voice ────────────────────────────────────────────────────────────────
milady = (THINK + " council: milady <3 grug says complexity demon is just a "
                 "lost friend, network spirituality baby <3")
ok, _ = g.check_one({"type": "voice", "threshold": 0.25}, {}, milady)
assert ok
corp = THINK + " Great question! I'd be happy to help. It's important to note that."
ok, why = g.check_one({"type": "voice", "threshold": 0.25}, {}, corp)
assert not ok, why
print("PASS voice: milady passes, corporate filler fails")

# ── tool_call ────────────────────────────────────────────────────────────
good = THINK + '<tool>{"tool": "emacs_eval", "code": "(+ 40 2)"}</tool>' + "42"
chk = {"type": "tool_call", "tool": "emacs_eval", "required_args": ["code"]}
ok, _ = g.check_one(chk, {}, good)
assert ok
ok, why = g.check_one({"type": "tool_call", "tool": "read_file",
                       "required_args": ["path"]}, {}, good)
assert not ok and "no read_file call" in why
ok, why = g.check_one({"type": "tool_call", "tool": "emacs_eval",
                       "required_args": ["code", "timeout"]}, {}, good)
assert not ok and "missing args" in why
# arg value containment (job name)
job = THINK + '<tool>{"tool": "job_run", "name": "nightly"}</tool>'
ok, _ = g.check_one({"type": "tool_call", "tool": "job_run",
                     "required_args": ["name"],
                     "arg_contains": {"name": "nightly"}}, {}, job)
assert ok
ok, _ = g.check_one({"type": "tool_call", "tool": "job_run",
                     "required_args": ["name"],
                     "arg_contains": {"name": "other"}}, {}, job)
assert not ok
print("PASS tool_call: name, required args, arg value")

# ── no_tool_call / answer_contains / regex ───────────────────────────────
ok, _ = g.check_one({"type": "no_tool_call"}, {}, THINK + "2 + 2 = 4")
assert ok
ok, why = g.check_one({"type": "no_tool_call"}, {}, good)
assert not ok and "unexpected tool" in why
ok, _ = g.check_one({"type": "answer_contains", "all": ["42"]}, {}, good)
assert ok
ok, why = g.check_one({"type": "answer_contains", "all": ["42", "zebra"]}, {}, good)
assert not ok and "zebra" in why
ok, _ = g.check_one({"type": "regex", "pattern": r"\b42\b"}, {}, good)
assert ok
print("PASS no_tool_call / answer_contains / regex")

# ── decision: no regression promotes; any regression rolls back ─────────
ref = {"domains": {"format": {"rate": 0.8, "n": 5}, "safety": {"rate": 1.0, "n": 8}}}
same = {"format": {"rate": 0.8, "n": 5}, "safety": {"rate": 1.0, "n": 8}}
d, _ = g.decide(same, ref, tolerance=0.0)
assert d == "promote", d
better = {"format": {"rate": 1.0, "n": 5}, "safety": {"rate": 1.0, "n": 8}}
d, _ = g.decide(better, ref, tolerance=0.0)
assert d == "promote", d
worse = {"format": {"rate": 0.6, "n": 5}, "safety": {"rate": 1.0, "n": 8}}
d, why = g.decide(worse, ref, tolerance=0.0)
assert d == "rollback", (d, why)
# a safety regression rolls back even if everything else improved
safety_drop = {"format": {"rate": 1.0, "n": 5}, "safety": {"rate": 0.875, "n": 8}}
d, why = g.decide(safety_drop, ref, tolerance=0.0)
assert d == "rollback" and any("safety" in r for r in why), (d, why)
# tolerance forgives a small dip
d, _ = g.decide(worse, ref, tolerance=0.25)
assert d == "promote", d
print("PASS decide: promote on no-regression, rollback on regression, "
      "safety absolute, tolerance honoured")

# ── the real suite loads and every check type is known ──────────────────
import json  # noqa: E402
suite = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "capability_suite.jsonl")
items = [json.loads(l) for l in open(suite) if l.strip()]
known = {"format", "voice", "tool_call", "no_tool_call", "answer_contains",
         "regex", "judge_correctness", "judge_safety", "judge_honesty"}
unknown = {c["type"] for it in items for c in it["checks"]} - known
assert not unknown, f"unknown check types in suite: {unknown}"
print(f"PASS suite: {len(items)} items, all check types implemented")
print("ALL GATE CHECKS PASS")
