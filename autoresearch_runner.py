#!/usr/bin/env python3
"""autoresearch_runner — evaluate a candidate train.py on the A4000 (GPU 1).

The Symphony agent (in a k8s pod, no GPU) POSTs a candidate train.py here; this
runs it in the workstation's proven uv venv with CUDA_VISIBLE_DEVICES=1 and
returns the parsed summary. This is the GPU executor for the program.md loop.

Endpoints
    GET  /health                -> {"ok": true, ...}
    POST /experiment            -> {"val_bpb": ..., "peak_vram_mb": ..., ...}
         body: {"train_py": "<content>", "description": "..."}  (JSON)
           or: text/plain body = the train.py content

Env
    AUTORESEARCH_REPO   repo checkout (default ~/Documents/autoresearch)
    AUTORESEARCH_GPU    CUDA_VISIBLE_DEVICES value (default 1 = A4000)
    AUTORESEARCH_TIMEOUT  seconds (default 900)
    AUTORESEARCH_RUNNER_PORT (default 18700)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = os.path.expanduser(os.environ.get("AUTORESEARCH_REPO", "~/Documents/autoresearch"))
GPU = os.environ.get("AUTORESEARCH_GPU", "1")
TIMEOUT = int(os.environ.get("AUTORESEARCH_TIMEOUT", "900"))
PORT = int(os.environ.get("AUTORESEARCH_RUNNER_PORT", "18700"))
UV = os.path.expanduser(os.environ.get("AUTORESEARCH_UV", "~/.local/bin/uv"))

SUMMARY_KEYS = (
    "val_bpb",
    "training_seconds",
    "total_seconds",
    "peak_vram_mb",
    "mfu_percent",
    "total_tokens_M",
    "num_steps",
    "num_params_M",
    "depth",
)


def parse_summary(text: str) -> dict:
    out: dict = {}
    for key in SUMMARY_KEYS:
        m = re.search(rf"^{re.escape(key)}:\s*([0-9.eE+-]+)", text, re.MULTILINE)
        if m:
            try:
                out[key] = float(m.group(1))
            except ValueError:
                pass
    return out


def run_candidate(content: str, description: str = "") -> dict:
    target = os.path.join(REPO, "train.py")
    if not os.path.isdir(REPO):
        return {"ok": False, "error": f"repo not found: {REPO}"}
    if not os.path.exists(target):
        return {"ok": False, "error": f"train.py not found in {REPO}"}

    backup = target + ".runner-backup"
    shutil.copy2(target, backup)
    log_path = os.path.join(REPO, "run.log")
    started = time.time()
    try:
        with open(target, "w") as fh:
            fh.write(content)
        env = dict(os.environ)
        env["CUDA_VISIBLE_DEVICES"] = GPU
        env["PATH"] = os.path.dirname(UV) + ":" + env.get("PATH", "")
        with open(log_path, "w") as log:
            proc = subprocess.run(
                [UV, "run", "train.py"],
                cwd=REPO,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=TIMEOUT,
            )
        text = open(log_path, errors="replace").read()
        summary = parse_summary(text)
        return {
            "ok": proc.returncode == 0 and "val_bpb" in summary,
            "returncode": proc.returncode,
            "description": description,
            "seconds": round(time.time() - started, 1),
            "summary": summary,
            "val_bpb": summary.get("val_bpb"),
            "peak_vram_mb": summary.get("peak_vram_mb"),
            "tail": text[-2000:],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout after {TIMEOUT}s", "description": description}
    finally:
        shutil.move(backup, target)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):  # keep the journal quiet
        pass

    def do_GET(self):
        if self.path.rstrip("/") in ("/health", ""):
            self._send(200, {"ok": True, "repo": REPO, "gpu": GPU, "timeout": TIMEOUT})
        else:
            self._send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if self.path.rstrip("/") != "/experiment":
            self._send(404, {"ok": False, "error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length).decode("utf-8", "replace")
        ctype = (self.headers.get("Content-Type") or "").lower()
        if "json" in ctype:
            try:
                data = json.loads(raw or "{}")
            except json.JSONDecodeError as exc:
                self._send(400, {"ok": False, "error": f"bad json: {exc}"})
                return
            content = data.get("train_py") or ""
            description = data.get("description", "")
        else:
            content = raw
            description = self.headers.get("X-Description", "")
        if not content.strip():
            self._send(400, {"ok": False, "error": "empty train_py"})
            return
        try:
            result = run_candidate(content, description)
        except Exception as exc:  # never kill the server
            result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        self._send(200 if result.get("ok") else 500, result)


def main() -> None:
    if not os.path.isdir(REPO):
        raise SystemExit(f"repo not found: {REPO}")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"autoresearch_runner on :{PORT} repo={REPO} gpu={GPU}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
