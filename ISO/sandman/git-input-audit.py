#!/usr/bin/env python3
"""git-input audit — which repos are both remote-backed and watched?

The tracking gap this closes: a pipeline can declare a mirror repo AND a git
remote (`input.git.url`), so pushes auto-flow into the mirror and trigger the
watch — but nothing lists those mappings, so "is this repo actually tracked,
and is the mirror current?" is guesswork.

Prints one row per git-input pipeline:

    pipeline            url                              mirror    branch  head      age

`head` is the mirror branch head the watch last ran against; a `-` means the
repo is mapped but has no commit yet (the remote has not been seen). Uses the
sandman HTTP API only (no CLI, no sandman binary needed).

    ISO/sandman/git-input-audit.py [--addr host:port] [--json]

Mirrors the endpoints sandman-pipelines/buildbus uses:
    GET /api/v1/pipelines
    GET /api/v1/repos/<name>/branches/<branch>/head
"""
import argparse
import datetime as dt
import json
import sys
import urllib.request

DEFAULT_ADDR = "192.168.1.15:4242"


def get(base: str, path: str, timeout: int = 15):
    with urllib.request.urlopen(base + path, timeout=timeout) as r:
        return json.load(r)


def maybe_get(base: str, path: str):
    try:
        return get(base, path)
    except Exception:
        return None


def age(ts: str) -> str:
    if not ts:
        return "-"
    try:
        t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return "?"
    d = dt.datetime.now(dt.timezone.utc) - t
    s = int(d.total_seconds())
    for unit, n in (("d", 86400), ("h", 3600), ("m", 60)):
        if s >= n:
            return f"{s // n}{unit}"
    return f"{s}s"


def git_inputs(pipelines):
    out = []
    for p in pipelines if isinstance(pipelines, list) else pipelines.get("pipelines", []):
        inp = p.get("input") or {}
        git = inp.get("git") or {}
        url = git.get("url")
        if not url:
            continue
        name = p.get("name") or inp.get("name") or ""
        repo = inp.get("repo") or inp.get("name") or ""
        branch = git.get("branch") or inp.get("branch") or "master"
        out.append((name, url, repo, branch))
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--addr", default=DEFAULT_ADDR, help="sandman control plane (default %(default)s)")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    a = ap.parse_args()
    base = a.addr if a.addr.startswith("http") else "http://" + a.addr

    pipelines = maybe_get(base, "/api/v1/pipelines")
    if pipelines is None:
        print(f"git-input-audit: cannot reach {base}", file=sys.stderr)
        return 1

    rows = []
    for name, url, repo, branch in git_inputs(pipelines):
        head = maybe_get(base, f"/api/v1/repos/{repo}/branches/{branch}/head") or {}
        rows.append({
            "pipeline": name,
            "url": url,
            "mirror": repo,
            "branch": branch,
            "head": (head.get("id") or "")[:12] or "-",
            "age": age(head.get("committedAt") or head.get("createdAt") or ""),
        })

    if a.json:
        print(json.dumps(rows, indent=2))
        return 0

    if not rows:
        print("no git-input pipelines found")
        return 0
    w = max(len(r["pipeline"]) for r in rows)
    print(f"{'pipeline':<{w}}  {'url':<52}  {'mirror':<14}  branch  head          age")
    for r in rows:
        print(f"{r['pipeline']:<{w}}  {r['url']:<52}  {r['mirror']:<14}  "
              f"{r['branch']:<6}  {r['head']:<12}  {r['age']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
