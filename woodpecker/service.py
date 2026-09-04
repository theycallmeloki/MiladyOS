"""MiladyCI — the gitea/woodpecker-free facade milady drives.

milady addresses *jobs* by a logical name plus variables. Everything else —
forge repo provisioning, the woodpecker yml envelope, activation, triggering,
status/logs — is owned here so milady never names a forge repo, a pipeline id,
or pastes woodpecker-specific framing.

Conventions
----------
- A bare job name resolves to the ``milady/<name>`` forge repo; ``owner/name``
  is used as-is (cross-owner escape hatch). ``milady/`` is prepended on
  milady's behalf.
- milady writes *plain steps yml* (``steps:`` → ``image`` + ``commands``).
  If it lacks the ``when: event: manual`` gate woodpecker requires for manual
  triggers, this layer injects it — she shouldn't need to know that quirk.
- Backend is catalog-driven and transparent, never content-sniffed. The
  seeded *builder* jobs (``kaniko-build``, ``build-bus``) are kaniko; any
  other job is a node-agent job. ``KNOWN_JOBS`` is the single source of that
  truth.
"""

import json
import time
from typing import Any, Dict, List, Optional

from .woodpecker_client import WoodpeckerClient

# Logical job name -> forge repo short name + execution backend.
# These are the pre-seeded builder jobs (milady/kaniko, milady/buildbus).
# Anything not listed is a node-agent job keyed by its own name.
KNOWN_JOBS: Dict[str, Dict[str, str]] = {
    "kaniko-build": {
        "repo": "kaniko",
        "backend": "kaniko",
        "description": "Build the current repo checkout into a registry image (kaniko-submit).",
    },
    "build-bus": {
        "repo": "buildbus",
        "backend": "kaniko",
        "description": "Build a sandman-mirrored repo as an image; git-ops promote on PROMOTE=1.",
    },
}

# Woodpecker manual-trigger gate injected when milady's plain steps yml omits
# it (mirrors the format startup.sh / the re-seeded pipelines use).
_MANUAL_GATE = "when:\n  event: manual\n"


def _known(name: str) -> Optional[Dict[str, str]]:
    """Return the KNOWN_JOBS entry for a logical name (exact match), else None."""
    return KNOWN_JOBS.get(name)


def _resolve_repo(name: str, client: WoodpeckerClient) -> str:
    """Bare name -> milady/<name>; owner/name passed through."""
    name = name.strip().strip("/")
    if not name:
        raise ValueError("job name is required")
    if "/" in name:
        return name
    return f"{client.forge_user}/{name}"


def _enveloped(yml: str) -> str:
    """Inject the woodpecker manual-trigger gate if the plain yml lacks it.

    Only the minimal structural guarantee: a ``when:`` top-level block if
    missing, and that ``steps:`` is present. milady writes image/commands
    steps and should not need to know woodpecker requires a manual gate.
    """
    yml = yml.lstrip("\n")
    if not yml.lstrip().startswith("when:"):
        yml = _MANUAL_GATE + yml
    body = yml
    if "steps:" not in body:
        raise ValueError("job yml must define steps: (image + commands)")
    if not body.endswith("\n"):
        body += "\n"
    return body


def ad_hoc_pipeline(command: str, working_directory: str, session_id: str) -> str:
    """Ad-hoc one-shot pipeline for execute_command (mirrors the old contract)."""
    script = [
        'echo "==== COMMAND EXECUTION ===="',
        f'echo "COMMAND: {command}"',
        f'echo "SESSION: {session_id}"',
        'echo "WORKING DIR: $(pwd)"',
        'echo "TIME: $(date)"',
        'echo "==== OUTPUT ===="',
    ]
    if working_directory and working_directory != "/tmp/workspace":
        script.append(f'cd "{working_directory}" || true')
    script.extend(
        [
            f"{command} 2>&1; EC=$?",
            'echo "==== END OUTPUT ===="',
            'echo "EXIT CODE: $EC"',
            "exit $EC",
        ]
    )
    lines = "\n".join(f"      - {json.dumps(line)}" for line in script)
    return (
        "when:\n"
        "  event: manual\n"
        "steps:\n"
        "  execute:\n"
        "    image: alpine:3.20\n"
        "    commands:\n"
        f"{lines}\n"
    )


class MiladyCI:
    """High-level job surface over the local woodpecker/forgejo stack."""

    def __init__(self) -> None:
        self._client: Optional[WoodpeckerClient] = None

    @property
    def client(self) -> WoodpeckerClient:
        if self._client is None:
            self._client = WoodpeckerClient()
        return self._client

    # ---- repo resolution helpers -------------------------------------------

    def backend_for(self, name: str) -> str:
        """Execution backend for a logical job name (kaniko | node)."""
        entry = _known(name)
        if entry:
            return entry["backend"]
        return "node"

    def known_jobs(self) -> List[Dict[str, str]]:
        """Catalog of pre-seeded builder jobs (name, repo, backend)."""
        return [
            {"name": name, **entry, "repo": f"{self.client.forge_user}/{entry['repo']}"}
            for name, entry in KNOWN_JOBS.items()
        ]

    # ---- define / run ------------------------------------------------------

    def define(self, name: str, yml: str, backend: str = "auto") -> Dict[str, Any]:
        """Provision (or re-provision) a reusable job from plain steps yml.

        Writes the enveloped pipeline to ``milady/<name>`` and activates it.
        The ``backend`` argument is only informational for new jobs: known
        catalog jobs keep their catalog backend; new jobs are node-agent jobs.
        Does not run.
        """
        repo = _resolve_repo(name, self.client)
        body = _enveloped(yml)
        client = self.client
        client.forge_create_repo(repo.split("/", 1)[1])
        client.forge_upsert_file(repo, ".woodpecker.yml", body)
        client.repo_id(repo)  # idempotent activation
        return {
            "success": True,
            "status": "defined",
            "name": name,
            "repo": repo,
            "backend": self.backend_for(name),
            "bytes": len(body.encode("utf-8")),
        }

    def run(
        self,
        name: str,
        variables: Optional[Dict[str, str]] = None,
        branch: str = "main",
    ) -> Dict[str, Any]:
        """Trigger an existing job by logical name (no content required)."""
        repo = _resolve_repo(name, self.client)
        try:
            result = self.client.trigger(repo, branch, variables)
        except Exception as e:
            raise RuntimeError(
                f"could not run job {name!r} ({repo}): {e}. "
                f"Define it first with job_define(name, yml) — known jobs: "
                f"{', '.join(KNOWN_JOBS) or 'none'}"
            ) from e
        result["success"] = True
        result["backend"] = self.backend_for(name)
        return result

    # ---- status / logs / history -------------------------------------------

    def status(self, name: str, number: int) -> Dict[str, Any]:
        repo = _resolve_repo(name, self.client)
        result = self.client.pipeline_status(repo, int(number))
        result["success"] = True
        return result

    def logs(self, name: str, number: int) -> Dict[str, Any]:
        repo = _resolve_repo(name, self.client)
        steps = self.client.pipeline_logs(repo, int(number))
        return {"success": True, "pipeline_id": int(number), "steps": steps}

    def list_runs(self, name: str, limit: int = 10) -> Dict[str, Any]:
        repo = _resolve_repo(name, self.client)
        pipelines = self.client.list_pipelines(repo, int(limit))
        return {"success": True, "pipelines": pipelines}

    # ---- one-shot command execution (execute_command backend) --------------

    def execute(
        self,
        command: str,
        working_directory: str = "/tmp/workspace",
        session_id: str = "",
        timeout: float = 600.0,
    ) -> Dict[str, Any]:
        """Run a CLI command as a one-shot pipeline on the ad-hoc job.

        Returns the old execute_command contract (status + streamed console).
        """
        if not command:
            return {"command": command, "status": "ERROR",
                    "error": "command is required", "success": False}
        session_id = session_id or ""
        try:
            client = self.client
            repo = f"{client.forge_user}/ad-hoc"
            # run_content provisions the ad-hoc repo, pushes the yml, triggers
            # and blocks until the pipeline finishes.
            result = client.run_content(
                repo,
                ad_hoc_pipeline(command, working_directory, session_id),
                timeout=timeout,
            )
            console = result.get("console", "")
            ok = result.get("success", False)
            return {
                "command": command,
                "status": "SUCCESS" if ok else "FAILURE",
                "console_output": console,
                "success": ok,
                "pipeline_id": result.get("pipeline_id"),
                "session_id": session_id,
            }
        except Exception as e:
            return {"command": command, "status": "ERROR",
                    "error": str(e), "success": False}
