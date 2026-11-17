from fastapi import APIRouter, HTTPException

from app.core.config import get_settings
from app.models.chat import ChatRequest, ChatResponse
from app.services.ollama_service import (
    OllamaService,
    OllamaConnectionError,
    OllamaTimeoutError,
    OllamaResponseError,
)

router = APIRouter()
ollama_service = OllamaService()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    try:
        answer = await ollama_service.generate(
            prompt=request.prompt,
            system_prompt=request.system_prompt,
        )

        return ChatResponse(
            answer=answer,
            model=get_settings().ollama_model,
        )

    except OllamaTimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail=str(exc),
        ) from exc

    except OllamaConnectionError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

    except OllamaResponseError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc