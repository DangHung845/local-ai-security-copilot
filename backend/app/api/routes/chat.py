import time

from fastapi import APIRouter, HTTPException

from app.core.audit import AuditLogger
from app.core.config import get_settings
from app.core.prompts import BASE_SYSTEM_PROMPT, DENY_MESSAGES, REDIRECT_ADDENDUM
from app.models.chat import ChatRequest, ChatResponse
from app.policy import Decision, PolicyEngine
from app.policy.engine import is_vietnamese
from app.services.ollama_service import (
    OllamaConnectionError,
    OllamaResponseError,
    OllamaService,
    OllamaTimeoutError,
)

router = APIRouter()
ollama_service = OllamaService()
policy_engine = PolicyEngine()


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

    start = time.perf_counter()
    try:
        answer = await ollama_service.generate(prompt=request.prompt, system_prompt=system_prompt)
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
    )
