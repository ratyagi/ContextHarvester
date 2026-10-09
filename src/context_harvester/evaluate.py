"""Evaluation harness: snapshot -> leakage guard -> index -> every method -> recall rows (PRD: Evaluation design)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from .files import list_files
from .gold import filter_gold, strip_fix_text
from .metrics import score
from .pipeline import METHODS, Params, Retriever, rankings_from
from .semantic import EmbedCache, Embedder
from .snapshot import (
    LeakageError, ensure_clone, ensure_commit, verify_fix_absent_blobs, verify_fix_absent_patch, worktree,
)
from .split import assign


def repo_dir(repos_dir: Path, repo: str) -> Path:
    return Path(repos_dir) / repo.replace("/", "__")


def gold_sets(gold_files: list[str], indexed: set[str]) -> dict[str, set[str]]:
    """Gold restricted to indexed files: a file the fix adds, or a non-Python file, cannot be retrieved.

    The raw counts (before this restriction) are kept as n_gold_raw so the loss is visible in the results.
    """
    return {
        "unfiltered": set(gold_files) & indexed,
        "filtered": set(filter_gold(list(gold_files))) & indexed,
    }


def eval_instance(inst, files, retriever: Retriever, params: Params, methods=METHODS) -> list[dict]:
    query = strip_fix_text(inst.issue_text)
    ranks = rankings_from(retriever.retrieve(query), retriever.graph, params, [f.path for f in files], inst.instance_id)
    tokens = {f.path: f.tokens for f in files}
    golds = gold_sets(list(inst.gold_files), set(tokens))
    raw = {"unfiltered": len(set(inst.gold_files)), "filtered": len(set(filter_gold(list(inst.gold_files))))}
    rows = []
    for mode, gold in golds.items():
        if not gold:
            continue
        for m in methods:
            rows.append({"instance_id": inst.instance_id, "gold_mode": mode, "method": m, "n_gold": len(gold), "n_gold_raw": raw[mode], **score(ranks[m], gold, tokens)})
    return rows


def run_eval(
    instances: pd.DataFrame,
    split: dict,
    embedder: Embedder,
    repos_dir: Path,
    cache_dir: Path,
    params: Params,
    only_groups: tuple[str, ...] = ("test", "held_out"),
    limit: int | None = None,
    url_for=lambda repo: f"https://github.com/{repo}.git",
    log=lambda s: print(s, file=sys.stderr),
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (per-instance rows, excluded rows). Leakage failures are recorded, never swallowed."""
    inst_df = instances.copy()
    inst_df["group"] = assign(inst_df, split)
    inst_df = inst_df[inst_df["group"].isin(only_groups)].sort_values(["repo", "created_at"])
    if limit:
        inst_df = inst_df.groupby("repo").head(limit)
    rows, excluded = [], []
    for repo, grp in inst_df.groupby("repo"):
        rd = ensure_clone(url_for(repo), repo_dir(repos_dir, repo))
        cache = EmbedCache(Path(cache_dir) / repo.replace("/", "__"), embedder.name)
        for inst in grp.itertuples():
            try:
                ensure_commit(rd, inst.base_commit)
                if inst.fix_commit:
                    ensure_commit(rd, inst.fix_commit)
                    verify_fix_absent_blobs(rd, inst.base_commit, inst.fix_commit, list(inst.gold_files))
                with worktree(rd, inst.base_commit) as wt:
                    if inst.gold_patch:
                        verify_fix_absent_patch(wt, inst.gold_patch)
                    files = list_files(wt)
                if not files:
                    raise RuntimeError("no indexable files in snapshot")
                r = Retriever(files, embedder, cache)
                for row in eval_instance(inst, files, r, params):
                    rows.append({**row, "source": inst.source, "repo": repo, "group": inst.group, "leaky": bool(inst.leaky)})
                log(f"ok  {inst.instance_id} ({len(files)} files)")
            except LeakageError as e:
                excluded.append({"instance_id": inst.instance_id, "reason": f"LEAKAGE: {e}"})
                log(f"LEAK {inst.instance_id}: {e}")
            except Exception as e:  # network, bad commit, etc.: record and continue
                excluded.append({"instance_id": inst.instance_id, "reason": f"{type(e).__name__}: {e}"})
                log(f"skip {inst.instance_id}: {e}")
    return pd.DataFrame(rows), pd.DataFrame(excluded, columns=["instance_id", "reason"])
