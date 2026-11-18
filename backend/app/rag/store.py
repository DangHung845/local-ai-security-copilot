"""Index lưu một file JSON (chunks + embedding tùy chọn). Đủ cho vài nghìn chunk;
khi kho tri thức lớn hơn ~20k chunk thì đổi sang ChromaDB/FAISS qua cùng interface."""
import json
from dataclasses import asdict
from pathlib import Path

from app.rag.bm25 import BM25
from app.rag.chunker import Chunk


class IndexStore:
    def __init__(self, chunks: list[Chunk], embeddings: list[list[float]] | None = None,
                 embed_model: str | None = None):
        self.chunks = chunks
        self.embeddings = embeddings
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
            "embeddings": self.embeddings,
        }, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "IndexStore":
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls([Chunk(**c) for c in d["chunks"]], d.get("embeddings"), d.get("embed_model"))
