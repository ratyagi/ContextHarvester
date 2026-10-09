"""Tune fusion/graph parameters on DEV instances only (before the cutoff, non-held-out repos)."""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pandas as pd

from .evaluate import gold_sets, repo_dir
from .files import list_files
from .gold import strip_fix_text
from .metrics import recall_at_k
from .pipeline import Params, Retriever, Retrieved, rankings_from
from .semantic import EmbedCache, Embedder
from .snapshot import ensure_clone, ensure_commit, worktree
from .split import assign

GRID = {
    "rrf_k": [20, 60],
    "graph_weight": [0.25, 0.5, 0.75, 1.0],
    "n_seed": [5, 10, 20],
    "max_per_seed": [3, 6, 10],
}


def tune(instances: pd.DataFrame, split: dict, embedder: Embedder, repos_dir: Path, cache_dir: Path, limit: int | None = None):
    df = instances.copy()
    df["group"] = assign(df, split)
    df = df[df["group"] == "dev"].sort_values(["repo", "created_at"])  # never touches held_out or test
    if limit:
        df = df.groupby("repo").head(limit)
    cached = []
    for repo, grp in df.groupby("repo"):
        rd = ensure_clone(f"https://github.com/{repo}.git", repo_dir(repos_dir, repo))
        cache = EmbedCache(Path(cache_dir) / repo.replace("/", "__"), embedder.name)
        for inst in grp.itertuples():
            try:
                ensure_commit(rd, inst.base_commit)
                with worktree(rd, inst.base_commit) as wt:
                    files = list_files(wt)
                r = Retriever(files, embedder, cache)
                gold = gold_sets(list(inst.gold_files), {f.path for f in files})["filtered"]
                if gold:
                    cached.append((r.retrieve(strip_fix_text(inst.issue_text)), r.graph, [f.path for f in files], gold, inst.instance_id))
            except Exception as e:
                print(f"tune skip {inst.instance_id}: {e}", file=sys.stderr)
    if not cached:
        raise RuntimeError("no dev instances available for tuning")
    results = []
    for vals in itertools.product(*GRID.values()):
        p = Params(**dict(zip(GRID, vals)))
        rec = [recall_at_k(rankings_from(rt, g, p, paths, iid)["full"], gold, 10) for rt, g, paths, gold, iid in cached]
        results.append({**p.to_dict(), "dev_recall@10": sum(rec) / len(rec), "n": len(rec)})
    out = pd.DataFrame(results).sort_values("dev_recall@10", ascending=False, kind="stable")
    return Params(**{k: out.iloc[0][k].item() if hasattr(out.iloc[0][k], "item") else out.iloc[0][k] for k in GRID}), out
