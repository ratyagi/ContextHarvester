import pandas as pd

from context_harvester import experiments as ex
from context_harvester.harvest import COLUMNS
from context_harvester.pipeline import Params


def make(a, b, dates):
    rows = [dict(instance_id=f"o__r-{i}", source="harvested", repo="o/r", issue_number=i, pr_number=i, issue_title="t",
                 issue_text="parse_date does not validate the date string", created_at=d, base_commit=a, fix_commit=b,
                 gold_files=["pkg/parser.py"], gold_patch="", leaky=False) for i, d in enumerate(dates, 1)]
    return pd.DataFrame(rows, columns=COLUMNS)


def test_experiments_use_dev_instances_only_and_report_every_variant(fixrepo, embedder, tmp_path):
    repo, a, b = fixrepo
    df = make(a, b, ["2020-01-01T00:00:00Z", "2020-02-01T00:00:00Z", "2030-01-01T00:00:00Z"])  # last is after the cutoff
    split = {"cutoff": "2025-01-01T00:00:00+00:00", "held_out_repos": []}
    rows, graph_rows, cps = ex.run_experiments(df, split, embedder, tmp_path / "r", tmp_path / "e", Params(), url_for=lambda r: str(repo), log=lambda s: None)
    assert set(rows.instance_id) == {"o__r-1", "o__r-2"}                       # the post-cutoff instance is never touched
    assert set(rows.variant) == set(ex.VARIANTS) and set(rows.method) == set(ex.METHODS)
    assert (graph_rows.edge_jaccard == 1.0).all()                              # regex graph equals the AST graph here
    summary = ex.summarize(rows, graph_rows, cps)
    base = summary[(summary.variant == ex.BASELINE) & (summary.method == "full")].iloc[0]
    assert base.margin_vs_baseline == 0.0 and base["recall@10"] == 1.0
    md = ex.markdown(summary, graph_rows, cps)
    assert "dev instances only" in md and "| candidates k=200, 4 chunks |" in md and "1.000" in md
