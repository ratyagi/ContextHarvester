"""Summaries with bootstrap CIs, the results page data, and the README ablation table.

Sources are never pooled (PRD: SWE-bench is over-represented in training data; the harvested set is the control).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .metrics import BUDGETS, CURVE_KS, KS
from .pipeline import METHODS

METRIC_COLS = [f"recall@{k}" for k in sorted(set(KS) | set(CURVE_KS))] + [f"recall@{b // 1000}k_tok" for b in BUDGETS]
LABELS = {
    "random": "Random files (floor)",
    "bm25": "BM25 over file contents",
    "embed": "Embeddings only (single pooled vector/file)",
    "bm25+embed": "BM25 + embeddings (RRF, no graph)",
    "full": "BM25 + embeddings + import graph (RRF)",
}
README_START, README_END = "<!-- RESULTS:START -->", "<!-- RESULTS:END -->"


def _boot_ci(x: np.ndarray, n: int = 2000, seed: int = 0) -> tuple[float, float]:
    if len(x) < 2:
        return (math.nan, math.nan)
    rng = np.random.default_rng(seed)
    means = x[rng.integers(0, len(x), (n, len(x)))].mean(axis=1)
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def summarize(per: pd.DataFrame) -> pd.DataFrame:
    """One row per (source, group, subset, gold_mode, method). `subset` is 'all' or 'clean' (leaky issues removed)."""
    rows = []
    for subset in ("all", "clean"):
        d = per if subset == "all" else per[~per["leaky"]]
        for (source, group, mode), g in d.groupby(["source", "group", "gold_mode"]):
            bm25 = g[g["method"] == "bm25"].set_index("instance_id")["recall@10"]
            fusion = g[g["method"] == "bm25+embed"].set_index("instance_id")["recall@10"]
            for m in METHODS:
                gm = g[g["method"] == m].set_index("instance_id")
                if gm.empty:
                    continue
                r10 = gm["recall@10"].to_numpy()
                lo, hi = _boot_ci(r10)
                row = {"source": source, "group": group, "subset": subset, "gold_mode": mode, "method": m, "n": len(gm)}
                row.update({c: float(gm[c].mean()) for c in METRIC_COLS})
                row.update({"recall@10_lo": lo, "recall@10_hi": hi})
                reach = gm["tokens_to_all"].dropna()
                row["tokens_to_all_median"] = float(reach.median()) if len(reach) else math.nan
                row["frac_reaching_all"] = len(reach) / len(gm)
                diff = (gm["recall@10"] - bm25.reindex(gm.index)).dropna().to_numpy()
                row["margin_vs_bm25"] = float(diff.mean()) if len(diff) else math.nan
                row["margin_lo"], row["margin_hi"] = _boot_ci(diff) if len(diff) else (math.nan, math.nan)
                # paired margin over BM25+embeddings: isolates what the import graph contributes
                gd = (gm["recall@10"] - fusion.reindex(gm.index)).dropna().to_numpy()
                row["margin_vs_fusion"] = float(gd.mean()) if len(gd) else math.nan
                row["margin_fusion_lo"], row["margin_fusion_hi"] = _boot_ci(gd) if len(gd) else (math.nan, math.nan)
                rows.append(row)
    return pd.DataFrame(rows)


def fmt(x: float, d: int = 3) -> str:
    return "n/a" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{d}f}"


def markdown_table(summary: pd.DataFrame, source: str, group: str, subset="all", gold_mode="filtered") -> str:
    s = summary[(summary.source == source) & (summary.group == group) & (summary.subset == subset) & (summary.gold_mode == gold_mode)]
    if s.empty:
        return ""
    lines = [
        f"**{source}, {group}, {gold_mode} gold, {'all issues' if subset == 'all' else 'issues without fix text/file names'}** (n={int(s.iloc[0].n)})",
        "",
        "| Configuration | recall@5 | recall@10 (95% CI) | recall@20 | margin vs BM25 (95% CI) | graph contribution: margin vs BM25+emb (95% CI) | median tokens to all gold |",
        "|---|---|---|---|---|---|---|",
    ]
    for m in METHODS:
        r = s[s.method == m]
        if r.empty:
            continue
        r = r.iloc[0]
        margin = "-" if m == "bm25" else f"{r.margin_vs_bm25:+.3f} ({fmt(r.margin_lo)}, {fmt(r.margin_hi)})"
        gmargin = f"{r.margin_vs_fusion:+.3f} ({fmt(r.margin_fusion_lo)}, {fmt(r.margin_fusion_hi)})" if m == "full" else "-"
        lines.append(
            f"| {LABELS[m]} | {fmt(r['recall@5'])} | {fmt(r['recall@10'])} ({fmt(r['recall@10_lo'])}, {fmt(r['recall@10_hi'])}) "
            f"| {fmt(r['recall@20'])} | {margin} | {gmargin} | {fmt(r.tokens_to_all_median, 0)} |"
        )
    return "\n".join(lines)


def build_readme_block(summary: pd.DataFrame) -> str:
    blocks = []
    for source in sorted(summary.source.unique()):
        for group in ("test", "held_out", "dev"):
            for gold_mode in ("filtered", "unfiltered"):
                for subset in ("all", "clean"):
                    t = markdown_table(summary, source, group, subset, gold_mode)
                    if t:
                        blocks.append(t)
    return "\n\n".join(blocks)


def write_outputs(per: pd.DataFrame, excluded: pd.DataFrame, out_dir: Path, web_data: Path, meta: dict) -> pd.DataFrame:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    per.to_parquet(out_dir / "per_instance.parquet", index=False)
    excluded.to_parquet(out_dir / "excluded.parquet", index=False)
    summary = summarize(per)
    summary.to_parquet(out_dir / "summary.parquet", index=False)
    web_data = Path(web_data)
    web_data.mkdir(parents=True, exist_ok=True)
    clean = json.loads(summary.to_json(orient="records"))  # NaN -> null
    (web_data / "results.json").write_text(json.dumps({
        "meta": meta, "labels": LABELS, "summary": clean, "excluded": excluded.to_dict(orient="records"),
    }, indent=1))
    return summary


def update_readme(readme: Path, summary: pd.DataFrame) -> None:
    text = Path(readme).read_text()
    block = f"{README_START}\n{build_readme_block(summary)}\n{README_END}"
    if README_START in text:
        text = text[: text.index(README_START)] + block + text[text.index(README_END) + len(README_END):]
    else:
        text += "\n" + block + "\n"
    Path(readme).write_text(text)
