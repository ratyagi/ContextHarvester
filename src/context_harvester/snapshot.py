"""Snapshot a repo at the commit immediately before the fix, via git worktree (PRD: Snapshot).

Everything downstream indexes the snapshot, never current main. verify_* are the leakage guards.
"""
from __future__ import annotations

import contextlib
import shutil
import subprocess
import tempfile
from pathlib import Path


class LeakageError(RuntimeError):
    """The fix is present in the snapshot. Every number computed from it would be meaningless."""


def git(repo: Path, *args: str, check: bool = True, input: str | None = None) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, input=input)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r


def ensure_clone(url: str, dest: Path) -> Path:
    """Blobless clone (fast, cold): file contents are fetched only for commits we check out."""
    dest = Path(dest)
    if (dest / ".git").exists() or (dest / "HEAD").exists():
        git(dest, "fetch", "--quiet", "origin", "+refs/heads/*:refs/remotes/origin/*", check=False)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "--quiet", "--filter=blob:none", "--no-checkout", url, str(dest)], check=True)
    return dest


def ensure_commit(repo: Path, sha: str) -> None:
    if git(repo, "cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode != 0:
        git(repo, "fetch", "--quiet", "origin", sha, check=False)
        git(repo, "cat-file", "-e", f"{sha}^{{commit}}")


def default_branch_head(repo: Path) -> str:
    r = git(repo, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", check=False)
    ref = r.stdout.strip() or "refs/remotes/origin/HEAD"
    return git(repo, "rev-parse", ref).stdout.strip()


@contextlib.contextmanager
def worktree(repo: Path, commit: str):
    """Detached worktree at `commit`, removed on exit."""
    ensure_commit(repo, commit)
    tmp = Path(tempfile.mkdtemp(prefix="ch-wt-"))
    path = tmp / "wt"
    git(repo, "worktree", "add", "--quiet", "--detach", str(path), commit)
    try:
        yield path
    finally:
        git(repo, "worktree", "remove", "--force", str(path), check=False)
        shutil.rmtree(tmp, ignore_errors=True)


def verify_fix_absent_blobs(repo: Path, base: str, fix: str, gold_files: list[str]) -> None:
    """For each gold file present at `base`, its blob must differ from the post-fix blob.

    Also requires the fix commit not to be an ancestor of the snapshot. Raises LeakageError otherwise.
    """
    if base == fix or git(repo, "merge-base", "--is-ancestor", fix, base, check=False).returncode == 0:
        raise LeakageError(f"fix commit {fix[:10]} is contained in snapshot {base[:10]}")
    for f in gold_files:
        pre = git(repo, "rev-parse", "--verify", "--quiet", f"{base}:{f}", check=False)
        if pre.returncode != 0:
            continue  # file added by the fix: absent from the snapshot, cannot leak
        post = git(repo, "rev-parse", "--verify", "--quiet", f"{fix}:{f}", check=False)
        if post.returncode == 0 and pre.stdout.strip() == post.stdout.strip():
            raise LeakageError(f"{f} is identical at snapshot and post-fix: fix not isolated")


def verify_fix_absent_patch(wt: Path, patch: str) -> None:
    """The gold patch must apply cleanly forward on the snapshot, and not in reverse (SWE-bench path)."""
    fwd = git(wt, "apply", "--check", "-", check=False, input=patch)
    if fwd.returncode != 0:
        raise LeakageError(f"gold patch does not apply forward to snapshot: {fwd.stderr.strip()[:200]}")
    rev = git(wt, "apply", "--check", "--reverse", "-", check=False, input=patch)
    if rev.returncode == 0:
        raise LeakageError("gold patch applies in reverse: the fix is already in the snapshot")
