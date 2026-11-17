from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    prompt: str = Field(
        min_length=1,
        max_length=32000,
        description="User prompt",
    )
    system_prompt: str | None = None


class ChatResponse(BaseModel):
    answer: str
    model: str
