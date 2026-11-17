"""Chạy 5 prompt kiểm tra, mỗi prompt N lần, in bảng và lưu kết quả.

Hai chế độ:
  --mode ollama   (mặc định) gọi thẳng Ollama: có token/giây và thời gian nạp model chính xác,
                  dùng để điền hardware.md. Không cần bật backend.
  --mode backend  gọi POST /api/v1/chat của backend ({"prompt": ...}): đo độ trễ end-to-end,
                  token/giây chỉ có nếu response có thêm các trường eval_tokens, tokens_per_sec.

    python scripts/bench.py
    python scripts/bench.py --model qwen2.5:7b --runs 3
    python scripts/bench.py --mode backend --url http://localhost:8000
Kết quả: results/bench_<thời gian>.md (bảng, dán vào hardware.md) và .json (kèm câu trả lời đầy đủ).
"""
import argparse
import json
import platform
import subprocess
import time
from datetime import datetime
from pathlib import Path

import httpx

SSH_LOG = """Nov 17 02:14:03 srv sshd[2211]: Failed password for root from 10.10.0.55 port 40122 ssh2
Nov 17 02:14:05 srv sshd[2213]: Failed password for root from 10.10.0.55 port 40124 ssh2
Nov 17 02:14:07 srv sshd[2215]: Failed password for admin from 10.10.0.55 port 40126 ssh2
Nov 17 02:14:09 srv sshd[2217]: Failed password for ubuntu from 10.10.0.55 port 40128 ssh2
Nov 17 02:14:12 srv sshd[2219]: Accepted password for ubuntu from 10.10.0.55 port 40130 ssh2
Nov 17 02:14:40 srv sudo: ubuntu : TTY=pts/0 ; COMMAND=/bin/cat /etc/shadow"""

PROMPTS = [
    ("1 ngắn (VI)", "SQL injection là gì? Trả lời trong 2 câu."),
    ("2 tiếng Anh", "Explain the difference between IDS and IPS in 5 bullet points."),
    ("3 dài (VI)", "Giải thích chi tiết quy trình xử lý sự cố an ninh mạng theo 6 giai đoạn của NIST "
                   "(chuẩn bị, phát hiện, ngăn chặn, loại bỏ, khôi phục, rút kinh nghiệm), "
                   "mỗi giai đoạn nêu 3 hành động cụ thể."),
    ("4 phân tích log", "Phân tích đoạn log SSH này: có dấu hiệu bất thường không, mức độ nghiêm trọng, "
                        "và nên làm gì tiếp theo?\n\n" + SSH_LOG),
    ("5 bịa nguồn?", "Theo OWASP Top 10 bản mới nhất, hạng mục A01 là gì? Nếu không chắc, hãy nói rõ."),
]


def vram_mb():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip().splitlines()[0]
        return int(out)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["ollama", "backend"], default="ollama")
    ap.add_argument("--url", default=None, help="mặc định: Ollama http://localhost:11434, backend http://localhost:8000")
    ap.add_argument("--model", default="qwen2.5:7b", help="chỉ dùng cho --mode ollama")
    ap.add_argument("--path", default="/api/v1/chat", help="đường dẫn chat của backend")
    ap.add_argument("--runs", type=int, default=2, help="số lần chạy mỗi prompt (lần 1 gồm cả nạp model)")
    ap.add_argument("--timeout", type=float, default=300)
    ap.add_argument("--outdir", default="results")
    args = ap.parse_args()

    url = args.url or ("http://172.23.128.1:11434" if args.mode == "ollama" else "http://localhost:8000")
    try:
        if args.mode == "ollama":
            httpx.get(f"{url}/api/tags", timeout=10).raise_for_status()
        else:
            httpx.get(f"{url}/health", timeout=10).raise_for_status()
    except httpx.HTTPError as e:
        raise SystemExit(f"Không gọi được {url}: {e}\nHãy bật {'Ollama' if args.mode == 'ollama' else 'uvicorn'} trước.")

    rows, full = [], []
    for name, prompt in PROMPTS:
        for run in range(1, args.runs + 1):
            t0 = time.perf_counter()
            tokens = tok_s = load_ms = None
            try:
                if args.mode == "ollama":
                    r = httpx.post(f"{url}/api/chat", timeout=args.timeout, json={
                        "model": args.model, "stream": False,
                        "messages": [{"role": "user", "content": prompt}],
                        "options": {"temperature": 0, "seed": 42}})
                    r.raise_for_status()
                    d = r.json()
                    answer, model = d["message"]["content"], args.model
                    tokens = d.get("eval_count")
                    if tokens and d.get("eval_duration"):
                        tok_s = round(tokens / (d["eval_duration"] / 1e9), 1)
                    load_ms = int(d.get("load_duration", 0) / 1e6)
                else:
                    r = httpx.post(f"{url}{args.path}", timeout=args.timeout, json={"prompt": prompt})
                    r.raise_for_status()
                    d = r.json()
                    answer, model = d["answer"], d.get("model", "?")
                    tokens, tok_s = d.get("eval_tokens"), d.get("tokens_per_sec")
            except (httpx.HTTPError, KeyError, ValueError) as e:
                print(f"LỖI {name} lần {run}: {e}")
                continue
            wall = int((time.perf_counter() - t0) * 1000)
            row = dict(prompt=name, run=run, wall_ms=wall, load_ms=load_ms,
                       tokens=tokens, tok_s=tok_s, vram_mb=vram_mb())
            rows.append(row)
            full.append({**row, "model": model, "answer": answer})
            print(f"{name:<16} lần {run} | {wall:>6} ms | nạp {load_ms} ms | {tokens} tok | "
                  f"{tok_s} tok/s | VRAM {row['vram_mb']} MB")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    model = full[0]["model"] if full else "?"
    lines = [
        f"# Bench {stamp}", "",
        f"- Model: {model}",
        f"- Máy: {platform.node()} ({platform.system()} {platform.release()})",
        f"- Số lần mỗi prompt: {args.runs} (lần 1 gồm thời gian nạp model nếu model chưa nằm trong bộ nhớ)",
        f"- Chế độ: {args.mode}", "",
        "| Prompt | Lần | Tổng thời gian (ms) | Nạp model (ms) | Token | Token/giây | VRAM (MB) |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        lines.append(f"| {r['prompt']} | {r['run']} | {r['wall_ms']} | {r['load_ms']} | {r['tokens']} | {r['tok_s']} | {r['vram_mb']} |")
    (out / f"bench_{stamp}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / f"bench_{stamp}.json").write_text(json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nĐã lưu: {out}/bench_{stamp}.md và .json (đọc câu trả lời đầy đủ trong file .json)")


if __name__ == "__main__":
    main()
