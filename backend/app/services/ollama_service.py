import httpx

from app.core.config import get_settings


class OllamaError(Exception):
    """Base exception for Ollama service errors."""


class OllamaConnectionError(OllamaError):
    pass


class OllamaTimeoutError(OllamaError):
    pass


class OllamaResponseError(OllamaError):
    pass


class OllamaService:
    def __init__(self):
        self.settings = get_settings()

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
    ) -> str:
        url = f"{self.settings.ollama_base_url.rstrip('/')}/api/generate"

        payload = {
            "model": self.settings.ollama_model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_ctx": self.settings.ollama_num_ctx}    
        }

        if system_prompt:
            payload["system"] = system_prompt

        timeout = httpx.Timeout(self.settings.ollama_timeout)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()

        except httpx.TimeoutException as exc:
            raise OllamaTimeoutError(
                "Ollama request timed out."
            ) from exc

        except httpx.HTTPStatusError as exc:
            raise OllamaResponseError(
                f"Ollama returned HTTP {exc.response.status_code}."
            ) from exc

        except httpx.RequestError as exc:
            raise OllamaConnectionError(
                "Could not connect to Ollama."
            ) from exc

        try:
            data = response.json()
            result = data.get("response")

            if not isinstance(result, str):
                raise OllamaResponseError(
                    "Ollama response does not contain a valid answer."
                )

            return result

        except ValueError as exc:
            raise OllamaResponseError(
                "Ollama returned invalid JSON."
            ) from exc
