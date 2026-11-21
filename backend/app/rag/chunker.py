"""Làm sạch Markdown và chia chunk theo tiêu đề, nhận biết khối code (fence).

"""
import re
from dataclasses import dataclass


@dataclass
class Chunk:
    id: str
    source: str
    heading: str
    text: str


_FENCE = re.compile(r"^\s*(```+|~~~+)")
_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


def _split_fenced(text: str) -> list[tuple[bool, str]]:
    """Tách thành các đoạn (is_code, text) theo code fence."""
    parts, buf, fence, in_code = [], [], None, False
    for line in text.splitlines():
        m = _FENCE.match(line)
        if not in_code and m:
            if buf:
                parts.append((False, "\n".join(buf)))
            buf, fence, in_code = [line], m.group(1)[:3], True
        elif in_code and m and m.group(1).startswith(fence):
            buf.append(line)
            parts.append((True, "\n".join(buf)))
            buf, fence, in_code = [], None, False
        else:
            buf.append(line)
    if buf:
        parts.append((in_code, "\n".join(buf)))  # fence không đóng: coi như code đến hết file
    return parts


def _clean_prose(s: str) -> str:
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)                       # ảnh
    s = re.sub(r"\[([^\]]+)\]\((?:[^()\s]|\([^)]*\))*\)", r"\1", s)  # [text](url) -> text
    s = re.sub(r"\[([^\]]+)\]\[[^\]]*\]", r"\1", s)                  # [text][ref] -> text
    s = re.sub(r"^\s*\[[^\]]+\]:\s*\S+.*$", "", s, flags=re.M)       # định nghĩa link tham chiếu
    s = re.sub(r"<https?://[^>]+>", "", s)
    s = re.sub(r"https?://\S+", "", s)                               # URL trần
    s = re.sub(r"[ \t]+$", "", s, flags=re.M)
    return s


def clean_markdown(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = re.sub(r"^([ \t]*)```([^`\n]+)```[ \t]*$", r"\1`\2`", text, flags=re.M)  # ```inline``` ghi nhầm
    text = re.sub(r"\A---\n.*?\n---\n", "", text, flags=re.S)  # front-matter
    out = [part if is_code else _clean_prose(part) for is_code, part in _split_fenced(text)]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def _sections(text: str) -> list[tuple[str, str]]:
    path: list[str] = []
    sections: list[tuple[str, str]] = []
    buf: list[str] = []

    def flush():
        body = "\n".join(buf).strip()
        if body:
            sections.append((" > ".join(h for h in path if h), body))
        buf.clear()

    for is_code, part in _split_fenced(text):
        if is_code:
            buf.append(part)
            continue
        for line in part.splitlines():
            m = _HEADING.match(line)
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


def _blocks(body: str) -> list[tuple[bool, str]]:
    """Khối đoạn văn (ngăn bởi dòng trống) và khối code (nguyên vẹn)."""
    blocks: list[tuple[bool, str]] = []
    for is_code, part in _split_fenced(body):
        if is_code:
            blocks.append((True, part.strip("\n")))
        else:
            blocks += [(False, p.strip()) for p in re.split(r"\n\s*\n", part) if p.strip()]
    return blocks


def _split_long(is_code: bool, text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    pieces: list[str] = []
    if is_code:
        lines = text.splitlines()
        opener = lines[0] if _FENCE.match(lines[0]) else "```"
        body = lines[1:-1] if len(lines) > 1 and _FENCE.match(lines[-1]) else lines[1:]
        cur: list[str] = []
        size = 0
        for ln in body:
            if cur and size + len(ln) + 1 > max_chars:
                pieces.append("\n".join([opener, *cur, "```"]))
                cur, size = [], 0
            cur.append(ln[:max_chars])
            size += len(ln) + 1
        if cur:
            pieces.append("\n".join([opener, *cur, "```"]))
        return pieces
    cur = ""
    for sent in re.split(r"(?<=[.!?])\s+", text):
        while len(sent) > max_chars:                       # câu dài bất thường
            if cur:
                pieces.append(cur)
                cur = ""
            pieces.append(sent[:max_chars])
            sent = sent[max_chars:]
        if cur and len(cur) + len(sent) + 1 > max_chars:
            pieces.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        pieces.append(cur)
    return pieces


def chunk_markdown(text: str, source: str, max_chars: int = 900, overlap: int = 200,
                   min_chars: int = 40) -> list[Chunk]:
    """overlap: nếu khối cuối của chunk trước ngắn hơn giá trị này thì lặp lại ở đầu chunk sau."""
    chunks: list[Chunk] = []

    def emit(heading: str, body: str):
        if len(re.sub(r"\W", "", body)) >= min_chars:
            chunks.append(Chunk(f"{source}#{len(chunks)}", source, heading, body))

    for heading, body in _sections(clean_markdown(text)):
        units: list[tuple[bool, str]] = []
        for is_code, blk in _blocks(body):
            units += [(is_code, p) for p in _split_long(is_code, blk, max_chars)]
        cur: list[str] = []
        size = 0
        for is_code, u in units:
            if cur and size + len(u) + 2 > max_chars:
                emit(heading, "\n\n".join(cur))
                tail = cur[-1]
                cur = [tail] if len(tail) <= overlap and "```" not in tail else []
                size = sum(len(x) + 2 for x in cur)
            cur.append(u)
            size += len(u) + 2
        if cur:
            emit(heading, "\n\n".join(cur))
    return chunks
