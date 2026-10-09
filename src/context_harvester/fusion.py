"""Reciprocal rank fusion. No training data, cannot overfit the small eval set (PRD: Fusion)."""
from __future__ import annotations


def rrf(rankings: list[tuple[list[str], float]], k: int = 60) -> list[tuple[str, float]]:
    """rankings: [(ordered paths, weight), ...]. Returns paths by fused score, ties by path."""
    scores: dict[str, float] = {}
    for paths, weight in rankings:
        for rank, p in enumerate(paths, start=1):
            scores[p] = scores.get(p, 0.0) + weight / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
