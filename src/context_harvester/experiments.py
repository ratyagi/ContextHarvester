"""Dev-only experiments: what does a cheaper cold path cost in recall?

Only DEV instances (before the frozen cutoff, non-held-out repos) are used, so the reported test and held-out
results are never touched. The baseline variant reproduces the committed pipeline exactly.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .evaluate import gold_sets, repo_dir
from .files import list_files
from .gold import strip_fix_text
from .lexical import LexicalIndex
from .metrics import recall_at_k
from .pipeline import Params, Retriever
from .report import _boot_ci
from .semantic import EmbedCache, Embedder, chunk_text
from .snapshot import ensure_clone, ensure_commit, worktree
from .split import assign
from .structural import build_graph

BASELINE = "baseline: all files, 8 chunks, AST graph"
# name -> Retriever settings. Candidate variants use the regex graph, the cheap one that would ship with them.
VARIANTS: dict[str, dict] = {
    BASELINE: dict(scope="all", graph="ast"),
    "all files, 8 chunks, regex graph": dict(scope="all", graph="regex"),
    "candidates k=100, 4 chunks": dict(scope="candidates", k=100, chunks=4, graph="regex"),
    "candidates k=200, 4 chunks": dict(scope="candidates", k=200, chunks=4, graph="regex"),
    "candidates k=400, 4 chunks": dict(scope="candidates", k=400, chunks=4, graph="regex"),
    "candidates k=200, 2 chunks": dict(scope="candidates", k=200, chunks=2, graph="regex"),
    "candidates k=200, 8 chunks": dict(scope="candidates", k=200, chunks=8, graph="regex"),
}
METHODS = ("bm25", "embed", "bm25+embed", "full")


def measure_throughput(embedder: Embedder, n: int = 256) -> float:
    """Chunks per second on this machine, from a fresh batch (never cached). Used to turn chunk counts into
    an ESTIMATED cold embedding time; the estimate is labelled as such wherever it is reported."""
    texts = [f"def sample_{i}(x):\n" + "    y = x + 1\n" * 90 for i in range(n)]
    t0 = time.perf_counter()
    embedder.encode(texts)
    return n / (time.perf_counter() - t0)


def _edges(g) -> set[tuple[str, str]]:
    return {(a, b) for a, bs in g.forward.items() for b in bs}


def run_experiments(
    instances: pd.DataFrame,
    split: dict,
    embedder: Embedder,
    repos_dir: Path,
    cache_dir: Path,
    params: Params,
    limit: int | None = None,
    url_for=lambda repo: f"https://github.com/{repo}.git",
    log=lambda s: print(s, file=sys.stderr),
):
    df = instances.copy()
    df["group"] = assign(df, split)
    df = df[df["group"] == "dev"].sort_values(["repo", "created_at"])  # dev only, by construction
    if limit:
        df = df.groupby("repo").head(limit)
    cps = measure_throughput(embedder)
    log(f"embedding throughput on this machine: {cps:.0f} chunks/s")
    rows, graph_rows = [], []
    for repo, grp in df.groupby("repo"):
        rd = ensure_clone(url_for(repo), repo_dir(repos_dir, repo))
        cache = EmbedCache(Path(cache_dir) / repo.replace("/", "__"), embedder.name)
        for inst in grp.itertuples():
            try:
                ensure_commit(rd, inst.base_commit)
                with worktree(rd, inst.base_commit) as wt:
                    files = list_files(wt)
                if not files:
                    continue
                gold = gold_sets(list(inst.gold_files), {f.path for f in files})["filtered"]
                if not gold:
                    continue
                lex = LexicalIndex(files)
                t0 = time.perf_counter(); g_ast = build_graph(files, "ast"); t_ast = time.perf_counter() - t0
                t0 = time.perf_counter(); g_re = build_graph(files, "regex"); t_re = time.perf_counter() - t0
                ea, er = _edges(g_ast), _edges(g_re)
                graph_rows.append({"instance_id": inst.instance_id, "files": len(files), "ast_s": t_ast, "regex_s": t_re,
                                   "edge_jaccard": len(ea & er) / max(1, len(ea | er))})
                all_chunks = sum(len(chunk_text(f.path, f.text)) for f in files)
                query = strip_fix_text(inst.issue_text)
                for name, cfg in VARIANTS.items():
                    r = Retriever(files, embedder, cache, scope=cfg["scope"], candidate_k=cfg.get("k", 300),
                                  candidate_chunks=cfg.get("chunks", 4), lex=lex, graph=g_ast if cfg["graph"] == "ast" else g_re)
                    ranks = r.rankings(query, params, inst.instance_id)
                    chunks = r.cand_sem.last_total_chunks if r.cand_sem else all_chunks
                    for m in METHODS:
                        rows.append({"instance_id": inst.instance_id, "repo": repo, "variant": name, "method": m,
                                     "recall@5": recall_at_k(ranks[m], gold, 5), "recall@10": recall_at_k(ranks[m], gold, 10),
                                     "chunks": chunks, "files": len(files)})
                log(f"ok {inst.instance_id} ({len(files)} files)")
            except Exception as e:
                log(f"skip {inst.instance_id}: {type(e).__name__}: {e}")
    return pd.DataFrame(rows), pd.DataFrame(graph_rows), cps


def summarize(rows: pd.DataFrame, graph_rows: pd.DataFrame, cps: float) -> pd.DataFrame:
    out = []
    for m in METHODS:
        d = rows[rows.method == m]
        base = d[d.variant == BASELINE].set_index("instance_id")["recall@10"]
        for v in VARIANTS:
            g = d[d.variant == v].set_index("instance_id")
            if g.empty:
                continue
            diff = (g["recall@10"] - base.reindex(g.index)).dropna().to_numpy()
            lo, hi = _boot_ci(diff) if len(diff) else (np.nan, np.nan)
            out.append({"method": m, "variant": v, "n": len(g), "recall@5": g["recall@5"].mean(), "recall@10": g["recall@10"].mean(),
                        "margin_vs_baseline": float(diff.mean()) if len(diff) else np.nan, "margin_lo": lo, "margin_hi": hi,
                        "mean_chunks": g["chunks"].mean(), "est_cold_embed_s": g["chunks"].mean() / cps})
    return pd.DataFrame(out)


def markdown(summary: pd.DataFrame, graph_rows: pd.DataFrame, cps: float) -> str:
    f = lambda x: "n/a" if pd.isna(x) else f"{x:.3f}"
    lines = [f"# Dev experiments (dev instances only; the reported test and held-out results are untouched)", "",
             f"Embedding throughput measured on this machine: {cps:.0f} chunks/s. `est. cold embed` = mean chunks per query / throughput: an ESTIMATE, not a timing.", ""]
    if len(graph_rows):
        lines += ["## Import graph: regex vs AST", "",
                  f"- mean edge overlap (Jaccard) between the two graphs: {graph_rows.edge_jaccard.mean():.4f} (min {graph_rows.edge_jaccard.min():.4f}) over {len(graph_rows)} snapshots",
                  f"- mean build time: AST {graph_rows.ast_s.mean():.2f}s, regex {graph_rows.regex_s.mean():.2f}s (warm interpreter, mean {graph_rows.files.mean():.0f} files per snapshot)", ""]
    for m in ("full", "bm25+embed"):
        s = summary[summary.method == m]
        lines += [f"## recall@10 for `{m}` by variant", "", "| Variant | n | recall@5 | recall@10 | change vs baseline (95% CI) | mean chunks embedded | est. cold embed (s) |", "|---|---|---|---|---|---|---|"]
        for _, r in s.iterrows():  # column names like "recall@5" are not valid identifiers, so index by name
            ch = "-" if r["variant"] == BASELINE else f"{r['margin_vs_baseline']:+.3f} ({f(r['margin_lo'])}, {f(r['margin_hi'])})"
            lines.append(f"| {r['variant']} | {int(r['n'])} | {f(r['recall@5'])} | {f(r['recall@10'])} | {ch} | {r['mean_chunks']:.0f} | {r['est_cold_embed_s']:.1f} |")
        lines.append("")
    return "\n".join(lines)
