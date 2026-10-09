"""List the indexable files of a checked-out snapshot (Python first, per PRD non-goals)."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from .tokens import count_tokens

INDEXABLE_EXT = {".py"}
SKIP_DIRS = {
    ".git", "node_modules", "venv", ".venv", "build", "dist", "__pycache__",
    ".tox", ".eggs", "site-packages", ".mypy_cache", ".pytest_cache",
}
MAX_BYTES = 300_000


@dataclass(frozen=True)
class RepoFile:
    path: str  # posix, relative to repo root
    text: str
    tokens: int

    @property
    def key(self) -> str:
        return hashlib.sha1(f"{self.path}\0{self.text}".encode("utf-8", "ignore")).hexdigest()


def list_files(root: Path) -> list[RepoFile]:
    out: list[RepoFile] = []
    root = Path(root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.endswith(".egg-info"))
        for name in sorted(filenames):
            p = Path(dirpath) / name
            if p.suffix not in INDEXABLE_EXT or p.is_symlink():
                continue
            try:
                if p.stat().st_size > MAX_BYTES:
                    continue
                text = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            rel = p.relative_to(root).as_posix()
            out.append(RepoFile(rel, text, count_tokens(text)))
    return out
