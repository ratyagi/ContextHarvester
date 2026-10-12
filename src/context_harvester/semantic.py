"""Per-file embeddings (chunked and pooled) searched with in-process FAISS (PRD: Semantic)."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol

import numpy as np

from .files import RepoFile

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
CHUNK_CHARS = 1200
MAX_CHUNKS = 8


class Embedder(Protocol):
    name: str

    def encode(self, texts: list[str]) -> np.ndarray: ...


class MiniLMEmbedder:
    """all-MiniLM-L6-v2 run locally. Costs nothing, no network once the weights are cached."""

    name = "all-MiniLM-L6-v2"

    def __init__(self) -> None:
        self._model = None

    def encode(self, texts: list[str]) -> np.ndarray:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(MODEL_NAME)
        v = self._model.encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(v, dtype="float32")


def chunk_text(path: str, text: str, max_chunks: int = MAX_CHUNKS) -> list[str]:
    """Split on line boundaries into ~CHUNK_CHARS pieces; sample evenly (keeping the first) if too many."""
    chunks, cur, size = [], [], 0
    for line in text.splitlines():
        cur.append(line)
        size += len(line) + 1
        if size >= CHUNK_CHARS:
            chunks.append("\n".join(cur))
            cur, size = [], 0
    if cur:
        chunks.append("\n".join(cur))
    if not chunks:
        chunks = [""]
    if len(chunks) > max_chunks:
        idx = np.linspace(0, len(chunks) - 1, max_chunks).round().astype(int)
        chunks = [chunks[i] for i in sorted(set(idx.tolist()))]
    return [f"{path}\n{c}" for c in chunks]


class EmbedCache:
    """Chunk-embedding cache keyed by sha1(path+content), shared across snapshots of one repo.

    Stores every chunk vector of a file, so both the pooled file vector and per-chunk search derive from it.
    """

    def __init__(self, directory: Path | None, model: str):
        self.file = None if directory is None else Path(directory) / f"embc_{model}.npz"
        self.mats: dict[str, np.ndarray] = {}
        self._dirty = False
        if self.file is not None and self.file.exists():
            z = np.load(self.file, allow_pickle=False)
            keys, offs, mat = z["keys"].tolist(), z["offsets"], z["mat"]
            for i, k in enumerate(keys):
                self.mats[k] = mat[offs[i] : offs[i + 1]]

    def get(self, key: str) -> np.ndarray | None:
        return self.mats.get(key)

    def put(self, key: str, mat: np.ndarray) -> None:
        self.mats[key] = mat
        self._dirty = True

    def flush(self) -> None:
        if self.file is None or not self._dirty or not self.mats:
            return
        self.file.parent.mkdir(parents=True, exist_ok=True)
        keys = list(self.mats)
        offs = np.cumsum([0] + [len(self.mats[k]) for k in keys])
        np.savez(self.file, keys=np.array(keys, dtype="U64"), offsets=offs, mat=np.concatenate([self.mats[k] for k in keys]))
        self._dirty = False


CHUNK_POOL = 400  # chunk hits examined by max-chunk search before aggregating per file


class SemanticIndex:
    def __init__(self, files: list[RepoFile], embedder: Embedder, cache: EmbedCache | None = None):
        import faiss

        self._faiss = faiss
        self.embedder = embedder
        self.paths = [f.path for f in files]
        cache = cache or EmbedCache(None, embedder.name)
        mats: list[np.ndarray | None] = [cache.get(f.key) for f in files]
        todo = [i for i, m in enumerate(mats) if m is None]
        if todo:
            texts, owner = [], []
            for i in todo:
                cs = chunk_text(files[i].path, files[i].text)
                texts.extend(cs)
                owner.extend([i] * len(cs))
            emb = embedder.encode(texts).astype("float32")
            owner_arr = np.array(owner)
            for i in todo:
                mats[i] = emb[owner_arr == i]
                cache.put(files[i].key, mats[i])
            cache.flush()
        self.dim = mats[0].shape[1] if mats else 0
        pooled = []
        for m in mats:
            v = m.mean(axis=0)
            pooled.append((v / (np.linalg.norm(v) or 1.0)).astype("float32"))
        self._index = faiss.IndexFlatIP(self.dim) if mats else None
        if mats:
            self._index.add(np.stack(pooled))
        self._chunk_mats = mats
        self._chunk_index = None
        self._chunk_owner = None

    def _build_chunk_index(self) -> None:
        self._chunk_owner = np.concatenate([np.full(len(m), i) for i, m in enumerate(self._chunk_mats)])
        self._chunk_index = self._faiss.IndexFlatIP(self.dim)
        self._chunk_index.add(np.concatenate(self._chunk_mats).astype("float32"))

    def search(self, query: str, k: int = 100, mode: str = "pooled") -> list[tuple[str, float]]:
        """mode 'pooled': one mean vector per file. 'maxchunk': a file scores as its best-matching chunk."""
        if self._index is None:
            return []
        q = self.embedder.encode([query]).astype("float32")
        if mode == "maxchunk":
            if self._chunk_index is None:
                self._build_chunk_index()
            scores, ids = self._chunk_index.search(q, min(CHUNK_POOL, self._chunk_index.ntotal))
            best: dict[int, float] = {}
            for s, i in zip(scores[0], ids[0]):
                if i >= 0:
                    f = int(self._chunk_owner[i])
                    best[f] = max(best.get(f, -1e9), float(s))
            ranked = sorted(best.items(), key=lambda kv: (-kv[1], self.paths[kv[0]]))
            return [(self.paths[f], s) for f, s in ranked[:k]]
        scores, ids = self._index.search(q, min(k, len(self.paths)))
        return [(self.paths[i], float(s)) for s, i in zip(scores[0], ids[0]) if i >= 0]


def chunk_key(f: RepoFile, max_chunks: int) -> str:
    """Cache key. The default cap keeps the plain file key so existing caches stay valid."""
    return f.key if max_chunks == MAX_CHUNKS else f"{f.key}:c{max_chunks}"


class CandidateSemantic:
    """Semantic search over a candidate subset only, so embedding cost is O(candidates), not O(repo size).

    Used on a cold run of a large repo: embed only the files lexical retrieval already considers plausible
    (plus anything cached), with a lower chunk cap, then search them with FAISS. Whether this costs recall is
    measured on dev instances before it is adopted.
    """

    def __init__(self, files: list[RepoFile], embedder: Embedder, cache: EmbedCache | None = None, max_chunks: int = 4):
        import faiss

        self._faiss = faiss
        self.by_path = {f.path: f for f in files}
        self.embedder = embedder
        self.cache = cache or EmbedCache(None, embedder.name)
        self.max_chunks = max_chunks
        self.last_new_chunks = 0  # chunks actually embedded by the last search (0 when fully cached)
        self.last_total_chunks = 0  # chunks the last search needed, cached or not (cold cost)

    def _mats(self, paths: list[str]) -> list[np.ndarray]:
        files = [self.by_path[p] for p in paths]
        todo = [f for f in files if self.cache.get(chunk_key(f, self.max_chunks)) is None]
        texts, owner = [], []
        for i, f in enumerate(todo):
            cs = chunk_text(f.path, f.text, self.max_chunks)
            texts.extend(cs)
            owner.extend([i] * len(cs))
        if texts:
            emb = self.embedder.encode(texts).astype("float32")
            owner_arr = np.array(owner)
            for i, f in enumerate(todo):
                self.cache.put(chunk_key(f, self.max_chunks), emb[owner_arr == i])
            self.cache.flush()
        self.last_new_chunks = len(texts)
        mats = [self.cache.get(chunk_key(f, self.max_chunks)) for f in files]
        self.last_total_chunks = int(sum(len(m) for m in mats))
        return mats

    def search(self, query: str, candidates: list[str], k: int = 100, mode: str = "pooled") -> list[tuple[str, float]]:
        if not candidates:
            return []
        mats = self._mats(candidates)
        q = self.embedder.encode([query]).astype("float32")
        if mode == "maxchunk":
            scores = [float((m @ q[0]).max()) for m in mats]
            order = sorted(range(len(candidates)), key=lambda i: (-scores[i], candidates[i]))
            return [(candidates[i], scores[i]) for i in order[:k]]
        pooled = np.stack([(lambda v: (v / (np.linalg.norm(v) or 1.0)))(m.mean(axis=0)) for m in mats]).astype("float32")
        index = self._faiss.IndexFlatIP(pooled.shape[1])
        index.add(pooled)
        sc, ids = index.search(q, min(k, len(candidates)))
        return [(candidates[i], float(x)) for x, i in zip(sc[0], ids[0]) if i >= 0]
