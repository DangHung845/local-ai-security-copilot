"""Reranker nhẹ qua Ollama để xếp lại candidate RAG bằng mô hình sinh."""

import json
import re

import httpx


class OllamaReranker:
    def __init__(self, base_url: str, model: str = "qwen2.5:7b", timeout: float = 120.0):
        self.url = f"{base_url.rstrip('/')}/api/generate"
        self.model = model
        self.timeout = timeout

    def rerank(self, query: str, candidates: list[tuple], top_k: int) -> list[tuple]:
        """Trả về candidate đã rerank. Candidate có dạng (index, chunk, rrf_score)."""
        if not candidates:
            return []

        documents = []
        for index, chunk, rrf_score in candidates:
            documents.append(
                f'{{"index":{index},"source":"{chunk.source}","heading":"{chunk.heading}",'
                f'"text":"{chunk.text[:1000]}"}}'
            )

        prompt = (
            "Bạn là reranker. Chấm mức độ liên quan của mỗi tài liệu với câu hỏi. "
            "Chỉ trả JSON hợp lệ theo dạng {\"scores\":[{\"index\":0,\"score\":85},...]} "
            "Score là số nguyên 0-100. Ưu tiên tài liệu trả lời trực tiếp câu hỏi.\n\n"
            f"Câu hỏi: {query}\n\nTài liệu:\n" + "\n".join(documents)
        )

        try:
            response = httpx.post(
                self.url,
                json={"model": self.model, "prompt": prompt, "stream": False,
                      "options": {"temperature": 0, "num_predict": 400}},
                timeout=self.timeout,
            )
            response.raise_for_status()
            raw = response.json().get("response", "")
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                return candidates[:top_k]
            parsed = json.loads(match.group(0))
            scores = {
                int(item["index"]): max(0, min(100, int(item["score"])))
                for item in parsed.get("scores", [])
                if isinstance(item, dict)
            }
            reranked = sorted(
                candidates,
                key=lambda candidate: scores.get(candidate[0], 0),
                reverse=True,
            )
            return reranked[:top_k]
        except Exception:
            return candidates[:top_k]
