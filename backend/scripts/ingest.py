"""Nạp knowledge_base/**/*.md vào index JSON (BM25) và ChromaDB (dense).

    python scripts/ingest.py             # tăng dần: chỉ embed phần mới/đổi
    python scripts/ingest.py --rebuild   # xóa sạch và embed lại (bắt buộc khi đổi model embedding)
    python scripts/ingest.py --no-dense  # chỉ BM25 (không cần Ollama)
Mặc định lấy cấu hình từ .env giống server nên ingest và server luôn trỏ cùng một index.
"""
import argparse
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.rag.embedder import OllamaEmbedder  # noqa: E402
from app.rag.ingest import load_kb, plan  # noqa: E402
from app.rag.store import ChromaStore, IndexStore  # noqa: E402


def main() -> None:
    cfg = get_settings()
    ap = argparse.ArgumentParser()
    ap.add_argument("--knowledge-dir", default=str(BACKEND_DIR.parent / "knowledge_base"))
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--no-dense", action="store_true")
    ap.add_argument("--batch", type=int, default=16)
    args = ap.parse_args()

    kb = Path(args.knowledge_dir)
    if not kb.exists():
        raise SystemExit(f"Không thấy thư mục tri thức: {kb}")
    chunks = load_kb(kb)
    print(f"{len(chunks)} chunk từ {kb}")

    old_model = None
    try:
        old_model = IndexStore.load(cfg.rag_index_path).embed_model
    except (OSError, ValueError):
        pass
    model = None if args.no_dense else cfg.rag_embed_model
    IndexStore(chunks, embed_model=model).save(cfg.rag_index_path)
    print(f"JSON index: {cfg.rag_index_path}")
    if args.no_dense:
        return

    store = ChromaStore(cfg.rag_chroma_dir, cfg.rag_chroma_collection)
    if args.rebuild or (old_model and old_model != model):
        why = "--rebuild" if args.rebuild else f"đổi model {old_model} -> {model}"
        print(f"Xóa sạch ChromaDB ({why})")
        store.reset()
    todo, hashes, stale = plan(chunks, store.existing_hashes(), model, cfg.rag_embed_doc_prefix)
    print(f"Cần embed {len(todo)}, giữ nguyên {len(chunks) - len(todo)}, xóa {len(stale)} vector cũ")
    if stale:
        store.delete(stale)

    emb = OllamaEmbedder(cfg.ollama_base_url, model, cfg.ollama_timeout, cfg.rag_embed_query_prefix,
                         cfg.rag_embed_doc_prefix, cfg.rag_embed_keep_alive, cfg.rag_embed_num_gpu)
    t0 = time.time()
    for s in range(0, len(todo), args.batch):
        batch = todo[s:s + args.batch]
        vecs = emb.embed_documents([f"{c.heading}\n{c.text}" for c in batch])
        store.upsert(batch, vecs, hashes[s:s + args.batch])   # ghi từng batch: ngắt giữa chừng vẫn chạy tiếp được
        done = s + len(batch)
        print(f"  {done}/{len(todo)}  ({done / max(time.time() - t0, 1e-6):.1f} chunk/s)", end="\r")
    print(f"\nChromaDB: {cfg.rag_chroma_dir} ({store.count()} vector, model {model})")


if __name__ == "__main__":
    main()
