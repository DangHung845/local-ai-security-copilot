from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    # system_prompt từ client đã bị loại bỏ có chủ đích: client không được ghi đè luật an toàn.
    prompt: str = Field(min_length=1, max_length=32000, description="User prompt")


class Source(BaseModel):
    n: int
    source: str
    heading: str
    chunk_id: str


class ChatResponse(BaseModel):
    answer: str
    model: str | None = None
    decision: str = "allow"
    policy_category: str | None = None
    policy_reason: str | None = None
    hitl_required: bool = False
    sources: list[Source] = Field(default_factory=list)
