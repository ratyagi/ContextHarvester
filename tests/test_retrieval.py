from context_harvester.files import RepoFile, list_files
from context_harvester.fusion import rrf
from context_harvester.lexical import LexicalIndex, tokenize
from context_harvester.metrics import recall_at_budget, recall_at_k, tokens_to_all
from context_harvester.pipeline import Params, Retriever
from context_harvester.snapshot import worktree
from context_harvester.structural import build_graph, expand
from context_harvester.tokens import count_tokens


def rf(path, text):
    return RepoFile(path, text, count_tokens(text))


def test_tokenize_splits_identifiers_and_keeps_compound():
    t = tokenize("parseDate parse_date_range")
    assert {"parse", "date", "parsedate", "range", "parse_date_range"} <= set(t)


def test_bm25_ranks_matching_file_first():
    files = [rf("a/parser.py", "def parse_date(s): validate date string")] + [rf(f"a/other{i}.py", f"def render_{i}(html): pass") for i in range(6)]
    assert LexicalIndex(files).search("date validation fails", 5)[0][0] == "a/parser.py"


def test_rrf_prefers_agreement_and_is_deterministic():
    out = rrf([(["a", "b", "c"], 1.0), (["b", "a", "d"], 1.0), (["b", "c"], 1.0)], 60)
    assert out[0][0] == "b" and out == rrf([(["a", "b", "c"], 1.0), (["b", "a", "d"], 1.0), (["b", "c"], 1.0)], 60)


def test_import_graph_resolves_absolute_relative_and_src_layout():
    files = [
        rf("src/pkg/__init__.py", ""),
        rf("src/pkg/api.py", "from pkg.core import Engine\nfrom . import util\nfrom .util import helper\n"),
        rf("src/pkg/core.py", "import os\nclass Engine: pass\n"),
        rf("src/pkg/util.py", "def helper(): pass\n"),
    ]
    g = build_graph(files)
    assert g.forward["src/pkg/api.py"] == {"src/pkg/core.py", "src/pkg/util.py"}
    assert g.reverse["src/pkg/core.py"] == {"src/pkg/api.py"}


def test_graph_expansion_is_one_hop_and_surfaces_unnamed_file():
    files = [rf("m/a.py", "from m.b import B\n"), rf("m/b.py", "from m.c import C\nclass B: pass\n"), rf("m/c.py", "class C: pass\n")]
    out = expand([("m/a.py", 1.0)], build_graph(files))
    assert [p for p, _ in out] == ["m/b.py"]  # c is two hops away


def test_graph_neighbors_weigh_less_than_direct(embedder):
    files = [rf("m/a.py", "def widget_frobnicate(): pass\nfrom m.b import B\n"), rf("m/b.py", "class B: pass\n"), rf("m/z.py", "x = 1\n")]
    r = Retriever(files, embedder)
    ranks = r.rankings("widget frobnicate", Params())
    assert ranks["full"][0] == "m/a.py" and "m/b.py" in ranks["full"]


def test_recall_metrics():
    ranked, gold = ["a", "b", "c", "d"], {"b", "d", "x"}
    tok = {"a": 100, "b": 100, "c": 100, "d": 100}
    assert recall_at_k(ranked, gold, 2) == 1 / 3 and recall_at_k(ranked, gold, 4) == 2 / 3
    assert recall_at_budget(ranked, gold, tok, 250) == 1 / 3
    assert tokens_to_all(ranked, {"b", "d"}, tok) == 400.0
    assert tokens_to_all(ranked, gold, tok) != tokens_to_all(ranked, gold, tok)  # NaN: x never appears


def test_end_to_end_on_synthetic_repo(fixrepo, embedder):
    repo, a, _ = fixrepo
    with worktree(repo, a) as wt:
        files = list_files(wt)
    ranks = Retriever(files, embedder).rankings("parse_date does not validate the date string", Params(), "x")
    assert ranks["bm25"][0] == "pkg/parser.py" and ranks["full"][0] == "pkg/parser.py"
    assert "pkg/tokens.py" in ranks["full"]  # reached through the import graph


def test_params_from_float_json_work_as_ints(embedder):
    """Regression: tuned_params.json held 20.0/10.0, which crashed slicing inside expand()."""
    files = [rf("m/a.py", "def widget_frobnicate(): pass\nfrom m.b import B\n"), rf("m/b.py", "class B: pass\n")]
    p = Params(**{"rrf_k": 20.0, "graph_weight": 0.75, "n_seed": 10.0, "max_per_seed": 10.0, "reverse_weight": 0.5})
    assert isinstance(p.n_seed, int) and isinstance(p.max_per_seed, int) and isinstance(p.rrf_k, int)
    assert Retriever(files, embedder).rankings("widget frobnicate", p)["full"][0] == "m/a.py"
