"""BM25 over file contents and paths. The baseline to beat (PRD: Lexical)."""
from __future__ import annotations

import re

from rank_bm25 import BM25Okapi

from .files import RepoFile

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_PARTS = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")
STOP = {
    "self", "def", "return", "import", "from", "the", "and", "for", "not", "none", "true",
    "false", "class", "if", "else", "elif", "in", "is", "of", "to", "as", "with", "try",
    "except", "pass", "raise", "lambda", "or", "an", "it", "this", "that", "be", "on",
}


def tokenize(text: str) -> list[str]:
    out: list[str] = []
    for word in _IDENT.findall(text):
        pieces = [p.lower() for p in _PARTS.findall(word) if len(p) > 1]
        out.extend(pieces)
        if len(pieces) > 1:  # keep the compound so exact identifiers match strongly
            out.append(word.lower())
    return [t for t in out if t not in STOP]


class LexicalIndex:
    def __init__(self, files: list[RepoFile]):
        self.paths = [f.path for f in files]
        docs = [tokenize(f.path.replace("/", " ").replace(".", " ")) * 2 + tokenize(f.text) for f in files]
        self._bm25 = BM25Okapi([d or ["_empty_"] for d in docs])

    def search(self, query: str, k: int = 100) -> list[tuple[str, float]]:
        toks = tokenize(query)
        if not toks:
            return []
        scores = self._bm25.get_scores(toks)
        order = sorted(range(len(scores)), key=lambda i: (-scores[i], self.paths[i]))
        return [(self.paths[i], float(scores[i])) for i in order[:k] if scores[i] > 0]
