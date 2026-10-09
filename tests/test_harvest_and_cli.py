"""Code paths that need the network in real use, exercised against mocks and a local repo."""
import json
import subprocess

import httpx
from typer.testing import CliRunner

from context_harvester import cli, snapshot
from context_harvester.harvest import GitHub, harvest_repo
from conftest import sh


def mock_github(a, b):
    def handler(req: httpx.Request) -> httpx.Response:
        p = req.url.path
        if p == "/repos/o/r/pulls" and req.url.params["page"] == "1":
            return httpx.Response(200, json=[
                {"number": 5, "title": "Fix date parsing", "body": "Fixes #3", "merged_at": "2024-02-01T00:00:00Z", "merge_commit_sha": b},
                {"number": 6, "title": "unmerged", "body": "Fixes #4", "merged_at": None, "merge_commit_sha": None},
            ])
        if p == "/repos/o/r/pulls":
            return httpx.Response(200, json=[])
        if p == "/repos/o/r/issues/3":
            return httpx.Response(200, json={"title": "dates broken", "body": "parse_date accepts junk", "created_at": "2024-01-01T00:00:00Z"})
        if p == "/repos/o/r/pulls/5/commits":
            return httpx.Response(200, json=[{"parents": [{"sha": a}]}]) if req.url.params["page"] == "1" else httpx.Response(200, json=[])
        if p == "/repos/o/r/pulls/5/files":
            files = [{"filename": "pkg/parser.py"}, {"filename": "CHANGELOG.md"}, {"filename": "tests/test_parser.py"}]
            return httpx.Response(200, json=files) if req.url.params["page"] == "1" else httpx.Response(200, json=[])
        return httpx.Response(404, json={})
    return handler


def test_harvest_repo_builds_instance(fixrepo):
    repo, a, b = fixrepo
    gh = GitHub(client=httpx.Client(transport=httpx.MockTransport(mock_github(a, b))))
    rows = harvest_repo(gh, "o/r")
    assert len(rows) == 1
    r = rows[0]
    assert (r["issue_number"], r["pr_number"], r["base_commit"], r["fix_commit"]) == (3, 5, a, b)
    assert "pkg/parser.py" in r["gold_files"] and "CHANGELOG.md" in r["gold_files"]  # unfiltered kept; filtered at eval time
    assert r["leaky"] is False


def local_clone(monkeypatch, repo, tmp_path):
    def fake(url, dest):
        subprocess.run(["git", "clone", "-q", str(repo), str(dest)], check=True)
        return dest
    monkeypatch.setattr(snapshot, "ensure_clone", fake)
    monkeypatch.setattr(cli, "CACHE", tmp_path / ".cache")
    import context_harvester.semantic as sem
    from conftest import HashEmbedder
    monkeypatch.setattr(sem, "MiniLMEmbedder", HashEmbedder)


def test_rank_command_prints_ranked_files_json(fixrepo, tmp_path, monkeypatch):
    repo, a, b = fixrepo
    local_clone(monkeypatch, repo, tmp_path)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False); monkeypatch.delenv("MISTRAL_API_KEY", raising=False); monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(cli, "_load_params", lambda p: __import__("context_harvester.pipeline", fromlist=["Params"]).Params())
    gh_issue = {"title": "parse_date does not validate", "body": "date string accepted"}
    monkeypatch.setattr(GitHub, "get", lambda self, path, **kw: gh_issue)
    res = CliRunner().invoke(cli.app, ["rank", "o/r", "3", "--json"])
    assert res.exit_code == 0, res.output
    out = json.loads(res.stdout[res.stdout.index("{"):])
    assert out["mode"] == "fusion" and out["files"][0]["path"] == "pkg/parser.py"
    assert out["files"][0]["cumulative_tokens"] == out["files"][0]["tokens"] and out["files"][0]["reason"]


def test_replay_snapshots_before_fix_and_grades(fixrepo, tmp_path, monkeypatch):
    repo, a, b = fixrepo
    local_clone(monkeypatch, repo, tmp_path)
    monkeypatch.setattr(cli, "_load_params", lambda p: __import__("context_harvester.pipeline", fromlist=["Params"]).Params())
    gh = GitHub(client=httpx.Client(transport=httpx.MockTransport(mock_github(a, b))))
    real_get = GitHub.get
    def get(self, path, **kw):
        if path == "/search/issues":
            return {"items": [{"number": 5}]}
        if path == "/repos/o/r/pulls/5":
            return {"number": 5, "title": "Fix date parsing", "body": "Fixes #3", "merged_at": "x", "merge_commit_sha": b}
        return real_get(gh, path, **kw)
    monkeypatch.setattr(GitHub, "get", get)
    monkeypatch.setattr(cli, "GitHub", GitHub, raising=False)
    monkeypatch.setattr("context_harvester.harvest.GitHub", lambda: gh)
    res = CliRunner().invoke(cli.app, ["replay", "o/r", "3", "--no-rerank"])
    assert res.exit_code == 0, res.output
    assert "the fix is NOT in the index" in res.stdout and "REPLAY vs merged fix" in res.stdout
    assert "pkg/parser.py" in res.stdout and "lower bound" in res.stdout
