"""File-level recall metrics (PRD: Metrics). Recall against changed files is a LOWER BOUND on the true target."""
from __future__ import annotations

import math

KS = (5, 10, 20)
CURVE_KS = (1, 2, 3, 5, 7, 10, 15, 20, 30, 50)  # for the recall@k curves on the results page
BUDGETS = (10_000, 20_000, 40_000, 80_000, 160_000)  # tokens


def recall_at_k(ranked: list[str], gold: set[str], k: int) -> float:
    return len(set(ranked[:k]) & gold) / len(gold)


def recall_at_budget(ranked: list[str], gold: set[str], tokens: dict[str, int], budget: int) -> float:
    """Recall using the longest ranked prefix that fits in `budget` tokens."""
    used, hit = 0, 0
    for p in ranked:
        used += tokens[p]
        if used > budget:
            break
        hit += p in gold
    return hit / len(gold)


def tokens_to_all(ranked: list[str], gold: set[str], tokens: dict[str, int]) -> float:
    """Cumulative tokens read until every gold file has appeared; NaN if the list never reaches them all."""
    used, need = 0, set(gold)
    for p in ranked:
        used += tokens[p]
        need.discard(p)
        if not need:
            return float(used)
    return math.nan


def score(ranked: list[str], gold: set[str], tokens: dict[str, int]) -> dict[str, float]:
    out = {f"recall@{k}": recall_at_k(ranked, gold, k) for k in sorted(set(KS) | set(CURVE_KS))}
    out.update({f"recall@{b // 1000}k_tok": recall_at_budget(ranked, gold, tokens, b) for b in BUDGETS})
    out["tokens_to_all"] = tokens_to_all(ranked, gold, tokens)
    return out
