"""Woodpecker/Forgejo plumbing behind the MCP pipeline tools.

Model B: milady only sees local files + "submit run". This client hides the
forge repo/file mechanics, the API token, repo activation and pipeline
triggering. Every endpoint here was verified live against woodpecker v3.18 +
forgejo 16.0.3; startup.sh performs the boot-time token dance that persists
WOODPECKER_TOKEN to /var/lib/woodpecker/.secrets (this client re-reads the
file lazily, since the MCP server boots before Phase B runs).
"""

import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

logger = logging.getLogger("woodpecker")

SECRETS_FILE = Path("/var/lib/woodpecker/.secrets")


def _load_secrets() -> Dict[str, str]:
    secrets: Dict[str, str] = {}
    try:
        for line in SECRETS_FILE.read_text().splitlines():
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                key, _, value = line.partition("=")
                secrets[key] = value
    except OSError:
        pass
    return secrets


class WoodpeckerClient:
    """Thin, verified client for the local Woodpecker/Forgejo stack."""

    def __init__(self) -> None:
        self.wp_url = os.getenv("WOODPECKER_URL", "http://localhost:8000").rstrip("/")
        self.forge_url = os.getenv("FORGE_PUBLIC_URL", "http://172.17.0.1:3000").rstrip("/")
        self.forge_user = os.getenv("MILADY_ADMIN_ID", "milady")
        self.forge_pass = os.getenv("MILADY_ADMIN_PASSWORD", "milady")
        self._token: Optional[str] = None
        self._repo_ids: Dict[str, int] = {}
        self._timeout = httpx.Timeout(30.0)

    # ---- auth --------------------------------------------------------------

    def token(self) -> str:
        # Lazy + re-read per call: startup.sh writes .secrets after the MCP
        # server boots, so the token may appear long after first use.
        if self._token is None:
            self._token = os.getenv("WOODPECKER_TOKEN") or _load_secrets().get("WOODPECKER_TOKEN", "")
        if not self._token:
            raise RuntimeError(
                "WOODPECKER_TOKEN missing — the startup token dance has not run; "
                "check /var/lib/woodpecker/.secrets"
            )
        return self._token

    def _wp_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token()}"}

    # ---- forge plumbing (repo + file mechanics) -----------------------------

    def forge_create_repo(self, name: str) -> None:
        """Create the forge repo if missing (auto-init on main)."""
        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(
                f"{self.forge_url}/api/v1/user/repos",
                auth=(self.forge_user, self.forge_pass),
                json={"name": name, "auto_init": True, "private": False, "default_branch": "main"},
            )
            if response.status_code == 409:
                return
            if response.status_code != 201:
                raise RuntimeError(f"forge create repo {name}: {response.status_code} {response.text[:200]}")

    def forge_upsert_file(self, repo: str, path: str, content: str) -> None:
        """Create or update a file in the forge repo (contents API)."""
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        with httpx.Client(timeout=self._timeout) as client:
            current = client.get(
                f"{self.forge_url}/api/v1/repos/{repo}/contents/{path}",
                auth=(self.forge_user, self.forge_pass),
            )
            payload: Dict[str, Any] = {"content": encoded, "message": f"miladyos_mcp: update {path}"}
            url = f"{self.forge_url}/api/v1/repos/{repo}/contents/{path}"
            if current.status_code == 200:
                # Exists -> PUT with the current sha (POST is create-only).
                payload["sha"] = current.json()["sha"]
                response = client.put(url, auth=(self.forge_user, self.forge_pass), json=payload)
            elif current.status_code == 404:
                response = client.post(url, auth=(self.forge_user, self.forge_pass), json=payload)
            else:
                raise RuntimeError(f"forge read {path}: {current.status_code} {current.text[:200]}")
            if response.status_code not in (200, 201):
                raise RuntimeError(f"forge write {path}: {response.status_code} {response.text[:200]}")

    # ---- woodpecker surface (activate / trigger / status / logs) ------------

    def repo_id(self, repo: str) -> int:
        """Woodpecker repo id; activates the repo first if needed (idempotent)."""
        cached = self._repo_ids.get(repo)
        if cached is not None:
            return cached
        with httpx.Client(timeout=self._timeout) as client:
            listed = client.get(f"{self.wp_url}/api/repos", headers=self._wp_headers())
            listed.raise_for_status()
            for row in listed.json():
                if row.get("full_name") == repo:
                    self._repo_ids[repo] = int(row["id"])
                    return int(row["id"])
            remote = client.get(
                f"{self.forge_url}/api/v1/repos/{repo}",
                auth=(self.forge_user, self.forge_pass),
            )
            remote.raise_for_status()
            remote_id = int(remote.json()["id"])
            response = client.post(
                f"{self.wp_url}/api/repos?forge_remote_id={remote_id}",
                headers=self._wp_headers(),
            )
            if response.status_code not in (200, 201):
                raise RuntimeError(f"activate {repo}: {response.status_code} {response.text[:200]}")
            self._repo_ids[repo] = int(response.json()["id"])
            return int(response.json()["id"])


    def forge_remote(self, repo: str) -> str:
        """Authenticated git URL for a forge repo (creds embedded; local forge)."""
        parts = urlsplit(self.forge_url)
        netloc = f"{quote(self.forge_user)}:{quote(self.forge_pass)}@{parts.netloc}"
        path = "/" + repo.lstrip("/") + ".git"
        return urlunsplit((parts.scheme, netloc, path, "", ""))

    def repo_secret_set(self, repo: str, name: str, value: str) -> None:
        """Ensure a repo-level woodpecker secret exists (name -> value).

        Idempotent: if the secret already exists it is left as-is (secrets are
        write-once here — value is not returned by the API, so we never
        overwrite blindly).
        """
        rid = self.repo_id(repo)
        with httpx.Client(timeout=self._timeout) as client:
            listed = client.get(f"{self.wp_url}/api/repos/{rid}/secrets", headers=self._wp_headers())
            listed.raise_for_status()
            if any((s.get("name") or "") == name for s in listed.json()):
                return
            response = client.post(
                f"{self.wp_url}/api/repos/{rid}/secrets",
                headers=self._wp_headers(),
                json={"name": name, "value": value},
            )
            if response.status_code not in (200, 201, 204):
                raise RuntimeError(
                    f"wp set secret {name}: {response.status_code} {response.text[:200]}"
                )

    def trigger(
        self,
        repo: str,
        branch: str = "main",
        variables: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Trigger a pipeline; returns the created pipeline's summary."""
        repo_id = self.repo_id(repo)
        payload: Dict[str, Any] = {"branch": branch}
        if variables:
            payload["variables"] = variables
        with httpx.Client(timeout=self._timeout) as client:
            response = client.post(
                f"{self.wp_url}/api/repos/{repo_id}/pipelines",
                headers=self._wp_headers(),
                json=payload,
            )
            if response.status_code not in (200, 201):
                raise RuntimeError(f"trigger {repo}: {response.status_code} {response.text[:200]}")
            pipeline = response.json()
            # NOTE: the API's {pipeline} path param resolves by NUMBER, not
            # the DB id (verified: GET /pipelines/{db_id} 404s when they
            # diverge). Return the number as pipeline_id.
            return {
                "pipeline_id": int(pipeline["number"]),
                "number": pipeline.get("number"),
                "status": pipeline.get("status"),
                "event": pipeline.get("event"),
                "repo": repo,
            }

    def pipeline_status(self, repo: str, pipeline_id: int) -> Dict[str, Any]:
        """Pipeline state plus a per-step summary."""
        raw = self._pipeline(repo, pipeline_id)
        steps = []
        for workflow in raw.get("workflows", []) or []:
            for step in workflow.get("children", []) or []:
                steps.append(
                    {
                        "name": step.get("name"),
                        "state": step.get("state"),
                        "exit_code": step.get("exit_code"),
                    }
                )
        return {
            "pipeline_id": pipeline_id,
            "number": raw.get("number"),
            "status": raw.get("status"),
            "event": raw.get("event"),
            "branch": raw.get("branch"),
            "created": raw.get("created"),
            "started": raw.get("started"),
            "finished": raw.get("finished"),
            "steps": steps,
        }

    def pipeline_logs(self, repo: str, pipeline_id: int) -> List[Dict[str, Any]]:
        """Per-step logs, decoded from the base64-per-line wire format."""
        raw = self._pipeline(repo, pipeline_id)
        repo_id = self.repo_id(repo)
        out: List[Dict[str, Any]] = []
        with httpx.Client(timeout=self._timeout) as client:
            for workflow in raw.get("workflows", []) or []:
                for step in workflow.get("children", []) or []:
                    step_id = step.get("id")
                    if not step_id:
                        continue
                    logs_response = client.get(
                        f"{self.wp_url}/api/repos/{repo_id}/logs/{pipeline_id}/{step_id}",
                        headers=self._wp_headers(),
                    )
                    lines: List[str] = []
                    if logs_response.status_code == 200:
                        for entry in logs_response.json() or []:
                            # v3.18 returns one JSON object per line
                            # ({id, step_id, line, data}) — not raw base64.
                            if isinstance(entry, dict):
                                data = entry.get("data", "")
                            else:
                                data = entry
                            if not isinstance(data, str):
                                lines.append(str(data))
                                continue
                            try:
                                lines.append(
                                    base64.b64decode(data).decode("utf-8", "replace").rstrip("\n")
                                )
                            except Exception:
                                lines.append(data)
                    out.append(
                        {
                            "step": step.get("name"),
                            "state": step.get("state"),
                            "exit_code": step.get("exit_code"),
                            "lines": lines,
                        }
                    )
        return out

    def run_content(
        self,
        repo: str,
        content: str,
        variables: Optional[Dict[str, str]] = None,
        branch: str = "main",
        timeout: float = 600.0,
    ) -> Dict[str, Any]:
        """Push a pipeline file to the repo, trigger it, and block until it
        finishes. Returns status + console output. Used by the evolve
        evaluators and the CLI run command (parity with the old
        execute_command contract).
        Callers in async context should wrap this in asyncio.to_thread.
        """
        self.forge_create_repo(repo.split("/", 1)[1])
        self.forge_upsert_file(repo, ".woodpecker.yml", content)
        triggered = self.trigger(repo, branch, variables)
        pipeline_id = triggered["pipeline_id"]
        deadline = time.time() + timeout
        status = None
        while time.time() < deadline:
            status = self.pipeline_status(repo, pipeline_id)
            if status["status"] in ("success", "failure", "error", "killed", "declined"):
                break
            time.sleep(3)
        if status is None:
            raise TimeoutError(f"pipeline {pipeline_id} on {repo} did not finish within {timeout}s")
        logs = self.pipeline_logs(repo, pipeline_id)
        console = "\n".join(line for step in logs for line in step["lines"])
        duration = None
        if status.get("started") and status.get("finished"):
            duration = float(status["finished"] - status["started"])
        return {
            "success": status["status"] == "success",
            "status": status["status"],
            "pipeline_id": pipeline_id,
            "duration_seconds": duration,
            "steps": status["steps"],
            "console": console,
        }

    def list_pipelines(self, repo: str, limit: int = 10) -> List[Dict[str, Any]]:
        repo_id = self.repo_id(repo)
        with httpx.Client(timeout=self._timeout) as client:
            response = client.get(
                f"{self.wp_url}/api/repos/{repo_id}/pipelines",
                params={"limit": limit},
                headers=self._wp_headers(),
            )
            response.raise_for_status()
            return [
                {
                    "pipeline_id": p.get("number"),
                    "number": p.get("number"),
                    "status": p.get("status"),
                    "event": p.get("event"),
                    "branch": p.get("branch"),
                    "created": p.get("created"),
                }
                for p in response.json()
            ]

    def _pipeline(self, repo: str, pipeline_id: int) -> Dict[str, Any]:
        repo_id = self.repo_id(repo)
        with httpx.Client(timeout=self._timeout) as client:
            response = client.get(
                f"{self.wp_url}/api/repos/{repo_id}/pipelines/{pipeline_id}",
                headers=self._wp_headers(),
            )
            response.raise_for_status()
            return response.json()
