import asyncio
import time
from functools import lru_cache

from fastapi import APIRouter, HTTPException

from app.core.audit import AuditLogger
from app.core.config import get_settings
from app.core.prompts import (
    BASE_SYSTEM_PROMPT,
    DENY_MESSAGES,
    RAG_ADDENDUM,
    REDIRECT_ADDENDUM,
    build_rag_prompt,
)
from app.models.chat import ChatRequest, ChatResponse, Source
from app.policy import Decision, PolicyEngine
from app.policy.engine import is_vietnamese
from app.rag import HybridRetriever, IndexStore
from app.rag.embedder import OllamaEmbedder
from app.services.ollama_service import (
    OllamaConnectionError,
    OllamaResponseError,
    OllamaService,
    OllamaTimeoutError,
)

router = APIRouter()
ollama_service = OllamaService()
policy_engine = PolicyEngine()


@lru_cache
def get_retriever() -> HybridRetriever | None:
    cfg = get_settings()
    if not cfg.rag_enabled:
        return None
    try:
        store = IndexStore.load(cfg.rag_index_path)
    except (OSError, ValueError):
        return None  # chưa chạy scripts/ingest.py -> chat không RAG
    embedder = None
    if cfg.rag_use_embeddings and store.embeddings:
        embedder = OllamaEmbedder(cfg.ollama_base_url, store.embed_model or cfg.rag_embed_model, cfg.ollama_timeout)
    return HybridRetriever(store, embedder, cfg.rag_top_k, min_semantic=cfg.rag_min_semantic)


def _audit() -> AuditLogger:
    return AuditLogger(get_settings().audit_log_path)


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    audit = _audit()
    policy = policy_engine.evaluate(request.prompt)
    audit.log(
        "policy_decision", request.prompt,
        decision=policy.decision.value, category=policy.category,
        rules=list(policy.matched_rules), hitl_required=policy.hitl_required,
    )

    if policy.decision is Decision.DENY:
        lang = "vi" if is_vietnamese(request.prompt) else "en"
        return ChatResponse(
            answer=DENY_MESSAGES[lang].format(reason=policy.reason),
            decision=policy.decision.value,
            policy_category=policy.category,
            policy_reason=policy.reason,
        )

    system_prompt = BASE_SYSTEM_PROMPT
    if policy.decision is Decision.REDIRECT:
        system_prompt += REDIRECT_ADDENDUM

    prompt, hits = request.prompt, []
    retriever = get_retriever()
    if retriever:
        # search có thể gọi HTTP (embedding) nên chạy ở thread riêng để không chặn event loop
        hits = await asyncio.to_thread(retriever.search, request.prompt)
        if hits:
            prompt = build_rag_prompt(request.prompt, hits)
            system_prompt += RAG_ADDENDUM
        audit.log("retrieval", request.prompt, chunk_ids=[h.chunk.id for h in hits])
    sources = [
        Source(n=i, source=h.chunk.source, heading=h.chunk.heading, chunk_id=h.chunk.id)
        for i, h in enumerate(hits, 1)
    ]

    start = time.perf_counter()
    try:
        answer = await ollama_service.generate(prompt=prompt, system_prompt=system_prompt)
    except OllamaTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except OllamaConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except OllamaResponseError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    audit.log(
        "llm_response", request.prompt,
        model=get_settings().ollama_model,
        latency_ms=int((time.perf_counter() - start) * 1000),
        answer_chars=len(answer),
    )
    return ChatResponse(
        answer=answer,
        model=get_settings().ollama_model,
        decision=policy.decision.value,
        policy_category=policy.category,
        policy_reason=policy.reason,
        hitl_required=policy.hitl_required,
        sources=sources,
    )
