from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Mặc định localhost; nếu Ollama chạy ở Windows host (WSL), đặt OLLAMA_BASE_URL trong .env
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    ollama_timeout: float = 120.0
    ollama_num_ctx: int = 8192
    audit_log_path: str = "logs/audit.jsonl"

    rag_enabled: bool = True
    rag_index_path: str = "data/rag_index.json"
    rag_embed_model: str = "bge-m3"
    rag_use_embeddings: bool = True
    rag_top_k: int = 4
    rag_min_semantic: float = 0.5
    rag_chroma_dir: str = "data/chroma"
    rag_chroma_collection: str = "security_knowledge"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
