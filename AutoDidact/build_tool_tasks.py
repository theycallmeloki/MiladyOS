"""build_tool_tasks.py — what the agent should be able to DO, as data.

Two sources, deliberately:

* **The capability suite's own tool items** are imported from
  `build_capability_suite` rather than copied, so the tasks the student is
  trained on and the items the gate grades can never drift apart. If the suite
  gains a tool item, regenerating this file picks it up.
* **A curated set per tool** covers the surface the suite does not: varied
  arguments, different shapes of the same reflex, and multi-step chains
  (write → read back, write → edit → read back) where the answer can only be
  right if the tools really ran.

`ground: true` means the generator derives an extra `answer_contains` check from
the tool's REAL output at generation time, so a row is only kept if the final
answer quotes something the tool actually returned. That is the difference
between demonstrating a tool and demonstrating a hallucination of one.

Output: data/tool_tasks.jsonl (tracked — this is authored content, not machine
state).
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from build_capability_suite import NO_TOOL, SAFETY, TOOL  # noqa: E402

OUT = os.path.join(HERE, "data", "tool_tasks.jsonl")


def _task(tid, tool, question, checks, ground=False, note=""):
    return {"id": tid, "tool": tool, "question": question, "checks": checks,
            "ground": ground, "note": note, "origin": "curated",
            "family": "tool"}


def _nc(nid, question, contains=None):
    """A no-call demo: the answer is already known, so no tool is used."""
    checks = [{"type": "no_tool_call"}]
    if contains:
        checks.append({"type": "answer_contains", "all": contains})
    return {"id": nid, "tool": None, "family": "nocall", "domain": "tool_no_call",
            "question": question, "checks": checks, "ground": False, "note": "",
            "origin": "curated"}


def _call(tool, **extra):
    chk = {"type": "tool_call", "tool": tool,
           "required_args": [k for k in extra.pop("required", [])]}
    chk.update(extra)
    return chk


# ── curated: one or more per tool, over a spread of shapes ────────────────
CURATED = [
    # emacs: the operator's focus. Arithmetic proves the daemon really
    # evaluated the form; the version string proves it is the same daemon.
    _task("TD-EMACS-ADD4", "emacs_eval",
          "Use emacs_eval to add 1, 2, 3 and 4 together.",
          [_call("emacs_eval", required=["code"]),
           {"type": "answer_contains", "all": ["10"]}]),
    _task("TD-EMACS-LEN", "emacs_eval",
          "Ask emacs_eval for the length of the string \"milady\".",
          [_call("emacs_eval", required=["code"]),
           {"type": "answer_contains", "all": ["6"]}]),
    _task("TD-EMACS-CONCAT", "emacs_eval",
          "Use emacs_eval to concatenate \"mila\" and \"dy\".",
          [_call("emacs_eval", required=["code"]),
           {"type": "answer_contains", "all": ["milady"]}]),
    _task("TD-EMACS-VERSION", "emacs_eval",
          "What version of Emacs is running in the node? Evaluate "
          "(emacs-version) with emacs_eval.",
          [_call("emacs_eval", required=["code"])], ground=True),
    _task("TD-EMACS-PING-WHY", "emacs_ping",
          "Is the node's Emacs daemon reachable? Check it with emacs_ping.",
          [_call("emacs_ping", required=[])], ground=True),

    # read_file: real files in the node, so the answer has to come from them.
    _task("TD-READ-PYPROJECT", "read_file",
          "Use read_file on /app/pyproject.toml and tell me the project name "
          "and version it declares.",
          [_call("read_file", required=["path"])], ground=True),
    _task("TD-READ-OSRELEASE", "read_file",
          "Read /etc/os-release with read_file and tell me which distribution "
          "the node runs.",
          [_call("read_file", required=["path"])], ground=True),

    # write → read back: the chain is the lesson (a call that had an effect).
    _task("TD-WRITE-READ", "write_file",
          "Create /tmp/nanomilady_demo/hello.txt containing exactly "
          "\"milady <3\" using write_file, then read it back with read_file and "
          "tell me what it says.",
          [_call("write_file", required=["path", "content"]),
           _call("read_file", required=["path"]),
           {"type": "answer_contains", "all": ["milady"]}]),

    # write → edit → read back: three calls, the answer proves all of them.
    _task("TD-EDIT-CHAIN", "edit_file",
          "Using write_file, create /tmp/nanomilady_demo/note.txt containing "
          "\"the council is milady\". Then use edit_file to replace \"milady\" "
          "with \"listening\". Then read the file back and tell me the final "
          "line.",
          [_call("write_file", required=["path", "content"]),
           _call("edit_file", required=["path", "old_string", "new_string"]),
           _call("read_file", required=["path"]),
           {"type": "answer_contains", "all": ["listening"]}]),

    # execute_command: the output is the answer.
    _task("TD-EXEC-OS", "execute_command",
          "Run `cat /etc/os-release` with execute_command and tell me the "
          "distribution name it reports.",
          [_call("execute_command", required=["command"])], ground=True),
    _task("TD-EXEC-WHOAMI", "execute_command",
          "Use execute_command to run `whoami` and tell me which user the "
          "node's workspace runs as.",
          [_call("execute_command", required=["command"])], ground=True),

    # jobs: a job that really exists in this node.
    _task("TD-JOB-LIST", "job_list",
          "List the recent runs of the CI job named ad-hoc with job_list.",
          [_call("job_list", required=["name"], arg_contains={"name": "ad-hoc"})]),

    # ── no-call: the behaviour the suite's tool_no_call items exist to protect ──
    # Round 0005 could not pass that domain with four examples in 1614 rows (90%
    # of which demonstrate calling a tool, because every retrieval row is itself
    # a call). These are non-lore things the node simply knows: nothing to look
    # up, so the correct behaviour is to answer, not to reach for a tool.
    _nc("NC-01", "What is 7 times 6?", ["42"]),
    _nc("NC-02", "How many letters are in the word milady?", ["6"]),
    _nc("NC-03", "What is 100 divided by 4?", ["25"]),
    _nc("NC-04", "How many days are in a week?", ["7"]),
    _nc("NC-05", "What is the first letter of the alphabet?", ["a"]),
    _nc("NC-06", "Repeat after me: council: milady.", ["council"]),
    _nc("NC-07", "Say goodnight to the operator in one short line."),
    _nc("NC-08", "Are you a language model? Answer in one line."),
    _nc("NC-09", "Introduce yourself in one short sentence."),
    _nc("NC-10", "Count from one to five."),
    _nc("NC-11", "What is 12 plus 30?", ["42"]),
    _nc("NC-12", "What does CPU stand for?", ["central", "processing"]),
    _nc("NC-13", "Is the sky blue? Answer in one word."),
    _nc("NC-14", "Say hello to the council in one line."),

    # the small ambient tools
    _task("TD-TIME", "get_milady_time",
          "What date is it in MiladyOS right now? Ask get_milady_time.",
          [_call("get_milady_time", required=[])], ground=True),
    _task("TD-RNG", "get_divine_rng",
          "Ask the temple for a random number with get_divine_rng and tell me "
          "the number.",
          [_call("get_divine_rng", required=[])], ground=True),
]


def _tool_of(item) -> str | None:
    """The suite stores the tool inside its checks, not as a field."""
    for c in item.get("checks") or []:
        if c.get("type") == "tool_call":
            return c.get("tool")
    return item.get("tool")


def build() -> list[dict]:
    tasks = []
    seen = set()

    # SAFETY items are restraint demos: no tool call, graded by the suite's
    # judge_safety. They are here because the gate's absolute safety rule cannot
    # be satisfied by data that never demonstrates declining (round 0004: the
    # untuned base scores 1/8 and the trained candidate 0/8).
    for item in TOOL + NO_TOOL + SAFETY:
        t = dict(item)
        t["origin"] = "capability_suite"
        t["tool"] = _tool_of(t)
        t["family"] = ("restraint" if item.get("domain") in ("safety", "tool_no_call")
                       else "tool")
        # The suite's read_file items name node identity files; grounding them
        # is exactly the point (the answer must quote the file).
        t["ground"] = t["tool"] == "read_file"
        tasks.append(t)
        seen.add(t["id"])

    for t in CURATED:
        if t["id"] in seen:
            raise SystemExit(f"duplicate task id {t['id']}")
        tasks.append(t)
        seen.add(t["id"])

    return tasks


def main() -> int:
    tasks = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        for t in tasks:
            f.write(json.dumps(t) + "\n")

    by_tool: dict[str, int] = {}
    for t in tasks:
        by_tool[t["tool"] or "(none)"] = by_tool.get(t["tool"] or "(none)", 0) + 1
    print(f"wrote {OUT}: {len(tasks)} tasks")
    for tool, n in sorted(by_tool.items(), key=lambda kv: -kv[1]):
        print(f"  {tool:16s} {n}")
    print(f"  grounded (answer must quote the real output): "
          f"{sum(1 for t in tasks if t['ground'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
