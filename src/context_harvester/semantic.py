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


def chunk_text(path: str, text: str) -> list[str]:
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
    if len(chunks) > MAX_CHUNKS:
        idx = np.linspace(0, len(chunks) - 1, MAX_CHUNKS).round().astype(int)
        chunks = [chunks[i] for i in sorted(set(idx.tolist()))]
    return [f"{path}\n{c}" for c in chunks]


class EmbedCache:
    """File-vector cache keyed by sha1(path+content), shared across snapshots of one repo."""

    def __init__(self, directory: Path | None, model: str):
        self.file = None if directory is None else Path(directory) / f"emb_{model}.npz"
        self.vecs: dict[str, np.ndarray] = {}
        self._dirty = False
        if self.file is not None and self.file.exists():
            z = np.load(self.file, allow_pickle=False)
            self.vecs = dict(zip(z["keys"].tolist(), z["vecs"]))

    def put(self, key: str, vec: np.ndarray) -> None:
        self.vecs[key] = vec
        self._dirty = True

    def flush(self) -> None:
        if self.file is None or not self._dirty:
            return
        self.file.parent.mkdir(parents=True, exist_ok=True)
        keys = np.array(list(self.vecs), dtype="U40")
        np.savez(self.file, keys=keys, vecs=np.stack(list(self.vecs.values())))
        self._dirty = False


class SemanticIndex:
    def __init__(self, files: list[RepoFile], embedder: Embedder, cache: EmbedCache | None = None):
        import faiss

        self.embedder = embedder
        self.paths = [f.path for f in files]
        cache = cache or EmbedCache(None, embedder.name)
        vecs: list[np.ndarray | None] = [cache.vecs.get(f.key) for f in files]
        todo = [i for i, v in enumerate(vecs) if v is None]
        if todo:
            texts, owner = [], []
            for i in todo:
                cs = chunk_text(files[i].path, files[i].text)
                texts.extend(cs)
                owner.extend([i] * len(cs))
            emb = embedder.encode(texts)
            owner_arr = np.array(owner)
            for i in todo:
                pooled = emb[owner_arr == i].mean(axis=0)
                pooled = pooled / (np.linalg.norm(pooled) or 1.0)
                vecs[i] = pooled.astype("float32")
                cache.put(files[i].key, vecs[i])
            cache.flush()
        self.dim = len(vecs[0]) if vecs else 0
        self._index = faiss.IndexFlatIP(self.dim) if vecs else None
        if vecs:
            self._index.add(np.stack(vecs).astype("float32"))

    def search(self, query: str, k: int = 100) -> list[tuple[str, float]]:
        if self._index is None:
            return []
        q = self.embedder.encode([query])
        scores, ids = self._index.search(q.astype("float32"), min(k, len(self.paths)))
        return [(self.paths[i], float(s)) for s, i in zip(scores[0], ids[0]) if i >= 0]
