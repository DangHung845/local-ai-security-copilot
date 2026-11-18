"""Hybrid retrieval: BM25 (từ khóa) + dense (ngữ nghĩa), hợp nhất bằng Reciprocal Rank Fusion."""
from dataclasses import dataclass

from app.rag.chunker import Chunk
from app.rag.store import IndexStore


@dataclass
class Hit:
    chunk: Chunk
    score: float       # điểm RRF
    lexical: float     # điểm BM25 gốc
    semantic: float | None  # cosine, None nếu không dùng dense


def _ranks(scores: list[float]) -> dict[int, int]:
    order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
    return {i: r for r, i in enumerate(order, 1)}


class HybridRetriever:
    def __init__(self, store: IndexStore, embedder=None, top_k: int = 4,
                 rrf_k: int = 60, min_semantic: float = 0.5, min_coverage: float = 0.3):
        self.store, self.embedder = store, embedder
        self.top_k, self.rrf_k, self.min_semantic = top_k, rrf_k, min_semantic
        self.min_coverage = min_coverage

    def search(self, query: str, top_k: int | None = None) -> list[Hit]:
        k = top_k or self.top_k
        n = len(self.store.chunks)
        if n == 0:
            return []
        bm25 = self.store.bm25_fold if query.isascii() else self.store.bm25
        lex = bm25.scores(query)
        cov = bm25.coverage(query)
        lex = [x if c >= self.min_coverage else 0.0 for x, c in zip(lex, cov)]
        sem = self._dense(query)
        fused = [0.0] * n
        for i, r in _ranks(lex).items():
            if lex[i] > 0:
                fused[i] += 1 / (self.rrf_k + r)
        if sem is not None:
            for i, r in _ranks(sem).items():
                fused[i] += 1 / (self.rrf_k + r)
        hits = []
        for i in sorted(range(n), key=lambda i: fused[i], reverse=True):
            relevant = lex[i] > 0 or (sem is not None and sem[i] >= self.min_semantic)
            if relevant and fused[i] > 0:
                hits.append(Hit(self.store.chunks[i], fused[i], lex[i], sem[i] if sem else None))
            if len(hits) == k:
                break
        return hits

    def _dense(self, query: str) -> list[float] | None:
        if not (self.embedder and self.store.embeddings):
            return None
        try:
            q = self.embedder.embed([query])[0]
        except Exception:  # Ollama/mạng lỗi (httpx.HTTPError, KeyError...) -> rơi về BM25
            return None
        return [sum(a * b for a, b in zip(q, d)) for d in self.store.embeddings]
