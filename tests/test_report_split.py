import numpy as np
import pandas as pd

from context_harvester.report import summarize, markdown_table
from context_harvester.split import assign, make_split


def inst(repo, dates):
    return pd.DataFrame({"repo": repo, "created_at": dates})


def test_forward_split_no_shuffle_and_heldout():
    df = pd.concat([inst("a/a", ["2021-01-01", "2022-01-01", "2023-01-01", "2024-01-01"]), inst("h/h", ["2019-01-01", "2024-06-01"])], ignore_index=True)
    s = make_split(df, ["h/h"])
    g = assign(df, s)
    assert list(g[:4]) == ["dev", "dev", "test", "test"]      # strictly by date
    assert set(g[4:]) == {"held_out"}                          # held-out regardless of date


def _per(source, group, n=8):
    rows = []
    for i in range(n):
        for m, r in [("bm25", 0.4), ("full", 0.6), ("random", 0.0), ("embed", 0.3), ("bm25+embed", 0.5)]:
            rows.append({"instance_id": f"{source}{i}", "source": source, "group": group, "gold_mode": "filtered", "leaky": i % 4 == 0,
                         "method": m, "n_gold": 1, "tokens_to_all": 1000.0 + i, **{f"recall@{k}": r for k in (1, 2, 3, 5, 7, 10, 15, 20, 30, 50)},
                         **{f"recall@{b}k_tok": r for b in (10, 20, 40, 80, 160)}})
    return rows


def test_summary_never_pools_sources_and_reports_margin():
    per = pd.DataFrame(_per("swebench", "test") + _per("harvested", "test"))
    s = summarize(per)
    assert set(s.source) == {"swebench", "harvested"}
    assert (s.groupby(["source", "group", "subset", "gold_mode", "method"]).size() == 1).all()  # one row per source: no pooled row
    full = s[(s.source == "swebench") & (s.method == "full") & (s.subset == "all")].iloc[0]
    assert np.isclose(full.margin_vs_bm25, 0.2) and full.n == 8
    clean = s[(s.source == "swebench") & (s.method == "full") & (s.subset == "clean")].iloc[0]
    assert clean.n == 6                                         # leaky instances removed
    assert "| BM25 over file contents |" in markdown_table(s, "swebench", "test")
