"""Ingest tăng dần: chỉ embed chunk mới hoặc đã đổi nội dung; xóa vector của chunk không còn."""
import hashlib
from pathlib import Path

from app.rag.chunker import Chunk, chunk_markdown


def load_kb(directory: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for f in sorted(directory.rglob("*.md")):
        chunks += chunk_markdown(f.read_text(encoding="utf-8", errors="replace"), str(f.relative_to(directory)))
    return chunks


def content_hash(c: Chunk, embed_model: str, doc_prefix: str = "") -> str:
    raw = f"{embed_model}\x00{doc_prefix}\x00{c.heading}\x00{c.text}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def plan(chunks: list[Chunk], existing: dict[str, str], embed_model: str, doc_prefix: str = ""):
    """-> (chunks cần embed, hash tương ứng, id cũ cần xóa)."""
    todo, hashes = [], []
    for c in chunks:
        h = content_hash(c, embed_model, doc_prefix)
        if existing.get(c.id) != h:
            todo.append(c)
            hashes.append(h)
    stale = sorted(set(existing) - {c.id for c in chunks})
    return todo, hashes, stale
