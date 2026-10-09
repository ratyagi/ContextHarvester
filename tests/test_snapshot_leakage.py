"""PRD risk: 'Repo snapshotting is subtly wrong and leaks the fix'. The gold-patch files must differ
from their post-fix contents in the indexed snapshot. This is the test to point at for
'How do you know the fix wasn't already in your index?'."""
import pytest

from context_harvester.files import list_files
from context_harvester.snapshot import (
    LeakageError, verify_fix_absent_blobs, verify_fix_absent_patch, worktree, git,
)
from conftest import sh


def test_indexed_snapshot_does_not_contain_fix(fixrepo):
    repo, a, b = fixrepo
    gold = ["pkg/parser.py"]
    verify_fix_absent_blobs(repo, a, b, gold)
    with worktree(repo, a) as wt:
        indexed = {f.path: f.text for f in list_files(wt)}
    post_fix = sh(repo, "show", f"{b}:pkg/parser.py")
    assert indexed["pkg/parser.py"] != post_fix          # gold file differs from post-fix contents
    assert "assert len(parts) == 3" not in indexed["pkg/parser.py"]  # the fix itself is absent
    assert "BUG: no validation" in indexed["pkg/parser.py"]


def test_indexing_the_fix_commit_is_caught(fixrepo):
    repo, a, b = fixrepo
    with pytest.raises(LeakageError):
        verify_fix_absent_blobs(repo, b, b, ["pkg/parser.py"])          # snapshot == fix
    c = sh(repo, "commit-tree", f"{b}^{{tree}}", "-p", b, "-m", "later")  # snapshot after the fix
    with pytest.raises(LeakageError):
        verify_fix_absent_blobs(repo, c, b, ["pkg/parser.py"])


def test_gold_patch_must_apply_forward_only(fixrepo):
    repo, a, b = fixrepo
    patch = sh(repo, "diff", a, b, "--", "pkg/parser.py") + "\n"
    with worktree(repo, a) as wt:
        verify_fix_absent_patch(wt, patch)
    with worktree(repo, b) as wt:
        with pytest.raises(LeakageError):
            verify_fix_absent_patch(wt, patch)


def test_worktree_is_removed(fixrepo):
    repo, a, _ = fixrepo
    with worktree(repo, a) as wt:
        assert wt.exists()
    assert not wt.exists()
    assert "wt" not in git(repo, "worktree", "list").stdout.replace(str(repo), "")
