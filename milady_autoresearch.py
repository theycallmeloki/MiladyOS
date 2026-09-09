#!/usr/bin/env python3
"""milady_autoresearch — MiladyOS control plane for karpathy/autoresearch.

Two execution paths, one metric (`val_bpb`, lower is better):

  A. Symphony executes / MiladyOS decides
     MiladyOS enqueues an experiment as a Symphony intent bound to the
     sandman mirror of the autoresearch repo. Symphony materializes the
     mirror head into an isolated workspace, a pi agent runs one
     experiment, and the thread parks `awaiting`. MiladyOS then reads the
     result and calls deploy (keep) or close (discard) — the deploy emits a
     git delta back to sandman, which commits it onto the mirror and
     re-triggers the bound pipeline. That is autoresearch's git
     keep/discard loop, with MiladyOS as the research director.

  C. MiladyOS drives train.py directly (AlphaEvolve-style)
     `run_experiment()` runs `uv run train.py` on a local GPU and records
     val_bpb. `run_candidate()` does the same for an arbitrary candidate
     train.py, which is the fitness function for evolutionary search.

Deliberately pure stdlib (urllib) so the same module drops into the MCP
server, a container, or a CLI without new dependencies.

Environment overrides:
  AUTORESEARCH_DIR       checkout to run (default ~/Documents/autoresearch)
  AUTORESEARCH_REPO_URL  mirror binding (default theycallmeloki/autoresearch.git)
  AUTORESEARCH_BRANCH    mirror branch (default master)
  AUTORESEARCH_STORE     JSONL result store for Symphony intents
  SANDMAN_ADDR           sandman control plane (default 192.168.1.15:4242)
  SYMPHONY_URL           Symphony base URL
  SYMPHONY_AUTH          Symphony basic auth user:pass (default milady:milady)
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value else default


def repo_dir() -> str:
    return _env("AUTORESEARCH_DIR", os.path.expanduser("~/Documents/autoresearch"))


def repo_url() -> str:
    return _env("AUTORESEARCH_REPO_URL", "https://github.com/theycallmeloki/autoresearch.git")


def repo_branch() -> str:
    return _env("AUTORESEARCH_BRANCH", "master")


def sandman_addr() -> str:
    addr = _env("SANDMAN_ADDR", "http://192.168.1.15:4242")
    return addr if addr.startswith("http") else "http://" + addr


def symphony_url() -> str:
    return _env("SYMPHONY_URL", "https://symphony.transparentlyrotatableproxy.site").rstrip("/")


def symphony_auth() -> str:
    return _env("SYMPHONY_AUTH", "milady:milady")


def store_path() -> str:
    return _env("AUTORESEARCH_STORE", os.path.join(HERE, "data", "autoresearch", "results.jsonl"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# HTTP (stdlib only)
# ---------------------------------------------------------------------------

def http_json(method: str, url: str, body=None, auth: str | None = None, timeout: int = 30):
    """Request JSON, returning (status, parsed-or-text). Never raises on HTTP."""
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if auth:
        token = base64.b64encode(auth.encode()).decode()
        headers["Authorization"] = "Basic " + token
    req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        status = exc.code
    except Exception as exc:  # connection refused, DNS, timeout ...
        return 0, {"error": f"{type(exc).__name__}: {exc}", "url": url}
    try:
        return status, json.loads(raw)
    except Exception:
        return status, raw


def sandman_get(path: str, timeout: int = 15):
    return http_json("GET", sandman_addr() + path, timeout=timeout)


def symphony_get(path: str, timeout: int = 20):
    return http_json("GET", symphony_url() + path, auth=symphony_auth(), timeout=timeout)


def symphony_post(path: str, body=None, timeout: int = 30):
    return http_json("POST", symphony_url() + path, body=body if body is not None else {},
                     auth=symphony_auth(), timeout=timeout)


# ---------------------------------------------------------------------------
# Local autoresearch checkout
# ---------------------------------------------------------------------------

def _git(*args: str, cwd: str | None = None) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", cwd or repo_dir(), *args],
            capture_output=True, text=True, timeout=30,
        )
        return out.stdout.strip()
    except Exception:
        return ""


def git_info() -> dict:
    d = repo_dir()
    return {
        "dir": d,
        "exists": os.path.isdir(d),
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "commit": _git("rev-parse", "--short", "HEAD"),
        "dirty": bool(_git("status", "--porcelain")),
    }


def _results_tsv() -> str:
    return os.path.join(repo_dir(), "results.tsv")


def read_results() -> list[dict]:
    path = _results_tsv()
    rows: list[dict] = []
    if not os.path.isfile(path):
        return rows
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("commit\t"):
                continue
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            try:
                val = float(parts[1])
            except ValueError:
                continue
            rows.append({
                "commit": parts[0],
                "val_bpb": val,
                "memory_gb": float(parts[2]) if parts[2] else 0.0,
                "status": parts[3],
                "description": parts[4] if len(parts) > 4 else "",
            })
    return rows


def best_result() -> dict | None:
    kept = [r for r in read_results() if r["status"] == "keep" and r["val_bpb"] > 0]
    return min(kept, key=lambda r: r["val_bpb"]) if kept else None


def append_result(commit: str, val_bpb: float, memory_gb: float, status: str, description: str) -> dict:
    path = _results_tsv()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("commit\tval_bpb\tmemory_gb\tstatus\tdescription\n")
    row = {"commit": commit, "val_bpb": round(val_bpb, 6), "memory_gb": round(memory_gb, 1),
           "status": status, "description": description}
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(f"{row['commit']}\t{row['val_bpb']:.6f}\t{row['memory_gb']:.1f}\t{row['status']}\t{row['description']}\n")
    return row


_SUMMARY_KEYS = {
    "val_bpb", "training_seconds", "total_seconds", "peak_vram_mb",
    "mfu_percent", "total_tokens_M", "num_steps", "num_params_M", "depth",
}


def parse_summary(log_text: str) -> dict:
    """Extract the `key: value` summary block train.py prints at the end."""
    found: dict[str, float] = {}
    for line in log_text.splitlines():
        m = re.match(r"^([a-zA-Z_]+):\s+([0-9.eE+-]+)\s*$", line.strip())
        if m and m.group(1) in _SUMMARY_KEYS:
            try:
                found[m.group(1)] = float(m.group(2))
            except ValueError:
                pass
    return found


def run_experiment(description: str = "", timeout: int = 900, gpu: int = 0,
                   cwd: str | None = None, log_path: str | None = None) -> dict:
    """Run one `uv run train.py` experiment and record the result.

    Returns a dict with metrics + status. On crash, status='crash' and the
    tail of run.log is included so the caller can fix or discard.
    """
    d = cwd or repo_dir()
    log_path = log_path or os.path.join(d, "run.log")
    uv = os.path.expanduser("~/.local/bin/uv")
    if not os.path.exists(uv):
        uv = "uv"
    env = dict(os.environ)
    env.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")
    if gpu is not None:
        env["CUDA_VISIBLE_DEVICES"] = str(gpu)

    started = time.time()
    try:
        with open(log_path, "w", encoding="utf-8") as log:
            proc = subprocess.run([uv, "run", "train.py"], cwd=d, env=env,
                                  stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        rc = -9
    duration = round(time.time() - started, 1)

    with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
        log_text = fh.read()
    summary = parse_summary(log_text)
    commit = _git("rev-parse", "--short", "HEAD", cwd=d) or "unknown"

    if rc != 0 or "val_bpb" not in summary:
        tail = "\n".join(log_text.splitlines()[-25:])
        append_result(commit, 0.0, 0.0, "crash", description or "experiment crashed")
        return {"success": False, "status": "crash", "returncode": rc,
                "duration_seconds": duration, "log_tail": tail, "description": description}

    val_bpb = summary["val_bpb"]
    memory_gb = summary.get("peak_vram_mb", 0.0) / 1024.0
    prev = best_result()
    improved = prev is None or val_bpb < prev["val_bpb"]
    status = "keep" if improved else "discard"
    row = append_result(commit, val_bpb, memory_gb, status, description or "experiment")
    return {"success": True, "status": status, "improved": improved,
            "val_bpb": val_bpb, "memory_gb": round(memory_gb, 1),
            "duration_seconds": duration, "commit": commit,
            "previous_best": prev, "row": row,
            "training_seconds": summary.get("training_seconds"),
            "num_steps": summary.get("num_steps"),
            "num_params_M": summary.get("num_params_M")}


def run_candidate(content: str, description: str = "", timeout: int = 900,
                  gpu: int = 0, cwd: str | None = None) -> dict:
    """Evaluate a candidate train.py: swap it in, run, restore, record.

    This is the fitness function for evolutionary search (option C). The
    candidate is written over train.py for the duration of the run and the
    original is restored afterwards, so a crash never loses the baseline.
    """
    d = cwd or repo_dir()
    target = os.path.join(d, "train.py")
    backup = None
    if os.path.isfile(target):
        with open(target, "r", encoding="utf-8", errors="replace") as fh:
            backup = fh.read()
    try:
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(content)
        return run_experiment(description=description, timeout=timeout, gpu=gpu, cwd=d)
    finally:
        if backup is not None:
            with open(target, "w", encoding="utf-8") as fh:
                fh.write(backup)


# ---------------------------------------------------------------------------
# sandman mirror
# ---------------------------------------------------------------------------

def sandman_status() -> dict:
    status, repos = sandman_get("/api/v1/repos")
    _, pipelines = sandman_get("/api/v1/pipelines")
    _, jobs = sandman_get("/api/v1/jobs")
    mirror = None
    if isinstance(repos, list):
        mirror = next((r for r in repos if r.get("name") == "autoresearch"), None)
    pipe = None
    if isinstance(pipelines, list):
        pipe = next((p for p in pipelines if p.get("name") == "autoresearch-watch"), None)
    recent = []
    if isinstance(jobs, list):
        recent = [j for j in jobs if j.get("pipeline") == "autoresearch-watch"][:5]
    return {
        "sandman": sandman_addr(),
        "reachable": status == 200,
        "mirror_repo": mirror,
        "binding_pipeline": pipe,
        "recent_jobs": recent,
    }


def sandman_head() -> dict:
    """Mirror head via the `sandman` CLI (the stable interface Symphony uses)."""
    try:
        out = subprocess.run(["sandman", "--addr", sandman_addr().replace("http://", ""),
                              "commit", "list", "autoresearch@master", "--json"],
                             capture_output=True, text=True, timeout=20)
        if out.returncode == 0:
            return {"ok": True, "commits": json.loads(out.stdout or "[]")}
        return {"ok": False, "error": out.stderr.strip() or out.stdout.strip()}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Symphony control plane
# ---------------------------------------------------------------------------

def symphony_state() -> dict:
    status, payload = symphony_get("/api/v1/state")
    return {"status": status, "state": payload}


def symphony_intents(limit: int = 20, full: bool = False) -> dict:
    status, payload = symphony_get("/api/v1/intents")
    raw = (payload or {}).get("intents", []) if isinstance(payload, dict) else []
    intents = list(raw or [])
    by_state: dict = {}
    for item in intents:
        state = item.get("state", "?")
        by_state[state] = by_state.get(state, 0) + 1
    if full:
        return {"status": status, "count": len(intents), "by_state": by_state, "intents": intents}
    trimmed = [{
        "id": item.get("id"),
        "state": item.get("state"),
        "title": (item.get("title") or "")[:120],
        "repo": item.get("repo"),
        "updated_at": item.get("updated_at"),
    } for item in intents[: max(1, int(limit))]]
    return {"status": status, "count": len(intents), "by_state": by_state, "intents": trimmed}


def symphony_intent(intent_id: str) -> dict:
    status, payload = symphony_get(f"/api/v1/intents/{intent_id}")
    intent = (payload or {}).get("intent") if isinstance(payload, dict) else None
    return {"status": status, "intent": intent, "raw": payload if intent is None else None}


def symphony_create_intent(title: str, description: str = "", repo: str | None = None,
                           labels: list | None = None) -> dict:
    body = {"intent": {"title": title, "description": description,
                       "repo": repo or repo_url(), "labels": labels or ["autoresearch"]}}
    status, payload = symphony_post("/api/v1/intents", body)
    intent = (payload or {}).get("intent") if isinstance(payload, dict) else None
    return {"status": status, "intent": intent, "raw": payload if intent is None else None}


def symphony_action(intent_id: str, action: str) -> dict:
    if action not in {"deploy", "close", "cancel", "activate", "verify"}:
        return {"error": f"unsupported action: {action}"}
    status, payload = symphony_post(f"/api/v1/intents/{intent_id}/{action}")
    return {"status": status, "action": action, "result": payload}


def symphony_runs(intent_id: str) -> dict:
    status, payload = symphony_get(f"/api/v1/issues/{intent_id}/runs")
    return {"status": status, "runs": payload}


def symphony_transcript(intent_id: str, run_index: int = 0) -> dict:
    status, payload = symphony_get(f"/api/v1/issues/{intent_id}/runs/{run_index}/transcript")
    return {"status": status, "transcript": payload}


# ---------------------------------------------------------------------------
# Result store + result extraction
# ---------------------------------------------------------------------------

def record_result(intent_id: str, payload: dict) -> dict:
    os.makedirs(os.path.dirname(store_path()), exist_ok=True)
    entry = {"at": _now(), "intent_id": intent_id, **(payload or {})}
    with open(store_path(), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    return entry


def recorded_result(intent_id: str) -> dict | None:
    path = store_path()
    if not os.path.isfile(path):
        return None
    latest = None
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if entry.get("intent_id") == intent_id:
                latest = entry
    return latest


_RESULT_RE = re.compile(r"RESULT:\s*(\{.*?\})", re.S)


def extract_result(text: str) -> dict | None:
    """Pull a machine-readable result the agent printed in its transcript."""
    if not text:
        return None
    for m in reversed(_RESULT_RE.findall(text)):
        try:
            return json.loads(m)
        except Exception:
            continue
    # fallback: bare val_bpb line
    m = re.findall(r"val_bpb[:\s]+([0-9.]+)", text)
    if m:
        return {"val_bpb": float(m[-1])}
    return None


def _transcript_text(payload) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for key in ("transcript", "text", "content", "messages"):
            value = payload.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, list):
                return "\n".join(json.dumps(v) if not isinstance(v, str) else v for v in value)
    return json.dumps(payload)


def settle_intent(intent_id: str, decide: str = "auto", threshold: float = 0.0) -> dict:
    """Decide keep (deploy) or discard (close) for a parked experiment.

    Result precedence: a result recorded via `record_result` (the agent
    calling the MiladyOS MCP `autoresearch_record` tool), else a `RESULT:
    {...}` line in the run transcript, else a bare val_bpb in the transcript.
    """
    intent_info = symphony_intent(intent_id)
    intent = intent_info.get("intent")
    if intent is None:
        return {"success": False, "error": "intent not found",
                "http_status": intent_info.get("status"), "raw": intent_info.get("raw")}

    state = intent.get("state")
    result = recorded_result(intent_id)
    source = "store"
    if result is None:
        transcript = symphony_transcript(intent_id)
        result = extract_result(_transcript_text(transcript.get("transcript")))
        source = "transcript"

    if result is None or result.get("val_bpb") in (None, ""):
        return {"success": False, "status": "needs_result", "intent_state": state,
                "intent_id": intent_id,
                "hint": "agent must record the result (MCP autoresearch_record) or print RESULT: {...}"}

    val_bpb = float(result["val_bpb"])
    prev = best_result()
    improved = prev is None or val_bpb < prev["val_bpb"] - float(threshold or 0.0)

    if decide == "auto":
        decision = "keep" if improved else "discard"
    elif decide in {"keep", "discard"}:
        decision = decide
    else:
        return {"success": False, "error": f"decide must be auto|keep|discard, got {decide!r}"}

    if state != "awaiting":
        return {"success": False, "status": "not_ready", "intent_state": state,
                "intent_id": intent_id, "decision": decision, "val_bpb": val_bpb,
                "hint": "thread must be awaiting before settle can deploy/close it"}

    action = "deploy" if decision == "keep" else "close"
    action_result = symphony_action(intent_id, action)
    memory_gb = float(result.get("memory_gb") or (float(result.get("peak_vram_mb", 0)) / 1024.0))
    row = append_result(
        commit=str(result.get("commit") or intent.get("result", {}).get("commit") or "symphony"),
        val_bpb=val_bpb, memory_gb=memory_gb, status=decision,
        description=result.get("description") or intent.get("title") or "symphony experiment",
    )
    return {"success": True, "intent_id": intent_id, "decision": decision, "action": action,
            "improved": improved, "val_bpb": val_bpb, "previous_best": prev,
            "result_source": source, "action_result": action_result, "row": row}


# ---------------------------------------------------------------------------
# MCP-facing wrappers (plain dicts; the MCP server registers these)
# ---------------------------------------------------------------------------

def mcp_status() -> dict:
    best = best_result()
    return {
        "checkout": git_info(),
        "best": best,
        "results_count": len(read_results()),
        "recent_results": read_results()[-5:],
        "sandman": sandman_status(),
        "symphony": {"url": symphony_url(), **symphony_state()},
    }


def mcp_best() -> dict:
    return {"best": best_result(), "results_count": len(read_results())}


def mcp_run(description: str = "", timeout: int = 900, gpu: int = 0) -> dict:
    return run_experiment(description=description, timeout=timeout, gpu=gpu)


def mcp_enqueue(title: str, description: str = "", repo: str | None = None,
                labels: list | None = None) -> dict:
    created = symphony_create_intent(title=title, description=description, repo=repo, labels=labels)
    intent = created.get("intent")
    return {"success": intent is not None, "intent": intent,
            "http_status": created.get("status"), "raw": created.get("raw"),
            "repo": repo or repo_url()}


def mcp_record(intent_id: str, val_bpb: float, memory_gb: float | None = None,
               commit: str | None = None, description: str | None = None) -> dict:
    payload = {"val_bpb": val_bpb}
    if memory_gb is not None:
        payload["memory_gb"] = memory_gb
    if commit:
        payload["commit"] = commit
    if description:
        payload["description"] = description
    return {"success": True, "recorded": record_result(intent_id, payload)}


def mcp_settle(intent_id: str, decide: str = "auto", threshold: float = 0.0) -> dict:
    return settle_intent(intent_id, decide=decide, threshold=threshold)


def mcp_symphony_state() -> dict:
    return symphony_state()


def mcp_symphony_intents(limit: int = 20, full: bool = False) -> dict:
    return symphony_intents(limit=limit, full=full)
