"""Unit tests for MiladyCI.import_context git machinery.

Exercises the full path against a LOCAL bare git remote (simulating forge):
safe untar -> single-commit snapshot -> force-push -> ref guard -> kaniko
inject + kubeconfig secret attach. No network, no real forge/woodpecker.

Run: python3 -m unittest woodpecker.service_import_test
"""

import io
import os
import subprocess
import sys
import tarfile
import tempfile
import types
import unittest

# The woodpecker package imports httpx at module load (used only inside
# client methods). Stub it so the test can import service.py on a host
# without httpx; no real WoodpeckerClient is ever constructed.
if "httpx" not in sys.modules:
    _httpx = types.ModuleType("httpx")
    _httpx.Timeout = lambda *a, **k: None
    _httpx.Client = lambda *a, **k: (_ for _ in ()).throw(NotImplementedError)
    sys.modules["httpx"] = _httpx

from woodpecker.service import MiladyCI  # noqa: E402


def git(cwd, *args):
    r = subprocess.run(["git"] + list(args), cwd=cwd,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {args}: {r.stderr}")
    return r.stdout.strip()


class FakeClient:
    """Stands in for WoodpeckerClient: only the methods import_context uses."""

    forge_user = "milady"

    def __init__(self, bare):
        self.bare = bare
        self.repos = set()
        self.secrets = []

    def forge_create_repo(self, name):
        self.repos.add(name)

    def forge_remote(self, repo):
        return self.bare

    def repo_secret_set(self, repo, name, value):
        self.secrets.append((name, value))


def make_tar(tree):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for rel, body in tree.items():
            info = tarfile.TarInfo(rel)
            data = body.encode() if isinstance(body, str) else body
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def seed_bare(bare):
    """Give the bare repo a main branch with an initial commit (auto-init sim)."""
    with tempfile.TemporaryDirectory() as d:
        git(d, "init", "-q", "-b", "main")
        with open(os.path.join(d, "README.md"), "w") as f:
            f.write("seed")
        git(d, "add", "-A")
        git(d, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed")
        git(d, "remote", "add", "origin", bare)
        git(d, "push", "-q", "-u", "origin", "main")


class ImportContextTest(unittest.TestCase):
    def _import(self, tree, name="dice-test"):
        bare = os.path.join(self.tmp, "forge.git")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", bare], check=True)
        seed_bare(bare)
        fake = FakeClient(bare)
        ci = MiladyCI()
        ci._client = fake
        os.environ["MILADY_KUBECONFIG_CONTENT"] = "fake-kubeconfig"
        res = ci.import_context(name, make_tar(tree))
        self.tmp = os.path.dirname(bare)  # keep ref for inspection helper
        self.fake = fake
        return res

    def _clone_entries(self, bare):
        with tempfile.TemporaryDirectory() as d:
            git(d, "clone", "-q", bare, os.path.join(d, "c"))
            c = os.path.join(d, "c")
            out = subprocess.run(["git", "ls-tree", "-r", "--name-only", "HEAD"],
                                 cwd=c, capture_output=True, text=True).stdout
            return set(out.split())

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="milady-import-test-")
        self.addCleanup(self._rm, self.tmp)

    @staticmethod
    def _rm(d):
        subprocess.run(["rm", "-rf", d], check=True)

    def test_kaniko_context_import(self):
        bare = os.path.join(self.tmp, "forge.git")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", bare], check=True)
        seed_bare(bare)
        fake = FakeClient(bare)
        ci = MiladyCI()
        ci._client = fake
        os.environ["MILADY_KUBECONFIG_CONTENT"] = "fake-kubeconfig"

        res = ci.import_context("dice-test", make_tar({
            "Dockerfile": "FROM scratch\n",
            "src/app.py": "print('hi')\n",
        }))

        self.assertTrue(res["success"])
        self.assertEqual(res["name"], "dice-test")
        self.assertEqual(res["branch"], "main")
        self.assertTrue(res["kaniko"], "Dockerfile tree should get kaniko yml")
        self.assertTrue(res["kubeconfig_secret"])
        self.assertTrue(res["commit"])
        # forge_remote got the repo + secret recorded
        self.assertEqual(("kubeconfig_content", "fake-kubeconfig"), fake.secrets[0])
        # landed tree: source + injected kaniko .woodpecker.yml
        entries = self._clone_entries(bare)
        self.assertIn("Dockerfile", entries)
        self.assertIn("src/app.py", entries)
        self.assertIn(".woodpecker.yml", entries)
        # ref guard held: remote HEAD == reported commit
        with tempfile.TemporaryDirectory() as d:
            git(d, "clone", "-q", bare, os.path.join(d, "c"))
            head = git(os.path.join(d, "c"), "rev-parse", "HEAD")
            self.assertEqual(head, res["commit"])

    def test_non_docker_context_no_inject(self):
        bare = os.path.join(self.tmp, "forge2.git")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", bare], check=True)
        seed_bare(bare)
        fake = FakeClient(bare)
        ci = MiladyCI()
        ci._client = fake
        res = ci.import_context("plain", make_tar({"data.txt": "x"}))
        self.assertFalse(res["kaniko"])
        entries = self._clone_entries(bare)
        self.assertIn("data.txt", entries)
        self.assertNotIn(".woodpecker.yml", entries)

    def test_unsafe_tar_rejected(self):
        bare = os.path.join(self.tmp, "forge3.git")
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", bare], check=True)
        seed_bare(bare)
        fake = FakeClient(bare)
        ci = MiladyCI()
        ci._client = fake
        evil = io.BytesIO()
        with tarfile.open(fileobj=evil, mode="w:gz") as tf:
            info = tarfile.TarInfo("../escape.txt")
            info.size = 4
            tf.addfile(info, io.BytesIO(b"evil"))
        with self.assertRaises(ValueError):
            ci.import_context("bad", evil.getvalue())


if __name__ == "__main__":
    unittest.main()
