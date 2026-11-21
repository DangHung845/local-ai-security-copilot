import math
import time


class OllamaEmbedder:
    """Embedding qua Ollama /api/embed (vd: bge-m3).

    query_prefix/doc_prefix: để trống với bge-m3; model E5 cần "query: " và "passage: ".
    keep_alive: giữ model embedding trong bộ nhớ để lần hỏi sau không phải nạp lại.
    num_gpu: đặt 0 để chạy embedding trên CPU, tránh tranh VRAM với LLM trên GPU nhỏ (None = mặc định Ollama).
    """

    def __init__(self, base_url: str, model: str = "bge-m3", timeout: float = 120.0,
                 query_prefix: str = "", doc_prefix: str = "",
                 keep_alive: str | None = "30m", num_gpu: int | None = None, retries: int = 2):
        self.url = f"{base_url.rstrip('/')}/api/embed"
        self.model, self.timeout = model, timeout
        self.query_prefix, self.doc_prefix = query_prefix, doc_prefix
        self.keep_alive, self.num_gpu, self.retries = keep_alive, num_gpu, retries

    def _post(self, texts: list[str]) -> list[list[float]]:
        import httpx  # import trễ để module dùng được khi chưa cài httpx

        body: dict = {"model": self.model, "input": texts}
        if self.keep_alive:
            body["keep_alive"] = self.keep_alive
        if self.num_gpu is not None:
            body["options"] = {"num_gpu": self.num_gpu}
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                r = httpx.post(self.url, json=body, timeout=self.timeout)
                r.raise_for_status()
                vecs = r.json()["embeddings"]
                if len(vecs) != len(texts):
                    raise ValueError(f"Ollama trả {len(vecs)} vector cho {len(texts)} văn bản")
                return [_unit(v) for v in vecs]
            except (httpx.HTTPError, KeyError, ValueError) as exc:
                last = exc
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"Embedding thất bại sau {self.retries + 1} lần: {last}") from last

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Giữ tương thích cũ: embed văn bản tài liệu."""
        return self.embed_documents(texts)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._post([self.doc_prefix + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._post([self.query_prefix + text])[0]


def _unit(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]
