"""Audit log dạng JSON Lines. Không ghi nguyên văn prompt có chứa secret."""
import hashlib
import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

_SECRET_PATTERNS = [
    re.compile(r"(?i)\b(password|passwd|pwd|mat khau|api[_-]?key|secret|token)\b\s*[:=]\s*\S+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}\b"),
]
_lock = threading.Lock()


def redact(text: str) -> str:
    for rx in _SECRET_PATTERNS:
        text = rx.sub("[REDACTED]", text)
    return text


class AuditLogger:
    def __init__(self, path: str | Path, preview_chars: int = 200):
        self.path = Path(path)
        self.preview_chars = preview_chars

    def log(self, event: str, prompt: str, **fields) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "prompt_preview": redact(prompt)[: self.preview_chars],
            **fields,
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with _lock, self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass  # audit lỗi không được làm sập API; cân nhắc cảnh báo ở bản sau
