# Local AI Security Copilot

Local AI Security Copilot là ứng dụng FastAPI hỗ trợ tư vấn an ninh mạng bằng Ollama, kết hợp policy engine, BM25 và ChromaDB RAG.

## Công nghệ

- Python 3.12 và FastAPI
- Ollama: `qwen2.5:7b` cho chat và `bge-m3` cho embedding
- BM25 cho tìm kiếm từ khóa
- ChromaDB cho tìm kiếm vector ngữ nghĩa
- JSON Lines cho audit log


## Yêu cầu

- Linux hoặc WSL 2
- Python 3.12+
- Ollama đang chạy
- Thư mục `knowledge_base/` chứa tài liệu Markdown

## Clone dự án

```bash
git clone https://github.com/DangHung845/local-ai-security-copilot.git
cd local-ai-security-copilot
```

## Cài Ollama

Cài Ollama, sau đó tải mô hình:

```bash
ollama pull qwen2.5:7b
ollama pull bge-m3
```

Kiểm tra Ollama:

```bash
curl http://localhost:11434/api/tags
```

Nếu Ollama chạy trên Windows host trong WSL, đặt địa chỉ Windows host trong `.env`, ví dụ:

```dotenv
OLLAMA_BASE_URL=http://172.23.128.1:11434
```

## Cài backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Tạo cấu hình:

```bash
cp .env.example .env
```

Cấu hình RAG mặc định:

```dotenv
RAG_ENABLED=true
RAG_INDEX_PATH=data/rag_index.json
RAG_EMBED_MODEL=bge-m3
RAG_USE_EMBEDDINGS=true
RAG_TOP_K=4
RAG_MIN_SEMANTIC=0.5
RAG_CHROMA_DIR=data/chroma
RAG_CHROMA_COLLECTION=security_knowledge
```

## Thêm tài liệu

Đặt các tài liệu Markdown trong `knowledge_base/`:

```text
knowledge_base/
└── owasp/
    ├── SQL_Injection_Prevention_Cheat_Sheet.md
    └── Cross_Site_Scripting_Prevention_Cheat_Sheet.md
```

Mỗi tài liệu nên có tiêu đề Markdown để chunker giữ đúng heading làm ngữ cảnh.

## Tạo RAG index

Chạy ingest sau khi clone hoặc khi thay đổi knowledge base:

```bash
cd backend
source .venv/bin/activate
python scripts/ingest.py
```

Script đọc toàn bộ file `.md`, tạo chunk BM25 và embedding bằng `bge-m3`.

Script tạo dữ liệu local:

- `backend/data/rag_index.json`: chunk và BM25 index
- `backend/data/chroma/`: vector và metadata ChromaDB

Hai thư mục này được sinh tự động và không cần commit.

Có thể truyền tùy chọn:

```bash
python scripts/ingest.py \
  --knowledge-dir ../knowledge_base \
  --index data/rag_index.json \
  --chroma-dir data/chroma \
  --collection security_knowledge \
  --ollama-url http://localhost:11434 \
  --embed-model bge-m3
```

## Chạy backend

```bash
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Địa chỉ:

- Health: http://localhost:8000/health
- Swagger: http://localhost:8000/docs
- Chat: `POST http://localhost:8000/api/v1/chat`

Kiểm tra:

```bash
curl http://localhost:8000/health
```

Gửi câu hỏi:

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"prompt":"OWASP khuyến nghị cách nào để phòng chống SQL injection?"}'
```

## Cập nhật knowledge base

Sau khi thêm, sửa hoặc xóa tài liệu Markdown, chạy lại ingest:

```bash
cd backend
source .venv/bin/activate
python scripts/ingest.py
```

## Chạy test

```bash
cd backend
source .venv/bin/activate
pytest -q
```

## Cấu trúc backend

```text
backend/
├── app/
│   ├── api/routes/chat.py
│   ├── core/
│   ├── models/
│   ├── policy/
│   ├── rag/
│   └── services/
├── scripts/ingest.py
├── tests/
└── requirements.txt
knowledge_base/
```

## Bảo mật

- Không commit `.env`, token hoặc khóa bí mật.
- Không commit `backend/data/rag_index.json` và `backend/data/chroma/`.
- Policy engine được chạy trước RAG để hạn chế yêu cầu tấn công.
- Chỉ đưa tài liệu được cấp phép vào knowledge base.

