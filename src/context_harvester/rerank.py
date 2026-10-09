"""Final stage: one LLM pass over a short list. Drops files, writes one-line reasons, stops at the token budget.

If no provider is configured or all fail, the fused ranking is returned with signal-based reasons
(PRD cut list item 2: fusion output is already a ranked list).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .files import RepoFile
from .llm import FallbackLLM, LLMError

SHORTLIST = 30
SNIPPET_CHARS = 700
DEFS = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+(\w+)", re.M)


@dataclass
class RankedFile:
    path: str
    reason: str
    tokens: int
    cumulative_tokens: int = 0
    signals: dict[str, int] = field(default_factory=dict)  # signal name -> 1-based rank


def signal_reason(sig: dict[str, int], neighbors: list[str]) -> str:
    bits = []
    if "bm25" in sig:
        bits.append(f"keyword match (BM25 #{sig['bm25']})")
    if "embed" in sig:
        bits.append(f"semantic match (#{sig['embed']})")
    if "graph" in sig:
        bits.append("import neighbor of " + ", ".join(neighbors[:2]) if neighbors else "import neighbor of a top hit")
    return "; ".join(bits) or "fused rank"


def apply_budget(ranked: list[RankedFile], budget: int) -> list[RankedFile]:
    """Stop at the token budget rather than a fixed file count. Always keeps at least one file."""
    out, total = [], 0
    for r in ranked:
        if out and total + r.tokens > budget:
            break
        total += r.tokens
        r.cumulative_tokens = total
        out.append(r)
    return out


def build_prompt(issue: str, cands: list[RankedFile], by_path: dict[str, RepoFile]) -> str:
    lines = []
    for i, c in enumerate(cands, 1):
        f = by_path[c.path]
        defs = ", ".join(DEFS.findall(f.text)[:12])
        lines.append(f"[{i}] {c.path} (~{c.tokens} tokens)\n  defs: {defs or '-'}\n  retrieval: {c.reason}\n  head: {f.text[:SNIPPET_CHARS]!r}")
    return (
        "You choose which files a coding agent must READ to fix this issue. Do not write the fix.\n"
        "Candidates come from keyword, semantic and import-graph retrieval. Keep files the agent must read, "
        "including interfaces and callers of the code that must change. Drop clearly irrelevant ones.\n"
        'Return JSON: {"files": [{"path": str, "reason": "<one line, max 20 words>"}]} ordered most important first.\n\n'
        f"ISSUE:\n{issue[:4000]}\n\nCANDIDATES:\n" + "\n".join(lines)
    )


def rerank(
    issue: str,
    fused: list[str],
    by_path: dict[str, RepoFile],
    signals: dict[str, dict[str, int]],
    neighbors: dict[str, list[str]],
    budget: int,
    llm: FallbackLLM | None = None,
) -> tuple[list[RankedFile], str]:
    """Returns (ranked files within budget, mode) where mode is 'llm:<provider>' or 'fusion'."""
    short = [
        RankedFile(p, signal_reason(signals.get(p, {}), neighbors.get(p, [])), by_path[p].tokens, signals=signals.get(p, {}))
        for p in fused[:SHORTLIST]
    ]
    if llm is not None and llm.configured and short:
        try:
            data = llm.complete_json(build_prompt(issue, short, by_path))
            known = {r.path: r for r in short}
            chosen, seen = [], set()
            for item in data.get("files", []):
                p = item.get("path")
                if p in known and p not in seen:
                    seen.add(p)
                    known[p].reason = str(item.get("reason") or known[p].reason).strip().replace("\n", " ")
                    chosen.append(known[p])
            if chosen:
                return apply_budget(chosen, budget), f"llm:{llm.last_provider}"
        except (LLMError, KeyError, AttributeError, TypeError, ValueError):
            pass
    return apply_budget(short, budget), "fusion"
