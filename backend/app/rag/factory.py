"""Dựng retriever từ Settings. Mọi lỗi dense được ghi log để biết vì sao đang rơi về BM25."""
import logging

from app.rag.embedder import OllamaEmbedder
from app.rag.retriever import HybridRetriever
from app.rag.store import ChromaStore, IndexStore

log = logging.getLogger("rag")


def build_retriever(cfg) -> tuple[HybridRetriever | None, dict]:
    """Trả (retriever | None, status). status dùng cho /rag/status."""
    status: dict = {"enabled": cfg.rag_enabled, "index": cfg.rag_index_path, "chunks": 0,
                    "vectors": 0, "embed_model": None, "dense": False, "problems": []}
    if not cfg.rag_enabled:
        return None, status
    try:
        store = IndexStore.load(cfg.rag_index_path)
    except (OSError, ValueError) as exc:
        status["problems"].append(f"Không đọc được index JSON ({exc}); chạy scripts/ingest.py")
        log.warning(status["problems"][-1])
        return None, status
    status.update(chunks=len(store.chunks), embed_model=store.embed_model)

    embedder = vectors = None
    if cfg.rag_use_embeddings:
        try:
            vs = ChromaStore(cfg.rag_chroma_dir, cfg.rag_chroma_collection)
            status["vectors"] = vs.count()
            if vs.count() == 0:
                status["problems"].append("ChromaDB rỗng: chạy scripts/ingest.py")
            elif store.embed_model and store.embed_model != cfg.rag_embed_model:
                status["problems"].append(
                    f"Index dựng bằng '{store.embed_model}' nhưng RAG_EMBED_MODEL='{cfg.rag_embed_model}': "
                    "vector không so sánh được, chạy lại ingest --rebuild")
            else:
                vectors = vs
                embedder = OllamaEmbedder(
                    cfg.ollama_base_url, store.embed_model or cfg.rag_embed_model, cfg.ollama_timeout,
                    cfg.rag_embed_query_prefix, cfg.rag_embed_doc_prefix,
                    cfg.rag_embed_keep_alive, cfg.rag_embed_num_gpu)
                status["dense"] = True
        except Exception as exc:  # chromadb chưa cài / thư mục hỏng
            status["problems"].append(f"ChromaDB lỗi: {type(exc).__name__}: {exc}")
    for p in status["problems"]:
        log.warning(p)
    retriever = HybridRetriever(
        store, embedder, vectors, top_k=cfg.rag_top_k, min_semantic=cfg.rag_min_semantic,
        min_coverage=cfg.rag_min_coverage, pool=cfg.rag_candidate_pool,
        max_per_source=cfg.rag_max_per_source)
    return retriever, status
