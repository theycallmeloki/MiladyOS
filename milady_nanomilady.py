"""milady_nanomilady.py — control plane for nanomilady (MCP-facing).

Deliberately **read-mostly**. The expensive work (training, gating, merging,
promotion) runs as systemd units — `nanomilady-student.service`,
`nanomilady-gate@.service`, and later the conductor. An MCP call therefore
never blocks on a GPU job: it reads the round state the loop wrote and reports.

State layout (all under AutoDidact/rounds/):
  champion.json        {"tag", "model_dir", "decided_at", "domains"}
  <tag>/eval.json      {"tag","domains":{d:{passed,n,rate,ci95}}, "decision", ...}

See docs/nanomilady-evolution-plan.md.
"""

import json
import os
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "AutoDidact")
ROUNDS = os.path.join(ROOT, "rounds")
CHAMPION = os.path.join(ROUNDS, "champion.json")
SUITE = os.path.join(ROOT, "capability_suite.jsonl")
STUDENT_ENV = os.path.expanduser("~/.config/nanomilady/student.env")
STUDENT_HEALTH = os.environ.get("NANOMILADY_HEALTH",
                                "http://127.0.0.1:8081/health")
JUDGE_HEALTH = os.environ.get("JUDGE_HEALTH", "http://127.0.0.1:18020/health")


def _json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _health(url, timeout=3):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _env(path):
    out = {}
    try:
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    except Exception:
        pass
    return out


def _suite():
    """Item count and per-domain totals from the frozen suite."""
    try:
        from collections import Counter
        items = [json.loads(l) for l in open(SUITE) if l.strip()]
        return {"items": len(items), "domains": dict(Counter(i["domain"] for i in items))}
    except Exception as e:
        return {"items": 0, "domains": {}, "error": str(e)}


def champion():
    """The currently promoted round, or a sensible default."""
    c = _json(CHAMPION)
    if c:
        return c
    return {"tag": None, "model_dir": _env(STUDENT_ENV).get("MODEL_DIR"),
            "decided_at": None, "domains": {}, "note": "no promotion recorded yet"}


def rounds():
    """Every scored round, newest first, with domain rates (no completions)."""
    out = []
    if not os.path.isdir(ROUNDS):
        return out
    for name in sorted(os.listdir(ROUNDS), reverse=True):
        p = os.path.join(ROUNDS, name, "eval.json")
        if not os.path.isfile(p):
            flat = os.path.join(ROUNDS, f"{name}.json")
            p = flat if os.path.isfile(flat) else None
        if not p:
            continue
        d = _json(p) or {}
        out.append({
            "tag": d.get("tag", name),
            "decision": d.get("decision"),
            "domains": {k: {"rate": v.get("rate"), "passed": v.get("passed"),
                            "n": v.get("n")}
                        for k, v in (d.get("domains") or {}).items()},
            "reasons": d.get("reasons", []),
        })
    return out


def gate_result(tag):
    """The full gate payload for one round tag (includes failing item ids)."""
    for p in (os.path.join(ROUNDS, tag, "eval.json"),
              os.path.join(ROUNDS, f"{tag}.json")):
        d = _json(p)
        if d:
            return d
    return {"error": f"no gate result for tag {tag!r}"}


def status():
    """One call that answers 'where is nanomilady right now?'"""
    champ = champion()
    return {
        "champion": champ,
        "student": {
            "health": _health(STUDENT_HEALTH),
            "endpoint": STUDENT_HEALTH.replace("/health", ""),
            "model_dir": _env(STUDENT_ENV).get("MODEL_DIR"),
            "unit": "nanomilady-student.service",
        },
        "judge_27b": {"health": _health(JUDGE_HEALTH),
                      "endpoint": JUDGE_HEALTH.replace("/health", "")},
        "suite": _suite(),
        "rounds": rounds(),
        "plan": "AutoDidact/docs/nanomilady-evolution-plan.md",
    }


# ── MCP entry points (thin wrappers, kept import-light) ──────────────────
def mcp_status():
    return {"success": True, "status": "success", "data": status()}


def mcp_rounds():
    return {"success": True, "status": "success", "data": {"rounds": rounds()}}


def mcp_gate_result(tag):
    if not tag:
        return {"success": False, "status": "error", "error": "tag is required"}
    return {"success": True, "status": "success", "data": gate_result(tag)}
