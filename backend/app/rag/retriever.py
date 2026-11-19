"""Hybrid retrieval: BM25 (từ khóa) + dense (ngữ nghĩa), hợp nhất bằng Reciprocal Rank Fusion."""
from dataclasses import dataclass

from app.rag.chunker import Chunk
from app.rag.store import ChromaStore, IndexStore


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
                 rrf_k: int = 60, min_coverage: float = 0.3,
                 chroma: ChromaStore | None = None, bm25_candidates: int = 50,
                 chroma_candidates: int = 50, reranker=None):
        self.store, self.embedder = store, embedder
        self.chroma = chroma
        self.top_k, self.rrf_k = top_k, rrf_k
        self.min_coverage = min_coverage
        self.bm25_candidates = bm25_candidates
        self.chroma_candidates = chroma_candidates
        self.reranker = reranker

    def search(self, query: str, top_k: int | None = None) -> list[Hit]:
        k = top_k or self.top_k
        n = len(self.store.chunks)
        if n == 0:
            return []
        bm25 = self.store.bm25_fold if query.isascii() else self.store.bm25
        lex = bm25.scores(query)
        cov = bm25.coverage(query)
        lex = [x if c >= self.min_coverage else 0.0 for x, c in zip(lex, cov)]
        sem_candidates = self._dense_chroma(query)
        sem_scores = [0.0] * n
        sem_candidate_indices = set()
        for i, similarity in sem_candidates:
            sem_scores[i] = similarity
            sem_candidate_indices.add(i)

        fused = [0.0] * n

        bm25_candidate_indices = sorted(
            (i for i, score in enumerate(lex) if score > 0),
            key=lambda i: lex[i],
            reverse=True,
        )[:self.bm25_candidates]
        for rank, i in enumerate(bm25_candidate_indices, 1):
            fused[i] += 1 / (self.rrf_k + rank)

        for rank, (i, _similarity) in enumerate(sem_candidates, 1):
            if rank <= self.chroma_candidates:
                fused[i] += 1 / (self.rrf_k + rank)

        candidate_indices = {
            i for i, score in enumerate(fused) if score > 0
        }
        candidates = [
            (i, self.store.chunks[i], fused[i])
            for i in sorted(candidate_indices, key=lambda i: fused[i], reverse=True)
        ]

        if self.reranker:
            reranked = self.reranker.rerank(query, candidates, k)
        else:
            reranked = candidates[:k]

        hits = []
        for i, chunk, rrf_score in reranked:
            semantic = sem_scores[i] if i in sem_candidate_indices else None
            hits.append(Hit(chunk, rrf_score, lex[i], semantic))
        return hits

    def _dense_chroma(self, query: str) -> list[tuple[int, float]]:
        if not (self.embedder and self.chroma):
            return []
        try:
            q = self.embedder.embed([query])[0]
            chroma_hits = self.chroma.search(q, self.chroma_candidates)
        except Exception:
            return []

        by_id = {chunk.id: i for i, chunk in enumerate(self.store.chunks)}
        candidates = []
        for chunk, similarity in chroma_hits:
            i = by_id.get(chunk.id)
            if i is not None:
                candidates.append((i, similarity))
        return candidates
