"""Endpoint debug RAG: xem trạng thái, thử truy vấn kèm điểm BM25/cosine, nạp lại index."""
import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.routes import chat as chat_module

router = APIRouter()


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=4, ge=1, le=20)


@router.get("/rag/status")
async def rag_status():
    return chat_module.get_status_and_retriever()[1]


@router.post("/rag/search")
async def rag_search(req: SearchRequest):
    retriever = chat_module.get_retriever()
    if retriever is None:
        raise HTTPException(status_code=503, detail="RAG chưa sẵn sàng: xem /api/v1/rag/status")
    r = await asyncio.to_thread(retriever.search_detailed, req.query, req.top_k)
    return {
        "dense_used": r.dense_used,
        "dense_error": r.dense_error,
        "top_semantic": r.top_semantic,
        "hits": [
            {"chunk_id": h.chunk.id, "heading": h.chunk.heading, "rrf": round(h.score, 5),
             "bm25": round(h.lexical, 2), "cosine": None if h.semantic is None else round(h.semantic, 3),
             "preview": h.chunk.text[:200]}
            for h in r.hits
        ],
    }


@router.post("/rag/reload")
async def rag_reload():
    chat_module.reload_retriever()
    return chat_module.get_status_and_retriever()[1]
