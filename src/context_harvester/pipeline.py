"""Three retrievers + fusion. Every ablation row comes from the same indexes, so rows are comparable."""
from __future__ import annotations

import hashlib
import random
from dataclasses import asdict, dataclass

from .files import RepoFile
from .fusion import rrf
from .lexical import LexicalIndex
from .semantic import EmbedCache, Embedder, SemanticIndex
from .structural import ImportGraph, build_graph, expand

METHODS = ["random", "bm25", "embed", "bm25+embed", "full"]
POOL = 100  # candidates each retriever contributes before fusion


@dataclass
class Params:
    rrf_k: int = 60
    graph_weight: float = 0.5  # structural list weighs below direct matches (PRD)
    n_seed: int = 10
    max_per_seed: int = 6
    reverse_weight: float = 0.5

    def __post_init__(self):
        # pandas round-trips tuned ints as floats (20.0); these are used as k and slice bounds
        self.rrf_k, self.n_seed, self.max_per_seed = int(self.rrf_k), int(self.n_seed), int(self.max_per_seed)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Retrieved:
    """The param-independent part of a retrieval run: the two text rankings."""
    lex: list[tuple[str, float]]
    sem: list[tuple[str, float]]


def fuse(r: Retrieved, graph: ImportGraph, params: Params):
    """Returns (signals, full) where signals has bm25/embed/bm25+embed/graph lists and full is the fused list."""
    lex, sem = [p for p, _ in r.lex], [p for p, _ in r.sem]
    two = rrf([(lex, 1.0), (sem, 1.0)], params.rrf_k)
    gr = expand(two, graph, params.n_seed, params.max_per_seed, params.reverse_weight)
    full = rrf([(lex, 1.0), (sem, 1.0), ([p for p, _ in gr], params.graph_weight)], params.rrf_k)
    return {"bm25": r.lex, "embed": r.sem, "bm25+embed": two, "graph": gr}, full


def random_ranking(paths: list[str], seed: str) -> list[str]:
    paths = sorted(paths)
    random.Random(int(hashlib.sha1(seed.encode()).hexdigest(), 16) % 2**32).shuffle(paths)
    return paths


class Retriever:
    def __init__(self, files: list[RepoFile], embedder: Embedder, cache: EmbedCache | None = None):
        self.files = files
        self.lex = LexicalIndex(files)
        self.sem = SemanticIndex(files, embedder, cache)
        self.graph = build_graph(files)

    def retrieve(self, query: str) -> Retrieved:
        return Retrieved(self.lex.search(query, POOL), self.sem.search(query, POOL))

    def rankings(self, query: str, params: Params, seed: str = "") -> dict[str, list[str]]:
        r = self.retrieve(query)
        return rankings_from(r, self.graph, params, [f.path for f in self.files], seed)


def rankings_from(r: Retrieved, graph: ImportGraph, params: Params, all_paths: list[str], seed: str) -> dict[str, list[str]]:
    signals, full = fuse(r, graph, params)
    return {
        "random": random_ranking(all_paths, seed),
        "bm25": [p for p, _ in r.lex],
        "embed": [p for p, _ in r.sem],
        "bm25+embed": [p for p, _ in signals["bm25+embed"]],
        "full": [p for p, _ in full],
    }
