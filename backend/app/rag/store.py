"""Index lưu một file JSON (chunks + embedding tùy chọn). Đủ cho vài nghìn chunk;
khi kho tri thức lớn hơn ~20k chunk thì đổi sang ChromaDB/FAISS qua cùng interface."""
import json
from dataclasses import asdict
from pathlib import Path

from app.rag.bm25 import BM25
from app.rag.chunker import Chunk


class IndexStore:
    def __init__(self, chunks: list[Chunk], embed_model: str | None = None):
        self.chunks = chunks
        self.embed_model = embed_model
        docs = [f"{c.heading}\n{c.text}" for c in chunks]
        self.bm25 = BM25(docs)                    # giữ dấu
        self.bm25_fold = BM25(docs, fold=True)    # bỏ dấu, dùng khi câu hỏi gõ không dấu

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


class ChromaStore:
    """Kho vector persistent dùng ChromaDB, giữ chunk metadata để truy xuất lại nguồn."""

    def __init__(self, persist_dir: str | Path, collection_name: str = "security_knowledge"):
        import chromadb

        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(self.persist_dir))
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def reset(self) -> None:
        name = self.collection.name
        self.client.delete_collection(name)
        self.collection = self.client.create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )

    def upsert(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("Số lượng chunk và embedding phải bằng nhau")
        if not chunks:
            return
        self.collection.upsert(
            ids=[c.id for c in chunks],
            embeddings=embeddings,
            documents=[f"{c.heading}\n{c.text}" for c in chunks],
            metadatas=[{"source": c.source, "heading": c.heading, "text": c.text} for c in chunks],
        )

    def search(self, query_embedding: list[float], top_k: int = 4) -> list[tuple[Chunk, float]]:
        if self.collection.count() == 0:
            return []
        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, self.collection.count()),
            include=["metadatas", "documents", "distances"],
        )
        hits = []
        ids = result.get("ids", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        for chunk_id, meta, distance in zip(ids, metas, distances):
            if meta is None:
                continue
            chunk = Chunk(
                id=chunk_id,
                source=str(meta.get("source", "")),
                heading=str(meta.get("heading", "")),
                text=str(meta.get("text", "")),
            )
            similarity = 1.0 - float(distance)
            hits.append((chunk, similarity))
        return hits

    def count(self) -> int:
        return self.collection.count()
