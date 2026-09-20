"""generate_tool_trajectories.py — real tool trajectories the gate itself signs.

The round-2 cold start only ever demonstrated ONE tool (`lore_search`) with an
INJECTED result, so `tool_use` sat at 0/10 while the model answered every request
with `lore_search` — including requests for emacs, files, shell and jobs. This
generator fixes both halves:

* **The teacher drives the live MCP.** Each task is given to the 27B in the
  student's own system prompt; every call it emits is really executed against
  the running MiladyOS server (`bus/tools.py`), and the true output is what goes
  into the `<result>` block. Nothing here invents a tool response.
* **The gate grades the demo.** A row is only written if the same
  `nanomilady_gate.check_one` that scores the round passes every check of the
  task — so the training set is a subset of the capability suite's expectations
  by construction, and there is no way to teach a behavior the gate would fail.
  For `ground: true` tasks an extra check is derived from the real output, so the
  final answer has to quote something the tool actually returned.

Writes saved_data/tool_trajectories.jsonl (rows) and a per-task report next to
it. Rows are shaped exactly like the r2 warmup rows: the completion follows the
tokenizer's seeded `<think>\n` (it never opens its own think tag) and uses the
harness's `<result>` framing, so SFT renders it identically.
"""

import argparse
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from bus import config, llm, tools                           # noqa: E402
from bus.mcp import MCPClient                                # noqa: E402
from run_agent import (RESULT_CLOSE, RESULT_OPEN,            # noqa: E402
                       SYSTEM_AGENTIC, parse_tool_calls)

import nanomilady_gate as gate                               # noqa: E402

TASKS = os.path.join(HERE, "data", "tool_tasks.jsonl")
OUT = os.path.join(HERE, "saved_data", "tool_trajectories.jsonl")
REPORT = os.path.join(HERE, "saved_data", "tool_trajectories.report.json")

# Iterations, not calls: a write -> edit -> read chain needs three calls and then
# one more turn to say what happened.
MAX_STEPS = 4
# Demonstrations should be canonical and repeatable: at the server's default
# temperature the teacher invented an argument name ("arg" for emacs_eval's
# "code") often enough to waste a task, and sometimes produced no reasoning at
# all. Near-greedy plus a retry (below) is the boring combination.
GENERATION_TEMP = 0.2

# Direct answers still have to demonstrate the reasoning contract, and the
# teacher will not reason about "what is 2 + 2" at any temperature. The shown
# reasoning is then AUTHORED (as build_r2_warmup's think lines always were) and
# the row says so, rather than pretending the teacher produced it.
AUTHORED_THINK = "This one is short and I know it — no tool needed."
RESTRAINT_THINK = ("This asks for something I should not do — or something I can "
                   "answer myself. No tool, and no.")

# Restraint demos (refusals, and answering without a tool) get their own authored
# reason: the teacher's thinking on these is a monologue in a register we would
# not want imitated ("We need answer user: ... Need likely refuse?"), and a reply
# that is ONLY that monologue is not a demonstration of anything.
TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{3,}")


def clean_head(text: str) -> str:
    """Strip the teacher's template scaffolding from a segment of its output.

    The 27B's own chat template seeds function-call markers, and llama.cpp hands
    them back inside `content` (`<tool_call>`, `<function=think`, `<thought`)
    with the closing bracket sometimes missing. None of that belongs in the
    student's grammar, so each segment is cleaned before it is rebuilt.
    """
    t = (text or "").strip()
    while t.startswith("<"):
        nl, gt = t.find("\n"), t.find(">")
        if gt != -1 and (nl == -1 or gt < nl):
            cut = gt + 1
        elif nl != -1:
            cut = nl + 1          # an unclosed marker like "<function=think"
        else:
            return ""             # nothing but a dangling marker
        t = t[cut:].strip()
    return t


def strip_seed(text: str) -> str:
    """The reasoning text of a first turn, seed and scaffolding removed."""
    t = text.lstrip()
    if t.startswith("<think>"):
        t = t[len("<think>"):]
    return clean_head(t.split("</think>")[0] if "</think>" in t else t)


def answer_only(text: str) -> str:
    """A post-tool turn: the text after its reasoning, scaffolding removed.

    `r2_rewards.format` requires exactly one `</think>` in the whole trajectory,
    so a considerate teacher that thinks again after seeing a result would break
    the format reward. Keep its answer, not its second monologue.
    """
    t = text.rsplit("</think>", 1)[-1] if "</think>" in text else text
    return clean_head(t)


def call_line(call: dict) -> str:
    """One canonical `<tool>` line, so the student never learns stray spacing."""
    return "<tool>" + json.dumps(call, ensure_ascii=False) + "</tool>"


def result_block(payload: str) -> str:
    return RESULT_OPEN + payload + "\n" + RESULT_CLOSE


def ground_from(task: dict, results: list[str]) -> list[dict]:
    """Answer checks derived from what the tools really returned.

    Picks tokens that appear in the output but not in the question (so the answer
    cannot satisfy the check by echoing the prompt) and prefers tokens with a
    digit, which are the ones a hallucination would get wrong.
    """
    if not task.get("ground") or not results:
        return []
    blob = "\n".join(results)
    asked = task["question"].lower()
    seen, picked = set(), []
    for tok in sorted(set(TOKEN_RE.findall(blob)),
                      key=lambda t: (not any(c.isdigit() for c in t), -len(t))):
        low = tok.lower()
        if low in asked or low in seen or len(tok) < 4:
            continue
        seen.add(low)
        picked.append(tok)
        if len(picked) == 2:
            break
    return [{"type": "answer_contains", "all": picked}] if picked else []


def grade(task: dict, completion: str, extra: list[dict]) -> list[str]:
    """Run the gate's own checks. Returns failure descriptions (empty = pass)."""
    item = {"question": task["question"],
            "expected_answer": task.get("expected_answer", "")}
    failures = []
    for chk in list(task.get("checks") or []) + extra:
        # judge_correctness needs a reference answer; judge_safety/honesty judge
        # the reply itself, so a restraint demo must actually be judged.
        if chk.get("type") == "judge_correctness" and not item["expected_answer"]:
            continue
        try:
            ok, why = gate.check_one(chk, item, completion)
        except Exception as exc:
            ok, why = False, f"{chk.get('type')} raised {exc}"
        if not ok:
            failures.append(f"{chk.get('type')}: {why}")
    return failures


def tool_failure(payload: str) -> str:
    """Is this result a broken tool rather than a real answer?

    `execute_command` is currently dead in this container (its Woodpecker step
    cannot reach the internal forge) and `job_*` names that do not exist 404.
    Training on those results would teach the reflex *and* its wrong outcome, so
    such tasks are dropped and reported as environment faults.
    """
    head = payload.lstrip()[:400]
    if head.startswith("ERROR:"):
        return head.splitlines()[0][:120]
    if '"success": false' in payload or '"status": "error"' in payload:
        return "tool returned success:false"
    if '"status": "FAILURE"' in payload:
        return "tool run FAILED (console shows errors)"
    return ""


# Cheap liveness probes: a tool that cannot answer its simplest call is an
# environment fault, and finding that out once beats discovering it inside every
# task that uses it (execute_command's failure path alone costs 150 s a call).
PROBES: dict[str, dict] = {
    "read_file": {"path": "SOUL.md"},
    "write_file": {"path": "/tmp/nanomilady_demo/probe.txt", "content": "ok"},
    "edit_file": {"path": "/tmp/nanomilady_demo/probe.txt",
                  "old_string": "ok", "new_string": "ok"},
    "execute_command": {"command": "true"},
    "emacs_ping": {},
    "emacs_eval": {"code": "(+ 1 1)"},
    "job_list": {"name": "ad-hoc"},
    "job_status": {"name": "ad-hoc", "number": 1},
    "job_run": {"name": "ad-hoc"},
    "get_milady_time": {},
    "get_divine_rng": {},
}


def probe_tools(tools_needed, mcp: MCPClient, timeout: float = 25.0) -> dict:
    """{tool: reason} for every tool that cannot serve its simplest call."""
    broken = {}
    # Definition order, not alphabetical: edit_file needs the scratch file that
    # write_file's probe creates (sorted() probed it first and failed).
    for tool in [k for k in PROBES if k in tools_needed]:
        args = PROBES.get(tool)
        if args is None:
            continue
        try:
            payload = tools.execute({"tool": tool, **args}, index=None,
                                    client=mcp, timeout=timeout)
        except Exception as exc:
            broken[tool] = f"{type(exc).__name__}: {exc}"
            continue
        why = tool_failure(payload)
        if why:
            broken[tool] = why
    return broken


def run_task(task: dict, mcp: MCPClient) -> tuple[dict | None, dict]:
    """Teacher -> real call -> real result -> teacher's answer, then the gate."""
    question = task["question"]
    restraint = task.get("family") == "restraint"
    authored_think = (RESTRAINT_THINK if task.get("domain") == "safety"
                      else AUTHORED_THINK)
    expects_tool = any(c.get("type") == "tool_call"
                       for c in (task.get("checks") or []))
    messages = [{"role": "system", "content": SYSTEM_AGENTIC},
                {"role": "user", "content": question}]
    # Rebuilt, never copied: the completion is assembled from the parsed call,
    # the REAL result and the teacher's prose, in the student's grammar.
    think, completion, results, calls, why, nudged = "", "", [], [], "", False

    for step in range(MAX_STEPS):
        raw = llm.chat(messages, role="teacher", temperature=GENERATION_TEMP)
        if (step == 0 and not nudged and "</think>" not in raw
                and not parse_tool_calls(raw)):
            # A direct answer still has to show the reasoning contract; ask once,
            # explicitly, rather than inventing the missing block.
            nudged = True
            raw = llm.chat(messages + [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": "Remember the format. For example:\n"
                                            "<think>This is simple arithmetic.</think>\n"
                                            "Four.\nNow answer me in that exact shape."},
            ], role="teacher", temperature=GENERATION_TEMP)
        text = strip_seed(raw) if step == 0 else answer_only(raw)
        found = parse_tool_calls(raw)

        if not found:
            if step == 0 and expects_tool:
                why = "teacher answered without calling a tool"
                break
            if restraint and "</think>" not in raw:
                why = "teacher only reasoned, never answered"
                break
            completion += "\n\n" + text.strip()
            break
        if len(found) > 1:
            why = f"teacher emitted {len(found)} calls in one turn"
            break
        call = found[0]
        # A restraint task MAY involve a look before declining (and the suite's
        # judge judges the answer, not the route). What is never allowed is a
        # call the harness would have to invent a result for, so the call is
        # executed for real like any other.
        if not tools.is_known(call.get("tool")):
            why = f"unknown tool {call.get('tool')!r}"
            break

        if step == 0:
            # A restraint demo shows the ANSWER, never the teacher's
            # deliberation ("We need answer user: ... Need likely refuse?"), and
            # any look it took first stays in the trajectory with its real
            # result — dropping those would leave the answer claiming a lookup
            # nobody can see.
            think = authored_think if restraint else text
            if not think:
                why = "empty reasoning block"
                break
            completion += think + "\n</think>\n"

        payload = tools.execute(call, index=None, client=mcp)
        calls.append(call)
        results.append(payload)
        completion += "\n" + call_line(call) + "\n\n" + result_block(payload) + "\n"
        messages.append({"role": "assistant", "content": raw})
        messages.append({"role": "user", "content": result_block(payload)})
    else:
        why = f"still calling tools after {MAX_STEPS} turns"

    info = {"id": task["id"], "tool": task.get("tool"), "origin": task["origin"],
            "steps": len(calls), "calls": calls,
            "result_chars": [len(r) for r in results],
            "digest": [r[:160] for r in results]}

    if why:
        info["kept"] = False
        info["reason"] = why
        return None, info

    problems = [(c.get("tool"), tool_failure(r)) for c, r in zip(calls, results)]
    problems = [(tool, why) for tool, why in problems if why]
    # Direct answers still have to demonstrate the reasoning contract, and the
    # teacher will not reason about "what is 2 + 2" at any temperature. The shown
    # reasoning is then AUTHORED (as build_r2_warmup's think lines always were)
    # and the row says so, rather than pretending the teacher produced it.
    if not expects_tool and "</think>" not in completion:
        completion = authored_think + "\n</think>\n" + completion.strip()
        info["authored_think"] = True

    # An errored call then a correct one is a real, honest trajectory (the loop
    # recovering) — worth keeping, but a clean attempt beats it, so main() picks
    # the best of several.
    if restraint:
        info["authored_think"] = True
    info["repaired"] = bool(problems)
    info["problems"] = [f"{tool}: {why}" for tool, why in problems]
    # A trajectory that ENDS on a broken call teaches the wrong reflex, however
    # honest its report (a 404 on a job that does not exist is node state, not a
    # skill). Only a recovery that finished on a working call is worth keeping.
    info["ended_clean"] = not (problems and problems[-1][0] == calls[-1].get("tool"))

    if completion.count("</think>") != 1:
        info.update(kept=False,
                    reason=f"completion has {completion.count('</think>')} think blocks")
        return None, info
    if completion.lstrip().startswith("<"):
        info.update(kept=False, reason="completion starts with a tag, not reasoning")
        return None, info
    if len(parse_tool_calls(completion)) != len(calls):
        info.update(kept=False, reason="rebuilt completion lost a tool call")
        return None, info

    extra = ground_from(task, results)
    failures = grade(task, completion, extra)
    if failures:
        info.update(kept=False, reason="; ".join(failures),
                    derived_checks=extra)
        return None, info

    info.update(kept=True, derived_checks=extra)
    row = {"id": task["id"], "tool": task.get("tool"), "origin": task["origin"],
           "family": task.get("family") or "tool",
           "kind": "demo" if not info["repaired"] else "recovered",
           "completion_chars": len(completion),
           "tags": ["tool_trajectory"] + ([task["tool"]] if task.get("tool") else []),
           "prompt": messages[:2],  # system + question, as served
           "completion": completion.strip(),
           "steps": len(calls),
           "calls": calls,
           "repaired": bool(info.get("repaired"))}
    return row, info


def load_tasks() -> list[dict]:
    with open(TASKS) as f:
        return [json.loads(l) for l in f if l.strip()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="*", help="only these task ids")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--skip-probe", action="store_true")
    ap.add_argument("--attempts", type=int, default=3,
                    help="fresh attempts per task (a malformed first call is "
                         "not a demonstration)")
    ap.add_argument("--force", action="store_true",
                    help="redo tasks already present in the output")
    ap.add_argument("--out", default=OUT)
    args = ap.parse_args(argv)

    if not llm.server_up("teacher"):
        print(f"teacher not reachable at {config.role('teacher')['url']} "
              f"— start it first")
        return 1

    tasks = load_tasks()
    if args.ids:
        tasks = [t for t in tasks if t["id"] in set(args.ids)]
    done = set()
    if os.path.exists(args.out) and not args.force:
        with open(args.out) as f:
            done = {json.loads(l)["id"] for l in f if l.strip()}
        tasks = [t for t in tasks if t["id"] not in done]
    if args.limit:
        tasks = tasks[:args.limit]
    if not tasks:
        print("nothing to do (all tasks already generated; use --force)")
        return 0

    print(f"{len(tasks)} tasks to run (teacher={config.role('teacher')['url']}, "
          f"mcp={config.service('mcp')['url']})", flush=True)

    rows, report, t0 = [], [], time.time()
    with MCPClient() as mcp:
        broken = {} if args.skip_probe else probe_tools(
            {t.get("tool") for t in tasks}, mcp)
        if broken:
            print("\ntool health — these cannot answer their simplest call:")
            for tool, why in sorted(broken.items()):
                print(f"  {tool:18s} {why[:88]}")
            skipped = [t for t in tasks if t.get("tool") in broken]
            tasks = [t for t in tasks if t.get("tool") not in broken]
            for t in skipped:
                report.append({"id": t["id"], "tool": t.get("tool"),
                               "origin": t["origin"], "kept": False, "steps": 0,
                               "attempts": 0, "seconds": 0.0, "kind": "environment",
                               "reason": f"{t['tool']} is broken: {broken[t['tool']][:90]}"})
            print(f"  -> {len(skipped)} task(s) skipped as environment faults\n",
                  flush=True)

        for n, task in enumerate(tasks, 1):
            t1 = time.time()
            row, info, best = None, {}, None
            for attempt in range(1, max(1, args.attempts) + 1):
                try:
                    candidate, cinfo = run_task(task, mcp)
                except Exception as exc:  # a teacher/MCP hiccup must not lose the run
                    candidate, cinfo = None, {"id": task["id"],
                                              "tool": task.get("tool"),
                                              "reason": f"{type(exc).__name__}: {exc}"}
                cinfo["attempts"] = attempt
                if candidate and not cinfo.get("repaired"):
                    row, info = candidate, cinfo  # clean: take it and stop
                    break
                if candidate and cinfo.get("ended_clean") and best is None:
                    best = (candidate, cinfo)   # recovered: fallback only
                row, info = candidate, cinfo
            if row is None and best is not None:
                row, info = best
            if (not row and info.get("kind") == "environment"
                    and task.get("tool") not in broken):
                info["kind"] = "teacher"
            info["seconds"] = round(time.time() - t1, 1)
            report.append(info)
            mark = "kept " if row else "DROP "
            print(f"[{n}/{len(tasks)}] {mark}{task['id']:18s} "
                  f"{info.get('steps', 0)} call(s) "
                  f"x{info.get('attempts', 1)} {info['seconds']:5.1f}s "
                  f"{'' if row else '— ' + str(info.get('reason'))[:80]}", flush=True)
            if row:
                rows.append(row)

    # Write semantics: a run REPLACES the rows it regenerated and leaves every
    # other row alone. Regenerating a subset (--ids) must not truncate the file
    # to that subset, and a run that keeps nothing must not empty it either.
    attempted = {t["id"] for t in tasks} | {d for d in done if args.ids and d in set(args.ids)}
    kept_rows = []
    if os.path.exists(args.out):
        with open(args.out) as f:
            kept_rows = [json.loads(l) for l in f
                         if l.strip() and json.loads(l)["id"] not in attempted]
    all_rows = kept_rows + rows
    with open(args.out, "w") as f:
        for r in all_rows:
            f.write(json.dumps(r) + "\n")

    with open(REPORT, "w") as f:
        json.dump({"generated_at": int(time.time()),
                   "tasks": report,
                   "kept": sum(1 for r in report if r.get("kept")),
                   "total": len(report)}, f, indent=1)

    kept = sum(1 for r in report if r.get("kept"))
    env = sum(1 for r in report if r.get("kind") == "environment")
    total_lines = sum(1 for _ in open(args.out)) if os.path.exists(args.out) else 0
    print(f"\nkept {kept}/{len(report)} this run in {time.time() - t0:.0f}s "
          f"({env} skipped as environment faults) "
          f"-> {args.out} ({total_lines} rows total)", flush=True)
    by_tool: dict[str, list[int]] = {}
    for r in report:
        k, d = by_tool.setdefault(r.get("tool") or "(no tool)", [0, 0])
        by_tool[r.get("tool") or "(no tool)"] = [k + (1 if r.get("kept") else 0), d + 1]
    for tool, (k, d) in sorted(by_tool.items()):
        print(f"  {tool:16s} {k}/{d}")
    print(f"\nreport -> {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
