import math


class OllamaEmbedder:
    """Embedding qua Ollama /api/embed (vd: bge-m3). Chạy local, không cần Internet sau khi pull model."""

    def __init__(self, base_url: str, model: str = "bge-m3", timeout: float = 120.0):
        self.url = f"{base_url.rstrip('/')}/api/embed"
        self.model = model
        self.timeout = timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx  # import trễ để module dùng được khi chưa cài httpx

        r = httpx.post(self.url, json={"model": self.model, "input": texts}, timeout=self.timeout)
        r.raise_for_status()
        return [_unit(v) for v in r.json()["embeddings"]]


def _unit(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]
