"""Three retrievers + fusion. Every ablation row comes from the same indexes, so rows are comparable."""
from __future__ import annotations

import hashlib
import random
import time
from dataclasses import asdict, dataclass

from .files import RepoFile
from .fusion import rrf
from .lexical import LexicalIndex
from .query import focus_query
from .semantic import CandidateSemantic, EmbedCache, Embedder, SemanticIndex
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
    # experimental variants; defaults reproduce the committed results
    query_mode: str = "full"      # 'full' | 'focused'
    sem_mode: str = "pooled"      # 'pooled' | 'maxchunk'
    hub_damping: bool = False

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
    gr = expand(two, graph, params.n_seed, params.max_per_seed, params.reverse_weight, params.hub_damping)
    full = rrf([(lex, 1.0), (sem, 1.0), ([p for p, _ in gr], params.graph_weight)], params.rrf_k)
    return {"bm25": r.lex, "embed": r.sem, "bm25+embed": two, "graph": gr}, full


def random_ranking(paths: list[str], seed: str) -> list[str]:
    paths = sorted(paths)
    random.Random(int(hashlib.sha1(seed.encode()).hexdigest(), 16) % 2**32).shuffle(paths)
    return paths


class Retriever:
    """scope 'all' (default, reproduces the committed results) embeds every file.

    scope 'candidates' embeds only the top `candidate_k` lexical hits per query, at `candidate_chunks` chunks
    per file, so the semantic stage costs the same on a 100-file repo and a 5,000-file repo.
    Pass prebuilt `lex` / `graph` to share them across variants in experiments.
    """

    def __init__(
        self,
        files: list[RepoFile],
        embedder: Embedder,
        cache: EmbedCache | None = None,
        scope: str = "all",
        candidate_k: int = 300,
        candidate_chunks: int = 4,
        graph_mode: str = "ast",
        lex: LexicalIndex | None = None,
        graph: ImportGraph | None = None,
    ):
        self.files = files
        self.scope, self.candidate_k = scope, candidate_k
        t0 = time.perf_counter()
        self.lex = lex or LexicalIndex(files)
        t1 = time.perf_counter()
        if scope == "candidates":
            self.sem = None
            self.cand_sem = CandidateSemantic(files, embedder, cache, candidate_chunks)
        else:
            self.sem = SemanticIndex(files, embedder, cache)  # embeds every file not already cached
            self.cand_sem = None
        t2 = time.perf_counter()
        self.graph = graph or build_graph(files, graph_mode)
        t3 = time.perf_counter()
        self.timings = {"bm25_index": t1 - t0, "embed_index": t2 - t1, "import_graph": t3 - t2}

    def retrieve(self, query: str, query_mode: str = "full", sem_mode: str = "pooled") -> Retrieved:
        q_lex, q_emb = focus_query(query) if query_mode == "focused" else (query, query)
        if self.cand_sem is None:
            return Retrieved(self.lex.search(q_lex, POOL), self.sem.search(q_emb, POOL, sem_mode))
        t0 = time.perf_counter()
        lex_big = self.lex.search(q_lex, max(POOL, self.candidate_k))
        sem = self.cand_sem.search(q_emb, [p for p, _ in lex_big[: self.candidate_k]], POOL, sem_mode)
        self.timings["embed_candidates"] = time.perf_counter() - t0
        return Retrieved(lex_big[:POOL], sem)

    def rankings(self, query: str, params: Params, seed: str = "") -> dict[str, list[str]]:
        r = self.retrieve(query, params.query_mode, params.sem_mode)
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
