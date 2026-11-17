from fastapi import FastAPI

from app.api.routes.chat import router as chat_router

app = FastAPI(
    title="Local AI Security Copilot",
    description="A local AI-powered cybersecurity assistant.",
    version="0.1.0",
)


@app.get("/health")
async def health():
    return {"status": "ok"}


app.include_router(
    chat_router,
    prefix="/api/v1",
    tags=["Chat"],
)