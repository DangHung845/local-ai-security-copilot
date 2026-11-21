"""Kho dữ liệu RAG.

- IndexStore: danh sách chunk + 2 chỉ mục BM25 (có dấu / bỏ dấu), lưu JSON.
- VectorStore (giao diện): query(vector, k) -> [(chunk_id, cosine)].
  Hai cài đặt: ChromaStore (persistent, dùng thật) và InMemoryVectorStore (test/so sánh, không phụ thuộc).
"""
import json
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

from app.rag.bm25 import BM25
from app.rag.chunker import Chunk


class VectorStore(Protocol):
    def query(self, vector: list[float], k: int) -> list[tuple[str, float]]: ...
    def count(self) -> int: ...


class IndexStore:
    def __init__(self, chunks: list[Chunk], embed_model: str | None = None, heading_weight: int = 2):
        self.chunks = chunks
        self.embed_model = embed_model
        # heading lặp heading_weight lần: tiêu đề tài liệu khớp câu hỏi được ưu tiên hơn đoạn ngắn dày từ khóa
        docs = [f"{(c.heading + chr(10)) * heading_weight}{c.text}" for c in chunks]
        self.bm25 = BM25(docs)                    # giữ dấu
        self.bm25_fold = BM25(docs, fold=True)    # bỏ dấu, dùng khi câu hỏi gõ không dấu
        self.by_id = {c.id: i for i, c in enumerate(chunks)}

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "embed_model": self.embed_model,
            "chunks": [asdict(c) for c in self.chunks],
        }, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "IndexStore":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls([Chunk(**c) for c in d["chunks"]], d.get("embed_model"))


class InMemoryVectorStore:
    """Brute-force cosine; vector đã chuẩn hóa nên cosine = tích vô hướng."""

    def __init__(self, ids: list[str], vectors: list[list[float]]):
        if len(ids) != len(vectors):
            raise ValueError("ids và vectors phải cùng độ dài")
        self.ids, self.vectors = ids, vectors

    def query(self, vector: list[float], k: int) -> list[tuple[str, float]]:
        sims = [(i, sum(a * b for a, b in zip(vector, v))) for i, v in zip(self.ids, self.vectors)]
        return sorted(sims, key=lambda x: x[1], reverse=True)[:k]

    def count(self) -> int:
        return len(self.ids)


class ChromaStore:
    """Kho vector persistent dùng ChromaDB (cosine). Mỗi vector kèm hash nội dung để ingest tăng dần."""

    def __init__(self, persist_dir: str | Path, collection_name: str = "security_knowledge"):
        import chromadb

        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(self.persist_dir))
        self.collection = self.client.get_or_create_collection(
            name=collection_name, metadata={"hnsw:space": "cosine"})

    def reset(self) -> None:
        name = self.collection.name
        self.client.delete_collection(name)
        self.collection = self.client.create_collection(name=name, metadata={"hnsw:space": "cosine"})

    def existing_hashes(self) -> dict[str, str]:
        res = self.collection.get(include=["metadatas"])
        return {i: (m or {}).get("h", "") for i, m in zip(res["ids"], res["metadatas"])}

    def delete(self, ids: list[str]) -> None:
        for s in range(0, len(ids), 500):
            self.collection.delete(ids=ids[s:s + 500])

    def upsert(self, chunks: list[Chunk], embeddings: list[list[float]], hashes: list[str] | None = None) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("Số lượng chunk và embedding phải bằng nhau")
        for s in range(0, len(chunks), 500):  # giới hạn kích thước batch của Chroma
            cs = chunks[s:s + 500]
            self.collection.upsert(
                ids=[c.id for c in cs],
                embeddings=embeddings[s:s + 500],
                documents=[f"{c.heading}\n{c.text}" for c in cs],
                metadatas=[{"source": c.source, "heading": c.heading, "h": (hashes[s + j] if hashes else "")}
                           for j, c in enumerate(cs)],
            )

    def query(self, vector: list[float], k: int) -> list[tuple[str, float]]:
        n = self.collection.count()
        if n == 0:
            return []
        res = self.collection.query(query_embeddings=[vector], n_results=min(k, n), include=["distances"])
        return [(i, 1.0 - float(d)) for i, d in zip(res["ids"][0], res["distances"][0])]

    def count(self) -> int:
        return self.collection.count()
