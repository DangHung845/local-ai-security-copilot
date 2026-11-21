"""BM25 thuần Python (không phụ thuộc thư viện). Chuẩn hóa bỏ dấu để chịu lỗi gõ tiếng Việt."""
import math
import re
import unicodedata
from collections import Counter

from app.policy.engine import normalize


_STOP_VI = ("và là của có không được trong cho các một những này đó khi thì mà bị với từ để gì nào sao "
            "như thế nên cần ra vào lên đã sẽ đang rất cũng hay hoặc nếu về tại theo ở").split()
_STOP_EN = ("a an the of and or to in on at is are was were be been it its this that for with as by from "
            "what why how can do does").split()
STOP = set(_STOP_VI) | set(_STOP_EN)
STOP_FOLD = {normalize(w) for w in STOP}


_SUFFIXES = ("ations", "ation", "ities", "ity", "ings", "ing", "ions", "ion", "ies", "ed", "es", "ly", "s")


def stem(w: str) -> str:
    """Bộ rút gọn hậu tố tiếng Anh rất nhẹ (prevention/prevent, stored/store, passwords/password).
    Chỉ áp cho từ ASCII dài; không đụng tiếng Việt."""
    if len(w) < 5 or not (w.isascii() and w.isalpha()):
        return w
    if w.endswith("ies"):
        return w[:-3] + "y"
    for suf in _SUFFIXES:
        if suf == "s" and w.endswith(("ss", "us", "is")):  # cross, access, status, analysis
            continue
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            w = w[: -len(suf)]
            break
    return w[:-1] if w.endswith("e") and len(w) > 4 else w


def tokenize(text: str, fold: bool = False) -> list[str]:
    """fold=False giữ dấu (chính xác hơn: "bò" khác "bỏ"); fold=True bỏ dấu để khớp câu hỏi gõ không dấu."""
    if fold:
        words = [w for w in re.findall(r"[a-z0-9]+", normalize(text)) if w not in STOP_FOLD]
    else:
        words = [w for w in re.findall(r"\w+", unicodedata.normalize("NFC", text).lower()) if w not in STOP]
    words = [stem(w) for w in words]
    return words + [f"{a}_{b}" for a, b in zip(words, words[1:])]  # unigram + bigram


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75, fold: bool = False):
        self.k1, self.b, self.fold = k1, b, fold
        self.tf = [Counter(tokenize(d, fold)) for d in docs]
        self.len = [sum(c.values()) for c in self.tf]
        self.avg = (sum(self.len) / len(docs)) if docs else 0.0
        df = Counter(t for c in self.tf for t in c)
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: str) -> list[float]:
        q = tokenize(query, self.fold)
        out = []
        for tf, dl in zip(self.tf, self.len):
            s = 0.0
            for t in q:
                f = tf.get(t)
                if f:
                    s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avg))
            out.append(s)
        return out

    def coverage(self, query: str) -> list[float]:
        """Tỉ lệ từ đơn của câu hỏi xuất hiện trong từng chunk: lọc khớp lẻ tẻ như "công" trong "tấn công"."""
        q = {t for t in tokenize(query, self.fold) if "_" not in t}
        if not q:
            return [0.0] * len(self.tf)
        return [sum(1 for t in q if t in tf) / len(q) for tf in self.tf]
