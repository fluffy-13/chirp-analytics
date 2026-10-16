import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from git_store import GitBranchStore, LocalStore  # noqa: E402


def _git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def test_branch_store_roundtrip_without_touching_checkout(tmp_path):
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", str(remote))
    work = tmp_path / "work"
    _git(tmp_path, "init", "-q", "-b", "main", str(work))
    (work / "README.md").write_text("hi")
    _git(work, "add", ".")
    _git(work, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
    _git(work, "remote", "add", "origin", str(remote))
    _git(work, "push", "-q", "origin", "main")

    store = GitBranchStore("state", repo=work)
    assert store.read("posted.json") is None
    store.write({"posted.json": b'{"a": 1}'}, "first")
    store.write({"posted.json": b'{"a": 2}', "dir/x.txt": b"x"}, "second")
    assert store.read("posted.json") == b'{"a": 2}'
    assert store.read("dir/x.txt") == b"x"
    # a second clone sees the same data
    other = GitBranchStore("state", repo=work)
    assert other.read("posted.json") == b'{"a": 2}'
    # the checkout and main are untouched
    status = subprocess.run(["git", "-C", str(work), "status", "--porcelain"], capture_output=True)
    assert status.stdout == b""
    log = subprocess.run(["git", "-C", str(work), "log", "--oneline", "main"], capture_output=True)
    assert log.stdout.count(b"\n") == 1


def test_local_store(tmp_path):
    s = LocalStore(tmp_path)
    s.write({"a/b.json": b"1"})
    assert s.read("a/b.json") == b"1" and s.read("missing") is None


def test_read_dir_both_backends(tmp_path):
    import subprocess
    from git_store import GitBranchStore, LocalStore
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", str(remote)], check=True)
    files = {"games/1.json": b'{"a":1}', "games/2.json": b"x\ny", "other.txt": b"no"}
    for store in (GitBranchStore("state", repo=repo), LocalStore(tmp_path / "local")):
        store.write(files, "seed")
        got = store.read_dir("games")
        assert got == {"games/1.json": b'{"a":1}', "games/2.json": b"x\ny"}
