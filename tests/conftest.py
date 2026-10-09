"""Test helpers: synthetic git repos and an offline hashing embedder (tests only; the product uses MiniLM)."""
from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

import numpy as np
import pytest


class HashEmbedder:
    name = "test-hash"

    def encode(self, texts):
        out = np.zeros((len(texts), 128), dtype="float32")
        for i, t in enumerate(texts):
            for w in re.findall(r"[a-z]+", t.lower()):
                out[i, int(hashlib.md5(w.encode()).hexdigest(), 16) % 128] += 1
        n = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(n == 0, 1, n)


def sh(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def embedder():
    return HashEmbedder()


@pytest.fixture
def fixrepo(tmp_path):
    """A repo with a buggy commit A and a fix commit B touching pkg/parser.py. Returns (path, A, B)."""
    r = tmp_path / "repo"
    (r / "pkg").mkdir(parents=True)
    sh(tmp_path, "init", "-q", str(r))
    sh(r, "config", "user.email", "t@t")
    sh(r, "config", "user.name", "t")
    (r / "pkg/__init__.py").write_text("")
    (r / "pkg/parser.py").write_text("from pkg.tokens import Token\n\ndef parse_date(s):\n    return s.split('-')  # BUG: no validation\n")
    (r / "pkg/tokens.py").write_text("class Token:\n    kind = 'date'\n")
    (r / "pkg/render.py").write_text("def render_page(html):\n    return html.strip()\n")
    (r / "CHANGELOG.md").write_text("# changes\n")
    sh(r, "add", "-A"); sh(r, "commit", "-qm", "A")
    a = sh(r, "rev-parse", "HEAD")
    (r / "pkg/parser.py").write_text("from pkg.tokens import Token\n\ndef parse_date(s):\n    parts = s.split('-')\n    assert len(parts) == 3\n    return parts\n")
    (r / "CHANGELOG.md").write_text("# changes\n- fix parse_date\n")
    sh(r, "add", "-A"); sh(r, "commit", "-qm", "B fix")
    b = sh(r, "rev-parse", "HEAD")
    return r, a, b
