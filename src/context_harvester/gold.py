"""Gold sets, the incidental-file filter, and issue-text leakage detection (PRD: Protocol and leakage guards)."""
from __future__ import annotations

import re
from pathlib import PurePosixPath

DIFF_FILE = re.compile(r"^diff --git a/(\S+) b/(\S+)", re.M)
PLUS_FILE = re.compile(r"^\+\+\+ b/(\S+)", re.M)


def patch_files(patch: str) -> list[str]:
    """Files a unified diff touches (post-image path; pre-image for deletions)."""
    out: list[str] = []
    for a, b in DIFF_FILE.findall(patch):
        for p in (a, b):
            if p != "/dev/null" and p not in out:
                out.append(p)
    return out


# --- incidental-file filter. These rules are the ones stated in the README. ---
LOCKFILES = {
    "poetry.lock", "pipfile.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "uv.lock", "pdm.lock", "cargo.lock", "gemfile.lock", "composer.lock",
}
BUILD_META = {"setup.py", "setup.cfg", "pyproject.toml", "manifest.in", "tox.ini", "noxfile.py", "makefile"}
CHANGELOG_NAMES = {"changelog", "changes", "history", "news", "releases", "release_notes", "whatsnew"}
VERSION_FILES = {"_version.py", "version.py", "__version__.py"}
FIXTURE_DIRS = {"fixtures", "testdata", "test_data", "data", "snapshots", "__snapshots__", "baseline", "expected", "golden"}
DOC_EXT = {".md", ".rst", ".txt", ".ipynb"}


def incidental_reason(path: str) -> str | None:
    p = PurePosixPath(path)
    name, low = p.name.lower(), path.lower()
    parts = [x.lower() for x in p.parts[:-1]]
    stem = p.stem.lower()
    if name in LOCKFILES or name.endswith(".lock"):
        return "lockfile"
    if stem in CHANGELOG_NAMES or any(d in {"changelog.d", "newsfragments", "changes", "news", "release-notes"} for d in parts):
        return "changelog"
    if name in VERSION_FILES:
        return "version bump"
    if name in BUILD_META or low.startswith(".github/"):
        return "build/CI metadata"
    if name.endswith(("_pb2.py", "_pb2_grpc.py", ".min.js", ".min.css")) or "generated" in parts or ".generated." in name:
        return "generated code"
    if any(d in FIXTURE_DIRS for d in parts) and any(d in {"test", "tests", "testing"} or d.startswith("test") for d in parts):
        return "test fixture"
    if p.suffix.lower() in DOC_EXT and name != "readme.md" or "docs" in parts:
        return "documentation"
    return None


def is_test_file(path: str) -> bool:
    p = PurePosixPath(path)
    parts = [x.lower() for x in p.parts[:-1]]
    return p.name.startswith("test_") or p.name.endswith("_test.py") or p.name == "conftest.py" or any(
        d in {"test", "tests", "testing"} for d in parts
    )


def filter_gold(files: list[str]) -> list[str]:
    return [f for f in files if incidental_reason(f) is None]


# --- issue-text leakage ---
FENCE = re.compile(r"```.*?```", re.S)
DIFFISH = re.compile(r"^(diff --git|index [0-9a-f]+\.\.|@@ .* @@|\+\+\+ |--- a/)", re.M)


def strip_fix_text(issue: str) -> str:
    """Drop diff/patch blocks from the issue text. Tracebacks are kept; instances are flagged instead."""
    def drop_block(m: re.Match) -> str:
        return "" if DIFFISH.search(m.group(0)) or re.search(r"^[+-]\s", m.group(0), re.M) and "@@" in m.group(0) else m.group(0)

    text = FENCE.sub(drop_block, issue)
    return "\n".join(l for l in text.splitlines() if not DIFFISH.match(l))


def leaky_issue(issue: str, gold_files: list[str]) -> bool:
    """True when the issue contains a patch, or names a gold file by path (traceback, suggested fix)."""
    if DIFFISH.search(issue):
        return True
    for g in gold_files:
        if g.endswith(".py") and (g in issue or re.search(rf"(?<![\w/]){re.escape(PurePosixPath(g).name)}\b", issue)):
            return True
    return False
