"""Load SWE-bench Verified (500 human-validated instances, 12 Python repos) as ground truth."""
from __future__ import annotations

from pathlib import Path

import httpx
import pandas as pd

from .gold import leaky_issue, patch_files

URL = "https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified/resolve/main/data/test-00000-of-00001.parquet"


def load(parquet: Path | None = None) -> pd.DataFrame:
    if parquet is None:
        r = httpx.get(URL, follow_redirects=True, timeout=120)
        r.raise_for_status()
        tmp = Path("/tmp/swebench_verified.parquet")
        tmp.write_bytes(r.content)
        parquet = tmp
    df = pd.read_parquet(parquet)
    rows = []
    for r in df.itertuples():
        gold = patch_files(r.patch)
        rows.append({
            "instance_id": r.instance_id,
            "source": "swebench",
            "repo": r.repo,
            "issue_number": int(str(r.instance_id).rsplit("-", 1)[-1]),
            "pr_number": 0,
            "issue_title": str(r.problem_statement).split("\n", 1)[0],
            "issue_text": r.problem_statement,
            "created_at": str(r.created_at),
            "base_commit": r.base_commit,
            "fix_commit": "",
            "gold_files": gold,
            "gold_patch": r.patch,
            "leaky": leaky_issue(r.problem_statement, gold),
        })
    from .harvest import COLUMNS
    return pd.DataFrame(rows, columns=COLUMNS)
