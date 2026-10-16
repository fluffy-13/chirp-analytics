"""Keep small files on their own git branch (state, previews) without touching the checkout.

Uses git plumbing against a throwaway index, so the working tree and `main` are never
modified. Concurrent writers are handled by retrying on a non-fast-forward push.
"""
import logging
import os
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent
BOT_ENV = {"GIT_AUTHOR_NAME": "chirp-bot", "GIT_AUTHOR_EMAIL": "chirp-bot@users.noreply.github.com",
           "GIT_COMMITTER_NAME": "chirp-bot",
           "GIT_COMMITTER_EMAIL": "chirp-bot@users.noreply.github.com"}


class GitBranchStore:
    def __init__(self, branch, remote="origin", repo=ROOT):
        self.branch, self.remote, self.repo = branch, remote, Path(repo)
        self.ref = f"refs/remotes/{remote}/{branch}"

    def _git(self, *args, input=None, env=None, check=True):
        full_env = {**os.environ, **BOT_ENV, **(env or {})}
        res = subprocess.run(["git", "-C", str(self.repo), *args], input=input, env=full_env,
                             capture_output=True, check=False)
        if check and res.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {res.stderr.decode()[:300]}")
        return res

    def fetch(self):
        res = self._git("fetch", "-q", self.remote, f"+refs/heads/{self.branch}:{self.ref}",
                        check=False)
        return res.returncode == 0

    def _head(self):
        res = self._git("rev-parse", "-q", "--verify", self.ref, check=False)
        return res.stdout.decode().strip() or None

    def read(self, path, fetch=True):
        if fetch:
            self.fetch()
        if not self._head():
            return None
        res = self._git("show", f"{self.ref}:{path}", check=False)
        return res.stdout if res.returncode == 0 else None

    def write(self, files, message, retries=4):
        """files: {path: bytes}. Adds/overwrites those paths on the branch and pushes."""
        for attempt in range(1, retries + 1):
            self.fetch()
            parent = self._head()
            with tempfile.TemporaryDirectory() as tmp:
                env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
                if parent:
                    self._git("read-tree", parent, env=env)
                else:
                    self._git("read-tree", "--empty", env=env)
                for path, data in files.items():
                    blob = self._git("hash-object", "-w", "--stdin", input=data).stdout.decode().strip()
                    self._git("update-index", "--add", "--cacheinfo", f"100644,{blob},{path}", env=env)
                tree = self._git("write-tree", env=env).stdout.decode().strip()
            args = ["commit-tree", tree, "-m", message] + (["-p", parent] if parent else [])
            commit = self._git(*args).stdout.decode().strip()
            push = self._git("push", "-q", self.remote, f"{commit}:refs/heads/{self.branch}",
                             check=False)
            if push.returncode == 0:
                self._git("update-ref", self.ref, commit)
                return commit
            log.warning("Push to %s rejected (attempt %s): %s", self.branch, attempt,
                        push.stderr.decode()[:200])
        raise RuntimeError(f"Could not push to branch {self.branch}")


class LocalStore:
    """Same interface, plain files (local runs and tests)."""

    def __init__(self, directory):
        self.dir = Path(directory)

    def read(self, path, fetch=True):
        p = self.dir / path
        return p.read_bytes() if p.exists() else None

    def write(self, files, message=""):
        for path, data in files.items():
            p = self.dir / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        return "local"


def default_store(branch, local_dir):
    """Git branch store on GitHub Actions, plain files everywhere else."""
    if os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("STORE_BACKEND") != "local":
        return GitBranchStore(branch)
    return LocalStore(local_dir)
