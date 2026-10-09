"""`ch` CLI: rank (live), replay (closed issue graded against the merged fix), and the evaluation pipeline."""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import pandas as pd
import typer

app = typer.Typer(add_completion=False, help="Ranked minimal file set a coding agent needs to read to fix an issue.")

CACHE = Path(".cache")
CORPUS = Path("corpus")


def parse_repo(s: str) -> str:
    m = re.search(r"github\.com[/:]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", s.strip())
    if m:
        return m.group(1)
    if re.fullmatch(r"[\w.-]+/[\w.-]+", s.strip()):
        return s.strip()
    raise typer.BadParameter(f"not a GitHub repo URL or owner/name: {s}")


def _tag(s: str) -> str:
    return s.replace("/", "__")


def _print_ranked(ranked, mode: str, budget: int, as_json: bool, elapsed: float) -> None:
    if as_json:
        print(json.dumps({"mode": mode, "token_budget": budget, "seconds": round(elapsed, 1), "files": [
            {"path": r.path, "reason": r.reason, "tokens": r.tokens, "cumulative_tokens": r.cumulative_tokens} for r in ranked]}, indent=1))
        return
    typer.echo(f"{'#':>2}  {'file':<56} {'tokens':>7} {'cumulative':>10}  reason")
    for i, r in enumerate(ranked, 1):
        typer.echo(f"{i:>2}  {r.path:<56} {r.tokens:>7} {r.cumulative_tokens:>10}  {r.reason}")
    typer.echo(f"\nranked by: {mode} | budget {budget} tokens | {elapsed:.1f}s")


def _signals(retriever, query, params, paths):
    """Per-file signal ranks (for reasons) and the import parents that pulled in graph neighbors."""
    from .pipeline import fuse

    sig, full = fuse(retriever.retrieve(query), retriever.graph, params)
    ranks: dict[str, dict[str, int]] = {}
    for name in ("bm25", "embed", "graph"):
        for i, (p, _) in enumerate(sig[name], 1):
            ranks.setdefault(p, {})[name] = i
    seeds = [p for p, _ in sig["bm25+embed"][: params.n_seed]]
    nbrs: dict[str, list[str]] = {}
    for s in seeds:
        for n in retriever.graph.forward.get(s, set()) | retriever.graph.reverse.get(s, set()):
            nbrs.setdefault(n, []).append(s)
    return ranks, nbrs, [p for p, _ in full]


def _load_params(path: Path | None):
    from .pipeline import Params

    p = path or CORPUS / "tuned_params.json"
    return Params(**json.loads(Path(p).read_text())) if Path(p).exists() else Params()


def _rank_text(repo, query, base_commit, budget, no_rerank, as_json, replay_gold=None, label=""):
    from .evaluate import repo_dir
    from .files import list_files
    from .gold import strip_fix_text
    from .llm import FallbackLLM
    from .pipeline import Retriever, rankings_from
    from .rerank import rerank
    from .semantic import EmbedCache, MiniLMEmbedder
    from .snapshot import default_branch_head, ensure_clone, worktree

    t0 = time.time()
    rd = ensure_clone(f"https://github.com/{repo}.git", repo_dir(CACHE / "repos", repo))
    commit = base_commit or default_branch_head(rd)
    emb = MiniLMEmbedder()
    params = _load_params(None)
    with worktree(rd, commit) as wt:
        files = list_files(wt)
    by_path = {f.path: f for f in files}
    q = strip_fix_text(query)
    r = Retriever(files, emb, EmbedCache(CACHE / "emb" / _tag(repo), emb.name))
    ranks, nbrs, full = _signals(r, q, params, list(by_path))
    llm = None if no_rerank else FallbackLLM()
    ranked, mode = rerank(query, full, by_path, ranks, nbrs, budget, llm)
    _print_ranked(ranked, mode, budget, as_json, time.time() - t0)
    if replay_gold is not None:
        gold = set(replay_gold) & set(by_path)
        bm = [p for p, _ in r.lex.search(q, 10)]
        top = [x.path for x in ranked[:10]]
        typer.echo(f"\nREPLAY vs merged fix ({len(gold)} source files in snapshot): {', '.join(sorted(gold)) or '-'}")
        typer.echo(f"  ranker top-10 surfaced : {sorted(gold & set(top))}  ({len(gold & set(top))}/{len(gold)})")
        typer.echo(f"  BM25 alone top-10      : {sorted(gold & set(bm))}  ({len(gold & set(bm))}/{len(gold)})")
        typer.echo("  note: recall against changed files is a lower bound; a highly ranked file outside the gold set is not necessarily a false positive.")


@app.command()
def rank(
    repo: str = typer.Argument(..., help="GitHub URL or owner/name"),
    issue: int = typer.Argument(..., help="Issue number"),
    budget: int = typer.Option(20000, help="Token budget for files to read"),
    no_rerank: bool = typer.Option(False, help="Skip the LLM rerank; use fusion output"),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable output (for agents calling this as a tool)"),
):
    """Rank the files to read for an issue, at the repo's current default-branch head."""
    from .harvest import GitHub

    repo = parse_repo(repo)
    iss = GitHub().get(f"/repos/{repo}/issues/{issue}")
    _rank_text(repo, f"{iss['title']}\n\n{iss.get('body') or ''}", None, budget, no_rerank, json_out)


@app.command()
def replay(
    repo: str = typer.Argument(...),
    issue: int = typer.Argument(..., help="A CLOSED issue whose merged fix is known"),
    budget: int = typer.Option(20000),
    no_rerank: bool = typer.Option(False),
):
    """Run on a closed issue at the commit before its fix, then grade against the files the merged PR touched."""
    from .gold import filter_gold, is_test_file
    from .harvest import GitHub, build_instance

    repo = parse_repo(repo)
    gh = GitHub()
    prs = gh.get("/search/issues", q=f"repo:{repo} is:pr is:merged \"#{issue}\" in:body,title", per_page=10)["items"]
    for item in prs:
        pr = gh.get(f"/repos/{repo}/pulls/{item['number']}")
        inst = build_instance(gh, repo, pr, issue)
        if inst:
            gold = [f for f in filter_gold(inst["gold_files"]) if not is_test_file(f)]
            typer.echo(f"issue #{issue} fixed by PR #{pr['number']}; snapshot {inst['base_commit'][:10]} (the fix is NOT in the index)\n")
            _rank_text(repo, inst["issue_text"], inst["base_commit"], budget, no_rerank, False, replay_gold=gold)
            return
    typer.echo("no merged PR with a `Fixes #N` link found for that issue", err=True)
    raise typer.Exit(1)


@app.command()
def harvest(
    repos_csv: Path = typer.Option(CORPUS / "repos.csv", help="Clay-exported corpus"),
    repo: list[str] = typer.Option(None, "--repo", help="Harvest these repos instead of the CSV"),
    out: Path = typer.Option(CORPUS / "instances_harvested.parquet"),
    max_per_repo: int = typer.Option(30),
):
    """Mine `Fixes #N` issue-to-PR links into an instance table."""
    from .harvest import GitHub, harvest_repo, to_frame

    repos = [parse_repo(r) for r in repo] if repo else pd.read_csv(repos_csv)["repo"].tolist()
    if not repos:
        raise typer.BadParameter(f"no repos: {repos_csv} is empty. Build the corpus in Clay (docs/CLAY_RUNBOOK.md) or pass --repo.")
    gh, rows = GitHub(), []
    for r in repos:
        got = harvest_repo(gh, r, max_per_repo)
        typer.echo(f"{r}: {len(got)} instances", err=True)
        rows += got
    out.parent.mkdir(parents=True, exist_ok=True)
    to_frame(rows).to_parquet(out, index=False)
    typer.echo(f"wrote {len(rows)} instances to {out}")


@app.command()
def swebench(
    out: Path = typer.Option(CORPUS / "instances_swebench.parquet"),
    parquet: Path = typer.Option(None, help="Local SWE-bench Verified parquet (skips the download)"),
):
    """Load SWE-bench Verified into the same instance table."""
    from . import swebench as sb

    df = sb.load(parquet)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    typer.echo(f"wrote {len(df)} instances ({df.repo.nunique()} repos) to {out}")


@app.command()
def split(
    instances: list[Path] = typer.Argument(..., help="Instance parquet files (all sources share one time axis)"),
    held_out: list[str] = typer.Option([], "--held-out", help="Repos used only at evaluation time"),
    out: Path = typer.Option(CORPUS / "split.json"),
    quantile: float = typer.Option(0.5),
):
    """Freeze the forward time cutoff and held-out repos. Run before `tune`; commit the result."""
    from . import split as sp

    df = pd.concat([pd.read_parquet(p) for p in instances])
    s = sp.make_split(df, held_out, quantile)
    sp.save(s, out)
    typer.echo(json.dumps(s, indent=1))


def _read(paths: list[Path]) -> pd.DataFrame:
    return pd.concat([pd.read_parquet(p) for p in paths], ignore_index=True)


@app.command()
def tune(
    instances: list[Path] = typer.Argument(...),
    split_file: Path = typer.Option(CORPUS / "split.json"),
    limit: int = typer.Option(0, help="Max dev instances per repo (0 = all)"),
):
    """Grid-search fusion and graph parameters on dev instances only."""
    from . import split as sp
    from .semantic import MiniLMEmbedder

    best, table = __import__("context_harvester.tune", fromlist=["tune"]).tune(
        _read(instances), sp.load(split_file), MiniLMEmbedder(), CACHE / "repos", CACHE / "emb", limit or None)
    (CORPUS / "tuned_params.json").write_text(json.dumps(best.to_dict(), indent=2) + "\n")
    table.to_parquet(CORPUS / "tuning_grid.parquet", index=False)
    typer.echo(table.head(8).to_string(index=False))
    typer.echo(f"\nbest params written to {CORPUS / 'tuned_params.json'}")


@app.command(name="eval")
def eval_cmd(
    instances: list[Path] = typer.Argument(...),
    split_file: Path = typer.Option(CORPUS / "split.json"),
    out: Path = typer.Option(Path("results")),
    web_data: Path = typer.Option(Path("web/data")),
    groups: list[str] = typer.Option(["test", "held_out"], help="Which groups to evaluate (add dev to report it too)"),
    limit: int = typer.Option(0, help="Max instances per repo (0 = all)"),
):
    """Run every configuration on every instance, write Parquet, and refresh the results page data."""
    from . import report
    from . import split as sp
    from .evaluate import run_eval
    from .semantic import MiniLMEmbedder

    sources = {pd.read_parquet(p)["source"].iloc[0] for p in instances}
    split_d = sp.load(split_file)
    df = _read(instances)
    per, excluded = run_eval(df, split_d, MiniLMEmbedder(), CACHE / "repos", CACHE / "emb", _load_params(None), tuple(groups), limit or None)
    if per.empty:
        typer.echo("no instances evaluated", err=True)
        raise typer.Exit(1)
    meta = {"split": split_d, "params": _load_params(None).to_dict(), "sources": sorted(sources), "n_instances": int(per.instance_id.nunique()),
            "generated": pd.Timestamp.now("UTC").isoformat()}
    summary = report.write_outputs(per, excluded, out, web_data, meta)
    typer.echo(report.build_readme_block(summary))
    if len(excluded):
        typer.echo(f"\n{len(excluded)} instances excluded (see {out}/excluded.parquet); leakage failures are listed with reason LEAKAGE", err=True)


@app.command()
def report(
    results: Path = typer.Option(Path("results/summary.parquet")),
    readme: Path = typer.Option(Path("README.md")),
):
    """Rewrite the README results block from results/summary.parquet."""
    from . import report as rp

    rp.update_readme(readme, pd.read_parquet(results))
    typer.echo(f"updated {readme}")


if __name__ == "__main__":
    app()
