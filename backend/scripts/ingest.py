"""Ingest Markdown knowledge files into BM25/JSON and ChromaDB."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.rag.chunker import Chunk, chunk_markdown
from app.rag.embedder import OllamaEmbedder
from app.rag.store import ChromaStore, IndexStore


def read_markdown_files(directory: Path) -> list[tuple[str, str]]:
    return [
        (str(path.relative_to(directory)), path.read_text(encoding="utf-8", errors="replace"))
        for path in sorted(directory.rglob("*.md"))
        if path.is_file()
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest knowledge base into RAG stores")
    parser.add_argument("--knowledge-dir", default=str(BACKEND_DIR.parent / "knowledge_base"))
    parser.add_argument("--index", default=str(BACKEND_DIR / "data" / "rag_index.json"))
    parser.add_argument("--chroma-dir", default=str(BACKEND_DIR / "data" / "chroma"))
    parser.add_argument("--collection", default="security_knowledge")
    parser.add_argument("--ollama-url", default="http://localhost:11434")
    parser.add_argument("--embed-model", default="bge-m3")
    args = parser.parse_args()

    knowledge_dir = Path(args.knowledge_dir)
    if not knowledge_dir.exists():
        raise SystemExit(f"Knowledge base directory not found: {knowledge_dir}")

    chunks: list[Chunk] = []
    for source, text in read_markdown_files(knowledge_dir):
        chunks.extend(chunk_markdown(text, source))

    embedder = OllamaEmbedder(args.ollama_url, args.embed_model)
    embeddings: list[list[float]] = []
    batch_size = 32
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start:start + batch_size]
        documents = [f"{chunk.heading}\n{chunk.text}" for chunk in batch]
        embeddings.extend(embedder.embed(documents))

    index = IndexStore(chunks, embed_model=args.embed_model)
    index.save(args.index)

    chroma = ChromaStore(args.chroma_dir, args.collection)
    chroma.reset()
    if chunks:
        chroma.upsert(chunks, embeddings)

    print(f"Ingested {len(chunks)} chunks from {knowledge_dir}")
    print(f"JSON index: {args.index}")
    print(f"ChromaDB: {args.chroma_dir} ({chroma.count()} vectors)")


if __name__ == "__main__":
    main()
