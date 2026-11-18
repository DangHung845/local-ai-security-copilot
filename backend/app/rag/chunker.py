"""Chia tài liệu Markdown thành chunk theo tiêu đề, giữ đường dẫn tiêu đề làm ngữ cảnh."""
import re
from dataclasses import dataclass


@dataclass
class Chunk:
    id: str
    source: str
    heading: str
    text: str


def _split_sections(text: str):
    path, buf, sections = [], [], []

    def flush():
        body = "\n".join(buf).strip()
        if body:
            sections.append((" > ".join(h for h in path if h), body))
        buf.clear()

    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*\S)\s*$", line)
        if m:
            flush()
            level = len(m.group(1))
            del path[level - 1:]
            path.extend([""] * (level - 1 - len(path)))
            path.append(m.group(2))
        else:
            buf.append(line)
    flush()
    return sections


def chunk_markdown(text: str, source: str, max_chars: int = 900, overlap: int = 120) -> list[Chunk]:
    chunks: list[Chunk] = []
    for heading, body in _split_sections(text):
        paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
        cur = ""
        for p in paras:
            if cur and len(cur) + len(p) + 2 > max_chars:
                chunks.append(Chunk(f"{source}#{len(chunks)}", source, heading, cur))
                cur = cur[-overlap:] if overlap else ""
            cur = f"{cur}\n\n{p}".strip() if cur else p
            while len(cur) > max_chars * 1.5:  # đoạn quá dài không có dòng trống
                chunks.append(Chunk(f"{source}#{len(chunks)}", source, heading, cur[:max_chars]))
                cur = cur[max_chars - overlap:]
        if cur:
            chunks.append(Chunk(f"{source}#{len(chunks)}", source, heading, cur))
    return chunks
