"""The scalable paths must match the originals where they claim to, and be bounded where they claim to be."""
import random
import re

import numpy as np

from context_harvester.files import RepoFile, list_files
from context_harvester.lexical import STOP, _IDENT, _PARTS, tokenize
from context_harvester.pipeline import Params, Retriever
from context_harvester.semantic import CandidateSemantic, EmbedCache, chunk_key, chunk_text
from context_harvester.snapshot import worktree
from context_harvester.structural import _ast_imports, _regex_imports, build_graph
from context_harvester.tokens import count_tokens


def rf(path, text):
    return RepoFile(path, text, count_tokens(text))


def reference_tokenize(text):
    """The original, un-memoized implementation."""
    out = []
    for word in _IDENT.findall(text):
        pieces = [p.lower() for p in _PARTS.findall(word) if len(p) > 1]
        out.extend(pieces)
        if len(pieces) > 1:
            out.append(word.lower())
    return [t for t in out if t not in STOP]


def test_memoized_tokenize_is_identical_to_reference():
    rng = random.Random(0)
    words = ["parseDate", "parse_date_range", "HTTPServer", "x", "ValueError", "get2Items", "snake_case_name", "the", "self", "__init__"]
    for _ in range(50):
        text = " ".join(rng.choice(words) for _ in range(40))
        assert tokenize(text) == reference_tokenize(text)


SAMPLE = '''"""doc"""
import os, sys as system
import pkg.core
from pkg import util, helper as h
from . import sibling
from .sub.mod import (
    alpha,
    beta as b,
)
from ..up import thing
from pkg.core import *
def f():
    import lazy.inside
'''


def normalize(imports):
    out = set()
    for imp in imports:
        if imp[0] == "import":
            out.update(("import", n) for n in imp[1])
        else:
            _, level, module, names = imp
            out.add(("from", level, module, tuple(sorted(names))))
    return out


def test_regex_and_ast_extract_the_same_imports():
    assert normalize(_regex_imports(SAMPLE)) == normalize(_ast_imports(SAMPLE))


def test_regex_graph_matches_ast_graph_on_a_package():
    files = [
        rf("src/pkg/__init__.py", ""),
        rf("src/pkg/api.py", "from pkg.core import Engine\nfrom . import util\nfrom .util import helper\n"),
        rf("src/pkg/core.py", "import os\nfrom .sub.deep import (\n    A,\n    B,\n)\nclass Engine: pass\n"),
        rf("src/pkg/util.py", "def helper(): pass\n"),
        rf("src/pkg/sub/__init__.py", ""),
        rf("src/pkg/sub/deep.py", "A = B = 1\n"),
    ]
    a, r = build_graph(files, "ast"), build_graph(files, "regex")
    assert {k: set(v) for k, v in a.forward.items()} == {k: set(v) for k, v in r.forward.items()}
    assert {k: set(v) for k, v in a.reverse.items()} == {k: set(v) for k, v in r.reverse.items()}


class CountingEmbedder:
    name = "counting"

    def __init__(self, inner):
        self.inner, self.chunks = inner, 0

    def encode(self, texts):
        self.chunks += len(texts)
        return self.inner.encode(texts)


def test_candidate_cost_is_bounded_by_k_not_repo_size(embedder):
    big = "\n".join(f"def func_{i}(): return {i}" for i in range(400))  # many chunks per file
    files = [rf(f"m/f{i}.py", big + f"\nVALUE_{i} = {i}\n") for i in range(60)]
    emb = CountingEmbedder(embedder)
    cs = CandidateSemantic(files, emb, None, max_chunks=2)
    cands = [f"m/f{i}.py" for i in range(5)]
    out = cs.search("func_3 VALUE_3", cands, 10)
    assert {p for p, _ in out} <= set(cands)                 # never returns a non-candidate
    assert emb.chunks <= len(cands) * 2 + 1                  # candidates x chunk cap (+ the query), not 60 files
    assert cs.last_new_chunks == len(cands) * 2
    emb.chunks = 0
    cs.search("func_3", cands, 10)
    assert emb.chunks == 1                                   # second query: fully cached, only the query embeds


def test_cache_keys_for_different_chunk_caps_do_not_collide(tmp_path):
    f = rf("a.py", "x = 1\n")
    c = EmbedCache(tmp_path, "m")
    c.put(chunk_key(f, 8), np.ones((1, 4), dtype="float32"))
    c.put(chunk_key(f, 4), np.zeros((1, 4), dtype="float32"))
    c.flush()
    c2 = EmbedCache(tmp_path, "m")
    assert c2.get(chunk_key(f, 8)).sum() == 4 and c2.get(chunk_key(f, 4)).sum() == 0   # 43-char key not truncated into the 40-char one


def test_chunk_cap_limits_chunks():
    text = "\n".join("x = %d  # " % i + "y" * 80 for i in range(300))
    assert len(chunk_text("a.py", text, 2)) == 2 and len(chunk_text("a.py", text, 8)) == 8


def test_candidate_scope_end_to_end(fixrepo, embedder):
    repo, a, _ = fixrepo
    with worktree(repo, a) as wt:
        files = list_files(wt)
    r = Retriever(files, embedder, scope="candidates", candidate_k=3, candidate_chunks=2, graph_mode="regex")
    ranks = r.rankings("parse_date does not validate the date string", Params(), "x")
    assert ranks["full"][0] == "pkg/parser.py" and "pkg/tokens.py" in ranks["full"]
    assert r.cand_sem.last_total_chunks <= 3 * 2             # bounded by K x cap
