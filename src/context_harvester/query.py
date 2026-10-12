"""Query construction. 'full' sends the whole issue; 'focused' emphasizes the title and code identifiers.

Experimental (dev-only until validated); the default stays 'full' so committed results are reproducible.
"""
from __future__ import annotations

import re

DOTTED = re.compile(r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\b")
CAMEL = re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b")
SNAKE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
CALL = re.compile(r"\b([A-Za-z_]\w{2,})\(")
EXC = re.compile(r"\b\w+(?:Error|Exception|Warning)\b")
NOISE = {"self.assertEqual", "e.g", "i.e", "etc.", "Python", "Traceback"}


def identifiers(text: str, limit: int = 60) -> list[str]:
    seen: dict[str, None] = {}
    for rx in (EXC, CAMEL, SNAKE, DOTTED, CALL):
        for m in rx.finditer(text):
            tok = m.group(1) if rx is CALL else m.group(0)
            if tok not in NOISE and len(tok) > 2:
                seen.setdefault(tok)
    return list(seen)[:limit]


def focus_query(text: str) -> tuple[str, str]:
    """Returns (bm25_query, embedding_query)."""
    lines = [l for l in text.splitlines() if l.strip()]
    title = lines[0].strip() if lines else ""
    ids = " ".join(identifiers(text))
    bm25 = f"{title} {title} {ids} {ids} {text}"
    embed = f"{title}\n{' '.join(identifiers(text, 30))}\n{text[:800]}"
    return bm25, embed
