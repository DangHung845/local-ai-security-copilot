"""Hybrid retrieval: BM25 (từ khóa) + dense (ngữ nghĩa), hợp nhất bằng Reciprocal Rank Fusion.

- Chỉ ứng viên thật sự do BM25 / dense trả về mới tham gia RRF
- Ứng viên dense dưới ngưỡng cosine bị loại trước khi hợp nhất
- Giới hạn số chunk mỗi tài liệu để top-k không bị một cheat sheet chiếm hết
- Lỗi dense (Ollama/Chroma/index lệch phiên bản) được báo ra, không nuốt im lặng
"""
import logging
from dataclasses import dataclass, field

from app.rag.chunker import Chunk
from app.rag.store import IndexStore, VectorStore

log = logging.getLogger("rag")


@dataclass
class Hit:
    chunk: Chunk
    score: float                 # điểm RRF
    lexical: float               # điểm BM25 gốc (0 nếu không qua cổng coverage)
    semantic: float | None       # cosine, None nếu chunk không nằm trong ứng viên dense


@dataclass
class SearchResult:
    hits: list[Hit]
    dense_used: bool = False
    dense_error: str | None = None
    top_semantic: float | None = None   # cosine cao nhất, kể cả khi dưới ngưỡng (để hiệu chỉnh)
    notes: list[str] = field(default_factory=list)


class HybridRetriever:
    def __init__(self, store: IndexStore, embedder=None, vectors: VectorStore | None = None,
                 top_k: int = 4, rrf_k: int = 60, min_semantic: float = 0.5, min_coverage: float = 0.3,
                 pool: int = 50, max_per_source: int = 2, w_lex: float = 1.0, w_dense: float = 1.0):
        self.store, self.embedder, self.vectors = store, embedder, vectors
        self.top_k, self.rrf_k, self.min_semantic, self.min_coverage = top_k, rrf_k, min_semantic, min_coverage
        self.pool, self.max_per_source, self.w_lex, self.w_dense = pool, max_per_source, w_lex, w_dense

    def search(self, query: str, top_k: int | None = None) -> list[Hit]:
        return self.search_detailed(query, top_k).hits

    def search_detailed(self, query: str, top_k: int | None = None) -> SearchResult:
        k = top_k or self.top_k
        res = SearchResult(hits=[])
        if not query.strip() or not self.store.chunks:
            return res

        lex = self._lexical(query)                                  # {idx: bm25}
        sem_all, res.dense_error = self._dense(query)               # {idx: cosine} | None
        res.dense_used = sem_all is not None
        if sem_all:
            res.top_semantic = max(sem_all.values())
        sem = {i: s for i, s in (sem_all or {}).items() if s >= self.min_semantic}

        fused: dict[int, float] = {}
        for r, i in enumerate(sorted(lex, key=lex.get, reverse=True), 1):
            fused[i] = fused.get(i, 0.0) + self.w_lex / (self.rrf_k + r)
        for r, i in enumerate(sorted(sem, key=sem.get, reverse=True), 1):
            fused[i] = fused.get(i, 0.0) + self.w_dense / (self.rrf_k + r)

        per_source: dict[str, int] = {}
        for i in sorted(fused, key=lambda i: (fused[i], sem.get(i, 0.0)), reverse=True):
            c = self.store.chunks[i]
            if self.max_per_source and per_source.get(c.source, 0) >= self.max_per_source:
                continue
            per_source[c.source] = per_source.get(c.source, 0) + 1
            res.hits.append(Hit(c, fused[i], lex.get(i, 0.0), sem.get(i)))
            if len(res.hits) == k:
                break
        return res

    def _lexical(self, query: str) -> dict[int, float]:
        bm25 = self.store.bm25_fold if query.isascii() else self.store.bm25
        scores, cov = bm25.scores(query), bm25.coverage(query)
        cand = [(s, i) for i, (s, c) in enumerate(zip(scores, cov)) if s > 0 and c >= self.min_coverage]
        cand.sort(reverse=True)
        return {i: s for s, i in cand[: self.pool]}

    def _dense(self, query: str) -> tuple[dict[int, float] | None, str | None]:
        if not (self.embedder and self.vectors):
            return None, None
        try:
            q = self.embedder.embed_query(query) if hasattr(self.embedder, "embed_query") else self.embedder.embed([query])[0]
            pairs = self.vectors.query(q, self.pool)
        except Exception as exc:  # Ollama/Chroma lỗi -> rơi về BM25 nhưng báo rõ
            log.warning("Dense retrieval lỗi, dùng BM25: %s", exc)
            return None, f"{type(exc).__name__}: {exc}"
        out = {self.store.by_id[cid]: sim for cid, sim in pairs if cid in self.store.by_id}
        if pairs and not out:
            msg = "Vector store lệch với index JSON (id không khớp): chạy lại scripts/ingest.py --rebuild"
            log.error(msg)
            return None, msg
        return out, None
