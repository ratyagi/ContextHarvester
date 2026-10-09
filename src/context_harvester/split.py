"""Forward time split and held-out repos, frozen to corpus/split.json BEFORE any tuning (PRD: Protocol)."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def make_split(instances: pd.DataFrame, held_out_repos: list[str], quantile: float = 0.5) -> dict:
    """Cutoff = the `quantile` date of non-held-out instances. Dev < cutoff <= test. No shuffling."""
    pool = instances[~instances["repo"].isin(held_out_repos)]
    ts = pd.to_datetime(pool["created_at"], utc=True)
    cutoff = ts.quantile(quantile).isoformat()
    return {"cutoff": cutoff, "held_out_repos": sorted(held_out_repos)}


def assign(instances: pd.DataFrame, split: dict) -> pd.Series:
    """'held_out' (evaluation-only repos), 'dev' (before cutoff, tunable), or 'test' (after cutoff)."""
    cutoff = pd.Timestamp(split["cutoff"])
    ts = pd.to_datetime(instances["created_at"], utc=True)
    out = pd.Series("test", index=instances.index)
    out[ts < cutoff] = "dev"
    out[instances["repo"].isin(split["held_out_repos"])] = "held_out"
    return out


def save(split: dict, path: Path) -> None:
    Path(path).write_text(json.dumps(split, indent=2) + "\n")


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text())
