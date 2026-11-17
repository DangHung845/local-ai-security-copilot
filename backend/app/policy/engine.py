"""Policy Engine v1 (rule-based baseline).

Thứ tự đánh giá: injection -> deny -> scope -> redirect -> allow.
Đây là lớp luật (tầng 1 của cơ chế lai trong đề cương). Tầng 2 (intent classifier)
sẽ được thêm sau và chỉ xử lý các ca luật trả về ALLOW/REDIRECT không chắc chắn.

Văn bản được chuẩn hóa (NFKC, bỏ dấu tiếng Việt, lower-case) trước khi so khớp,
nên các pattern bên dưới viết KHÔNG DẤU.
"""
import ipaddress
import re
import unicodedata

from app.policy.schemas import Decision, PolicyResult


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower().replace("đ", "d")
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", text).strip()


def is_vietnamese(text: str) -> bool:
    return bool(re.search(r"[àáảãạăâđêôơưèéìíòóùúỳýẻẽẹ]", text.lower()))


# ---- Prompt injection / jailbreak -------------------------------------------------
INJECTION = [
    r"ignore (all |any |the )?(previous|prior|above|earlier) (instructions|rules|prompts?)",
    r"disregard (all |any |the )?(previous|prior|above) (instructions|rules)",
    r"bo qua (tat ca |moi )?(huong dan|chi dan|quy tac|rang buoc) (truoc|o tren|truoc do|an toan)",
    r"(you are|ban la|tu bay gio ban la) (now )?(dan|an? unrestricted|khong bi gioi han)",
    r"\b(dan|developer|god) mode\b",
    r"pretend (that )?(you|to) (have no|are not|don'?t have) (rules|restrictions|filters|limits)",
    r"gia vo (la )?(ban )?(khong co|khong bi) (quy tac|gioi han|rang buoc)",
    r"(print|reveal|show|repeat|in ra|tiet lo|cho toi xem) [^.?!\n]{0,25}system prompt",
]

# ---- Nội dung phá hoại ------------------------------------------------------------
GEN_VERB = (
    r"(?:viet|tao|lap trinh|sinh ra|sinh|code|build|write|create|generate|develop|make|craft|"
    r"cho toi (?:mot )?(?:doan )?ma|dua toi)"
)
MALWARE_NOUN = (
    r"(?:ransomware|malware|ma doc|phan mem doc hai|keylogger|trojan|botnet|rootkit|spyware|"
    r"infostealer|info stealer|password stealer|backdoor|phishing kit|credential harvester|"
    r"trang (?:web )?(?:gia mao|lua dao)|fake login page|ddos tool|cong cu ddos|dos tool|"
    r"worm (?:tu lan|may tinh)|self-propagating worm|virus may tinh)"
)
DEFENSIVE_BEFORE = (
    r"(?:phat hien|detect|phong chong|chong|ngan chan|prevent|mitigat|bao ve|defen[sc]e|"
    r"block|chan|phan tich|analy[sz]e|gioi thieu|yara|sigma|suricata|snort)"
)
DENY_RULES = [
    ("malware_generation", re.compile(rf"\b{GEN_VERB}\b[^.?!\n]{{0,60}}?{MALWARE_NOUN}"), True),
    ("evasion", re.compile(
        r"\b(bypass|evade|vuot qua|qua mat|lach)\b[^.?!\n]{0,25}\b(edr|antivirus|av|windows defender|xdr)\b"), False),
    ("weaponized_exploit", re.compile(
        r"(weaponi[sz]ed|0-?day|zero-?day)[^.?!\n]{0,40}(exploit|payload)|"
        r"(exploit|payload)[^.?!\n]{0,40}(weaponi[sz]ed|san sang trien khai|hoan chinh de tan cong)"), False),
    ("account_takeover", re.compile(
        r"\b(hack|crack|chiem|danh cap|chiem doat)\b[^.?!\n]{0,30}"
        r"(tai khoan|facebook|zalo|gmail|instagram|mat khau cua|account|password of|someone'?s)"), False),
    ("out_of_scope_target", re.compile(
        r"\b(quet|scan|tan cong|attack|pentest|exploit|khai thac|ddos|dos)\b[^.?!\n]{0,60}"
        r"(hcmus|\.edu\.vn|\.gov\.vn|\.gov\b|ngan hang|vietcombank|bank of|cua truong|truong dai hoc)"), False),
    ("data_exfil", re.compile(
        r"(danh cap|steal|exfiltrate|lay trom)[^.?!\n]{0,30}(du lieu|cookie|token|credential|database|data)"), False),
]

# ---- Scope: lệnh scan/tấn công có mục tiêu ---------------------------------------
TARGET_VERB = re.compile(r"\b(quet|scan|nmap|pentest|tan cong|attack|exploit|khai thac|brute.?force)\b")
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
DOMAIN_RE = re.compile(r"\b[a-z0-9-]+\.(?:com|net|org|vn|io|edu|gov|info|xyz)\b")
LAB_MARKERS = re.compile(
    r"\b(lab|ctf|dvwa|juice ?shop|tryhackme|hack ?the ?box|htb|metasploitable|vulnhub|webgoat|"
    r"moi truong (?:tu dung|lab|thu nghiem)|may ao|sandbox)\b"
)
CONCEPTUAL = re.compile(
    r"\b(la gi|giai thich|explain|what is|what are|khac nhau|difference|phan biet|tong quan|"
    r"hoat dong nhu the nao|how does|why|tai sao|cach phong chong|how (?:do i |to |can i )?(?:prevent|detect|defend|mitigate|stop))\b"
)

# ---- Redirect: cận biên -----------------------------------------------------------
REDIRECT_RULES = [
    ("hack_howto", re.compile(r"\b(how to hack|lam sao (?:de )?hack|cach hack|huong dan hack)\b")),
    ("auth_bypass", re.compile(r"\b(bypass|vuot qua|qua mat)\b[^.?!\n]{0,25}\b(login|dang nhap|auth|waf|captcha|2fa|mfa)\b")),
    ("bruteforce", re.compile(r"\b(brute.?force|dictionary attack|do mat khau|crack password|crack hash)\b")),
    ("exploit_howto", re.compile(
        r"\b(khai thac|exploit)\b[^.?!\n]{0,30}\b(cve-\d{4}-\d+|lo hong|vulnerability)\b")),
    ("offensive_payload", re.compile(
        r"\b(reverse shell|payload|shellcode|web shell|webshell)\b[^.?!\n]{0,40}\b(cho toi|give me|viet|write|tao|create)\b|"
        r"\b(cho toi|give me|viet|write|tao|create)\b[^.?!\n]{0,40}\b(reverse shell|payload|shellcode|web shell|webshell)\b")),
    ("traffic_flood", re.compile(r"\b(syn flood|flood|ddos|lam sap)\b[^.?!\n]{0,30}\b(server|website|may chu|trang web)\b")),
]


def _is_private(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False


class PolicyEngine:
    def evaluate(self, prompt: str) -> PolicyResult:
        text = normalize(prompt)

        for pat in INJECTION:
            if re.search(pat, text):
                return PolicyResult(
                    Decision.DENY, "prompt_injection",
                    "Phát hiện nỗ lực vô hiệu hóa quy tắc an toàn hoặc lộ system prompt.",
                    ("injection",),
                )

        for name, rx, check_defensive in DENY_RULES:
            for m in rx.finditer(text):
                if check_defensive:
                    # bỏ qua nếu danh từ mã độc đứng ngay sau từ khóa phòng thủ (vd "phát hiện ransomware")
                    before = text[max(0, m.start()):m.end()]
                    noun = re.search(MALWARE_NOUN, before)
                    window = before[: noun.start()] if noun else ""
                    if re.search(DEFENSIVE_BEFORE, window):
                        continue
                return PolicyResult(
                    Decision.DENY, name,
                    "Yêu cầu tạo công cụ/nội dung tấn công hoặc nhắm vào mục tiêu ngoài phạm vi.",
                    (name,),
                )

        if TARGET_VERB.search(text):
            ips = IP_RE.findall(text)
            domains = DOMAIN_RE.findall(text)
            if ips and not domains and all(_is_private(ip) for ip in ips):
                return PolicyResult(
                    Decision.ALLOW, "lab_target", "Mục tiêu nằm trong dải IP riêng (lab).",
                    ("private_target",), hitl_required=True,
                )
            if (ips or domains) and not LAB_MARKERS.search(text):
                return PolicyResult(
                    Decision.REDIRECT, "scope_unverified",
                    "Mục tiêu không xác thực là lab tự dựng; cần chuyển sang môi trường lab.",
                    ("scope_unverified",),
                )

        if not LAB_MARKERS.search(text) and not CONCEPTUAL.search(text):
            for name, rx in REDIRECT_RULES:
                if rx.search(text):
                    return PolicyResult(
                        Decision.REDIRECT, name,
                        "Ý định cận biên: chuyển thành giải thích khái niệm, phòng thủ hoặc bài lab an toàn.",
                        (name,),
                    )

        return PolicyResult(Decision.ALLOW, "defensive_or_general", "Không có tín hiệu rủi ro.", ())
