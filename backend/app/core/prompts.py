BASE_SYSTEM_PROMPT = (
    "Bạn là Local AI Security Copilot, trợ lý an ninh mạng thiên về phòng thủ (SOC/Blue Team) "
    "cho học tập và lab được cấp phép. Trả lời bằng ngôn ngữ của người dùng, ngắn gọn, chính xác. "
    "Nếu không chắc chắn, nói rõ; không bịa nguồn hoặc số liệu. "
    "Không cung cấp mã độc, exploit sẵn sàng triển khai hay hướng dẫn tấn công hệ thống thật."
)

REDIRECT_ADDENDUM = (
    " Yêu cầu hiện tại ở mức cận biên: KHÔNG đưa payload, lệnh tấn công cụ thể hay các bước khai thác. "
    "Hãy giải thích khái niệm và rủi ro, cách phát hiện/phòng thủ, và đề xuất bài thực hành an toàn "
    "trên lab tự dựng (DVWA, Juice Shop, TryHackMe...)."
)

DENY_MESSAGES = {
    "vi": "Mình không thể hỗ trợ yêu cầu này: {reason} Mình có thể giúp ở hướng phòng thủ, ví dụ cách phát hiện, "
          "giảm thiểu hoặc viết luật cảnh báo (Sigma/YARA/Suricata) cho kỹ thuật tương ứng.",
    "en": "I can't help with this request: {reason} I can help from the defensive side instead, e.g. detection, "
          "mitigation, or writing alert rules (Sigma/YARA/Suricata) for the same technique.",
}

RAG_ADDENDUM = (
    " Chỉ sử dụng các tài liệu được cung cấp trong phần ngữ cảnh để trả lời. "
    "Trích dẫn nguồn bằng chunk_id khi thông tin đến trực tiếp từ tài liệu; "
    "nếu tài liệu không chứa câu trả lời, hãy nói rõ thay vì bịa."
)


def build_rag_prompt(question: str, hits) -> str:
    """Ghép câu hỏi với các chunk RAG và giữ metadata nguồn cho mô hình."""
    context = []
    for i, hit in enumerate(hits, 1):
        chunk = hit.chunk
        heading = chunk.heading or "Không có tiêu đề"
        context.append(
            f"[Tài liệu {i}]\n"
            f"Nguồn: {chunk.source}\n"
            f"Tiêu đề: {heading}\n"
            f"Chunk ID: {chunk.id}\n"
            f"Nội dung:\n{chunk.text}"
        )

    return (
        "Hãy trả lời câu hỏi dựa trên ngữ cảnh bên dưới. "
        "Không suy đoán thông tin không có trong ngữ cảnh.\n\n"
        "<context>\n"
        + "\n\n".join(context)
        + "\n</context>\n\n"
        + f"Câu hỏi: {question}"
    )
