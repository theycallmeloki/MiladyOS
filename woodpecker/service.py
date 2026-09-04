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
import os
import shutil
import tempfile
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



# Kaniko build pipeline injected into an imported build-context repo so it is
# runnable via job_run(name, {DESTINATION: ...}). Canonical source:
# woodpecker/kaniko-build.yml (kept in sync). The repo itself is the build
# context (Dockerfile at root + .dockerignore); kaniko-submit builds/pushes.
KANIKO_BUILD_YML = """# MiladyOS kaniko-build pipeline — the agent CI/CD path into the build fabric.
#
# Runs kaniko-submit (deploy/kaniko/kaniko-submit.py) against the CURRENT
# repo checkout (CI_WORKSPACE): the pipeline repo itself is the build
# context (Dockerfile at root + .dockerignore respected). The build runs as
# a KanikoBuild pod in the sandman namespace and lands in
# miladyosregistry.transparentlyrotatableproxy.site.
#
# Trigger (deliberate only — nothing auto-runs):
#   POST /api/repos/{repo_id}/pipelines
#     variables: { "DESTINATION": "miladyosregistry.../<image>:<tag>" }
#     optional:  KANIKO_TIMEOUT (seconds)
#
# Secrets (repo-level): kubeconfig_content — cluster kubeconfig for the
# kaniko submit. v3.18 injects via `from_secret` under environment (the
# legacy `secrets:` step list is gone).
#
# Evolvable region (EVOLVE-BLOCK, below in the kaniko-build step): the
# KANIKO_TIMEOUT default and the kaniko-submit flags. Everything else in this
# file is fixed machinery (kubeconfig write, from_secret binding, registry
# path) — AlphaEvolve mechanically discards any edit outside the markers.
# Step image: miladyosregistry.../kaniko-submit:<tag> (python3 + kubectl +
# kaniko-submit.py at /app). Registry-skip guard lives inside the helper
# (tag already present -> exit 0, nothing rebuilt).
when:
  - event: manual

steps:
  kaniko-build:
    image: miladyosregistry.transparentlyrotatableproxy.site/kaniko-submit:2
    environment:
      KUBECONFIG_CONTENT:
        from_secret: kubeconfig_content
    commands:
      - |
        set -e
        # woodpecker steps are separate containers: write the kubeconfig into
        # the SHARED workspace, not /root (which resets between steps).
        mkdir -p "$CI_WORKSPACE/.kube"
        printf '%s' "$KUBECONFIG_CONTENT" > "$CI_WORKSPACE/.kube/config"
        chmod 600 "$CI_WORKSPACE/.kube/config"
        export KUBECONFIG="$CI_WORKSPACE/.kube/config"
        # EVOLVE-BLOCK-START: {"type": "kaniko-submit", "optimization_targets": ["reliability", "resources"]}
        if [ -n "$KANIKO_TIMEOUT" ]; then TIMEOUT="$KANIKO_TIMEOUT"; else TIMEOUT=1500; fi
        python3 /app/kaniko-submit.py --context "$CI_WORKSPACE" --destination "$DESTINATION" --timeout-seconds "$TIMEOUT"
        # EVOLVE-BLOCK-END
"""


def _kaniko_template() -> str:
    """Return the kaniko .woodpecker.yml body (env path override, else embedded)."""
    path = os.environ.get("MILADY_KANIKO_TEMPLATE")
    if path:
        try:
            return open(path).read()
        except OSError as e:
            raise RuntimeError(f"cannot read MILADY_KANIKO_TEMPLATE {path}: {e}") from e
    return KANIKO_BUILD_YML


def _kubeconfig_source() -> Optional[str]:
    """Kubeconfig content to attach as the repo secret, or None if unset.

    Prefers MILADY_KUBECONFIG_CONTENT (env), else reads MILADY_KUBECONFIG (a
    path). Neither is baked into the public image — set at container runtime.
    """
    if os.environ.get("MILADY_KUBECONFIG_CONTENT"):
        return os.environ["MILADY_KUBECONFIG_CONTENT"]
    path = os.environ.get("MILADY_KUBECONFIG")
    if path:
        try:
            return open(path).read()
        except OSError:
            return None
    return None


def _untar(data: bytes, dest: str) -> None:
    """Safely extract a gzip tar into dest (rejects traversal; files + symlinks)."""
    import io
    import shutil as _sh
    import tarfile

    real_dest = os.path.realpath(dest)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tf:
        for member in tf:
            name = member.name.lstrip("/")
            if not name or "\\" in name:
                continue
            parts = name.split("/")
            if ".." in parts:
                raise ValueError(f"unsafe archive path: {member.name!r}")
            target = os.path.realpath(os.path.join(dest, *parts))
            if target != real_dest and not target.startswith(real_dest + os.sep):
                raise ValueError(f"archive path escapes root: {member.name!r}")
            if member.isdir():
                os.makedirs(target, exist_ok=True)
            elif member.issym():
                os.makedirs(os.path.dirname(target), exist_ok=True)
                if os.path.lexists(target):
                    os.remove(target)
                os.symlink(member.linkname, target)
            elif member.isfile():
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as out:
                    src = tf.extractfile(member)
                    _sh.copyfileobj(src, out)  # type: ignore[arg-type]
                    if src is not None:
                        src.close()


def _git_env() -> Dict[str, str]:
    import copy as _c
    env = _c.copy(os.environ)
    env.update({
        "GIT_AUTHOR_NAME": "MiladyCI",
        "GIT_AUTHOR_EMAIL": "milady@miladyos.local",
        "GIT_COMMITTER_NAME": "MiladyCI",
        "GIT_COMMITTER_EMAIL": "milady@miladyos.local",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "echo",
    })
    return env


def _git_run(args, cwd):
    import subprocess
    res = subprocess.run(args, cwd=cwd, env=_git_env(),
                         capture_output=True, text=True)
    return res


def _git_snapshot(dir_path: str, label: str) -> str:
    """Turn dir into a fresh single-commit repo on main; returns the commit sha."""
    import subprocess
    init = _git_run(["git", "init", "-q", "-b", "main"], dir_path)
    if init.returncode != 0:
        _git_run(["git", "init", "-q"], dir_path)
        _git_run(["git", "symbolic-ref", "HEAD", "refs/heads/main"], dir_path)
    if _git_run(["git", "add", "-A"], dir_path).returncode != 0:
        raise RuntimeError("git add failed during import")
    commit = _git_run(["git", "commit", "-q", "-m", f"milady import: {label}"], dir_path)
    if commit.returncode != 0:
        raise RuntimeError(f"git commit failed during import: {commit.stderr.strip()}")
    head = _git_run(["git", "rev-parse", "HEAD"], dir_path)
    return head.stdout.strip()


def _git_push(dir_path: str, remote: str) -> bool:
    """Force-push main to remote; returns True iff the remote ref == local head."""
    import subprocess
    _git_run(["git", "remote", "remove", "origin"], dir_path)
    add = _git_run(["git", "remote", "add", "origin", remote], dir_path)
    if add.returncode != 0:
        raise RuntimeError("git remote add failed during import")
    push = _git_run(["git", "push", "-q", "-f", "origin", "main"], dir_path)
    if push.returncode != 0:
        raise RuntimeError(f"git push failed: {push.stderr.strip()}")
    local = _git_run(["git", "rev-parse", "HEAD"], dir_path).stdout.strip()
    ls = _git_run(["git", "ls-remote", "origin", "refs/heads/main"], dir_path)
    return local in ls.stdout


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


    def import_context(self, name: str, tar_gz: bytes) -> Dict[str, Any]:
        """Land a slurped build-context tarball as a reusable job repo.

        Unpacks the gzip tar into ``milady/<name>`` via a single git commit
        (ref-checked after push), and, when the tree is a kaniko build context
        (Dockerfile present, no existing .woodpecker.yml), injects the kaniko
        pipeline so ``job_run(name, {DESTINATION: ...})`` builds it. Returns
        the landed repo + commit sha.
        """
        import re
        name = name.strip().strip("/")
        if not name or "/" in name:
            raise ValueError("job name must be a bare name (no '/')")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name) or name.startswith("."):
            raise ValueError(f"invalid job name: {name!r}")

        client = self.client
        repo = _resolve_repo(name, client)
        client.forge_create_repo(repo.split("/", 1)[1])

        work = tempfile.mkdtemp(prefix="milady-import-")
        try:
            _untar(tar_gz, work)
            injected = False
            if not os.path.exists(os.path.join(work, ".woodpecker.yml")) and \
                    os.path.exists(os.path.join(work, "Dockerfile")):
                with open(os.path.join(work, ".woodpecker.yml"), "w") as fh:
                    fh.write(_kaniko_template())
                injected = True
            commit = _git_snapshot(work, name)

            secret_source = _kubeconfig_source()
            secret_attached = False
            if secret_source:
                client.repo_secret_set(repo, "kubeconfig_content", secret_source)
                secret_attached = True

            if not _git_push(work, client.forge_remote(repo)):
                raise RuntimeError("git push ref mismatch after import")
        finally:
            shutil.rmtree(work, ignore_errors=True)

        return {
            "success": True,
            "status": "imported",
            "name": name,
            "repo": repo,
            "backend": self.backend_for(name),
            "commit": commit,
            "branch": "main",
            "kaniko": injected,
            "kubeconfig_secret": secret_attached,
        }

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
