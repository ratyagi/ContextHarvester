"""Whole harness on a local synthetic repo: snapshot, leakage guard, all methods, Parquet, README block."""
import pandas as pd
from typer.testing import CliRunner

from context_harvester import report
from context_harvester.cli import app
from context_harvester.evaluate import run_eval
from context_harvester.harvest import COLUMNS
from context_harvester.pipeline import Params
from conftest import sh


def instances(repo, a, b, fix_commit):
    base = dict(source="harvested", repo="o/r", issue_number=1, pr_number=1, issue_title="t", base_commit=a, fix_commit=fix_commit,
                gold_files=["pkg/parser.py", "CHANGELOG.md"], gold_patch="", leaky=False)
    rows = [
        {**base, "instance_id": f"o__r-{i}", "issue_text": "parse_date does not validate the date string", "created_at": f"2024-0{i}-01T00:00:00Z"}
        for i in range(1, 5)
    ]
    return pd.DataFrame(rows, columns=COLUMNS)


def test_run_eval_reports_all_methods_and_catches_leakage(fixrepo, embedder, tmp_path):
    repo, a, b = fixrepo
    good = instances(repo, a, b, b)
    bad = instances(repo, b, b, b).assign(instance_id=lambda d: "leak-" + d.instance_id)  # snapshot == fix
    df = pd.concat([good, bad], ignore_index=True)
    split = {"cutoff": "2000-01-01T00:00:00+00:00", "held_out_repos": []}
    per, excluded = run_eval(df, split, embedder, tmp_path / "repos", tmp_path / "emb", Params(), url_for=lambda r: str(repo), log=lambda s: None)
    assert set(per.method) == {"random", "bm25", "embed", "bm25+embed", "full"}
    assert set(per.instance_id) == set(good.instance_id)                 # leaked instances never scored
    assert excluded.reason.str.startswith("LEAKAGE").sum() == len(bad)   # ...and are reported, not dropped silently
    filt = per[(per.gold_mode == "filtered") & (per.method == "bm25")]
    assert (filt["recall@10"] == 1.0).all() and (filt.n_gold == 1).all()  # CHANGELOG.md filtered from gold
    un = per[per.gold_mode == "unfiltered"]
    assert (un.n_gold == 1).all() and (un.n_gold_raw == 2).all()      # CHANGELOG.md is not indexable: loss is visible
    out = report.write_outputs(per, excluded, tmp_path / "res", tmp_path / "web", {"split": split})
    assert (tmp_path / "res/per_instance.parquet").exists() and (tmp_path / "web/results.json").exists()
    readme = tmp_path / "README.md"
    readme.write_text("x\n<!-- RESULTS:START -->\nPLACEHOLDER\n<!-- RESULTS:END -->\n")
    report.update_readme(readme, out)
    assert "BM25 over file contents" in readme.read_text() and "PLACEHOLDER" not in readme.read_text()


def test_cli_help_lists_commands():
    r = CliRunner().invoke(app, ["--help"])
    assert r.exit_code == 0
    for c in ["rank", "replay", "harvest", "swebench", "split", "tune", "eval", "report"]:
        assert c in r.stdout
