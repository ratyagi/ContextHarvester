from context_harvester.files import RepoFile
from context_harvester.gold import filter_gold, incidental_reason, leaky_issue, patch_files, strip_fix_text
from context_harvester.harvest import gold_from_pr_files, linked_issues
from context_harvester.llm import FallbackLLM, LLMError, Provider
from context_harvester.rerank import apply_budget, rerank, RankedFile
from context_harvester.tokens import count_tokens

PATCH = "diff --git a/pkg/parser.py b/pkg/parser.py\n--- a/pkg/parser.py\n+++ b/pkg/parser.py\n@@ -1 +1 @@\n-x\n+y\n"


def test_patch_files():
    assert patch_files(PATCH) == ["pkg/parser.py"]


def test_incidental_filter_rules():
    for f in ["poetry.lock", "CHANGELOG.md", "docs/index.rst", "pkg/_version.py", "setup.py", "pkg/x_pb2.py", "tests/fixtures/a.json", ".github/workflows/ci.yml"]:
        assert incidental_reason(f), f
    assert filter_gold(["pkg/parser.py", "poetry.lock", "CHANGELOG.md"]) == ["pkg/parser.py"]


def test_leaky_issue_detection_and_stripping():
    assert leaky_issue("see pkg/parser.py line 3", ["pkg/parser.py"])
    assert leaky_issue("Traceback ... parser.py", ["pkg/parser.py"])
    assert leaky_issue("try this\n```diff\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n```", ["z.py"])
    assert not leaky_issue("dates are parsed wrong", ["pkg/parser.py"])
    assert "@@" not in strip_fix_text("bug\n```diff\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n```\nthanks")


def test_linked_issues_and_renames():
    assert linked_issues("Fixes #12, closes #7. Also resolved: #3 and unrelated #99") == [3, 7, 12]
    assert gold_from_pr_files([{"filename": "b.py", "previous_filename": "a.py"}, {"filename": "c.py"}]) == ["a.py", "b.py", "c.py"]


def mk(path, text="x" * 400):
    return RepoFile(path, text, count_tokens(text))


def test_budget_stops_on_tokens_not_file_count():
    r = [RankedFile(p, "", t) for p, t in [("a", 100), ("b", 100), ("c", 100)]]
    out = apply_budget(r, 250)
    assert [x.path for x in out] == ["a", "b"] and out[-1].cumulative_tokens == 200
    assert len(apply_budget([RankedFile("big", "", 9999)], 10)) == 1  # never returns nothing


class FakeLLM(FallbackLLM):
    def __init__(self, resp=None, fail=False):
        self.providers, self.last_provider, self._resp, self._fail = [object()], "fake", resp, fail

    def complete_json(self, prompt):
        if self._fail:
            raise LLMError("down")
        return self._resp


def test_rerank_uses_llm_reasons_and_drops_files():
    by = {p: mk(p) for p in ["a.py", "b.py", "c.py"]}
    llm = FakeLLM({"files": [{"path": "c.py", "reason": "owns the bug"}, {"path": "nope.py", "reason": "hallucinated"}, {"path": "a.py", "reason": "caller"}]})
    out, mode = rerank("issue", ["a.py", "b.py", "c.py"], by, {}, {}, 10_000, llm)
    assert mode == "llm:fake" and [r.path for r in out] == ["c.py", "a.py"] and out[0].reason == "owns the bug"


def test_rerank_falls_back_to_fusion_with_signal_reasons():
    by = {p: mk(p) for p in ["a.py", "b.py"]}
    out, mode = rerank("issue", ["a.py", "b.py"], by, {"a.py": {"bm25": 1}, "b.py": {"graph": 2}}, {"b.py": ["a.py"]}, 10_000, FakeLLM(fail=True))
    assert mode == "fusion" and out[0].reason.startswith("keyword match") and "import neighbor of a.py" in out[1].reason


def test_provider_fallback_order(monkeypatch):
    monkeypatch.setenv("K1", "x"); monkeypatch.setenv("K2", "y")
    def bad(c, k, p, t): raise RuntimeError("429")
    def good(c, k, p, t): return '{"files": []}'
    llm = FallbackLLM([Provider("one", "K1", bad), Provider("two", "K2", good), Provider("three", "NOKEY", good)])
    assert llm.complete_json("p") == {"files": []} and llm.last_provider == "two"
    assert [p.name for p in llm.providers] == ["one", "two"]  # providers without keys are skipped
