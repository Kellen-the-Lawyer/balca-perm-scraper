"""
Experience Verification Letter — pdfplumber extractor
Rule-based parsing; no AI required.

Extracts:
  - employerName
  - employerTitle  (signer's title)
  - beneficiaryName
  - jobTitle
  - startDate / endDate (as written)
  - startParsed / endParsed (ISO date strings, best-effort)
  - duties  (body paragraph text)
  - skills  (keywords found in duties)
  - fullText (all extracted text)
"""
import io
import re
import pdfplumber
from datetime import date


# ── Public entry points ───────────────────────────────────────────────────────

def extract_letter_from_bytes(pdf_bytes: bytes) -> dict:
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages = [p.extract_text() or "" for p in pdf.pages]
    return _parse_letter("\n".join(pages))


def extract_letter(pdf_path: str) -> dict:
    with pdfplumber.open(pdf_path) as pdf:
        pages = [p.extract_text() or "" for p in pdf.pages]
    return _parse_letter("\n".join(pages))


# ── Core parser ───────────────────────────────────────────────────────────────

def _parse_letter(text: str) -> dict:
    result = {
        "employerName":   "",
        "employerTitle":  "",
        "beneficiaryName": "",
        "jobTitle":       "",
        "startDate":      "",
        "endDate":        "",
        "startParsed":    None,
        "endParsed":      None,
        "months":         None,
        "duties":         "",
        "skills":         [],
        "fullText":       text,
    }

    lines = [l.strip() for l in text.splitlines() if l.strip()]

    _extract_dates(text, result)
    _extract_names_and_title(text, lines, result)
    _extract_job_title(text, result)
    _extract_duties(text, result)
    _extract_skills(result)

    if result["startParsed"] and result["endParsed"]:
        s = _to_date(result["startParsed"])
        e = _to_date(result["endParsed"])
        if s and e and e >= s:
            result["months"] = (e.year - s.year) * 12 + (e.month - s.month)

    return result


# ── Date extraction ───────────────────────────────────────────────────────────

# Patterns that recognise most date formats seen in experience letters
_DATE_PATTERNS = [
    # January 2019, Jan. 2019, January 15, 2019
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)[.,]?\s+(?:\d{1,2},?\s+)?\d{4}",
    # MM/YYYY or MM/DD/YYYY or MM-YYYY
    r"\d{1,2}[\/\-]\d{4}",
    r"\d{1,2}[\/\-]\d{1,2}[\/\-]\d{4}",
    # YYYY-MM
    r"\d{4}[\/\-]\d{1,2}",
]
_DATE_RE = re.compile("|".join(_DATE_PATTERNS), re.IGNORECASE)

# Phrases that introduce a date range in the first/second paragraph
_RANGE_TRIGGERS = re.compile(
    r"(?:employed|worked|position|service|from|between|since|period)[^\n.]{0,120}",
    re.IGNORECASE,
)

_PRESENT_RE = re.compile(
    r"\b(present|current|ongoing|to\s+date|till\s+date|to\s+present)\b",
    re.IGNORECASE,
)


def _extract_dates(text: str, result: dict):
    """Find start and end dates from the employment period sentence."""
    # Walk through trigger sentences and try to pull two dates out
    for m in _RANGE_TRIGGERS.finditer(text):
        snippet = m.group(0)
        dates = _DATE_RE.findall(snippet)
        if dates:
            result["startDate"] = dates[0]
            result["startParsed"] = _normalise_date(dates[0])
            if len(dates) >= 2:
                result["endDate"] = dates[1]
                result["endParsed"] = _normalise_date(dates[1])
            elif _PRESENT_RE.search(snippet):
                result["endDate"] = "Present"
                result["endParsed"] = date.today().isoformat()
            break

    # Fallback: grab all dates from entire text, take first two
    if not result["startDate"]:
        all_dates = _DATE_RE.findall(text)
        if all_dates:
            result["startDate"] = all_dates[0]
            result["startParsed"] = _normalise_date(all_dates[0])
        if len(all_dates) >= 2:
            result["endDate"] = all_dates[1]
            result["endParsed"] = _normalise_date(all_dates[1])
        elif _PRESENT_RE.search(text):
            result["endDate"] = "Present"
            result["endParsed"] = date.today().isoformat()


_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
}


def _normalise_date(s: str) -> str | None:
    """Convert a fuzzy date string to YYYY-MM-DD (first of month)."""
    s = s.strip().rstrip(",.")
    # Named month
    m = re.match(
        r"([A-Za-z]+)[.,]?\s+(?:(\d{1,2}),?\s+)?(\d{4})", s, re.IGNORECASE
    )
    if m:
        mo = _MONTH_MAP.get(m.group(1).lower()[:3])
        yr = int(m.group(3))
        if mo:
            return f"{yr:04d}-{mo:02d}-01"
    # MM/YYYY or MM-YYYY
    m = re.match(r"(\d{1,2})[\/\-](\d{4})$", s)
    if m:
        return f"{int(m.group(2)):04d}-{int(m.group(1)):02d}-01"
    # MM/DD/YYYY
    m = re.match(r"(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})$", s)
    if m:
        return f"{int(m.group(3)):04d}-{int(m.group(1)):02d}-01"
    # YYYY-MM
    m = re.match(r"(\d{4})[\/\-](\d{1,2})$", s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-01"
    return None


def _to_date(iso: str | None) -> date | None:
    if not iso:
        return None
    try:
        parts = iso.split("-")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        return None


# ── Names & signer title ──────────────────────────────────────────────────────

# Common salutations / closings to skip
_SKIP_WORDS = re.compile(
    r"^(?:Dear|To Whom|Sincerely|Regards|Best|Thank|Re:|Subject|Date|"
    r"Reference|This is to|Please|If you|Should you|The above|I am|"
    r"He|She|They|Mr\.|Ms\.|Mrs\.|Dr\.)",
    re.IGNORECASE,
)

_NAME_RE = re.compile(
    r"\b([A-Z][a-z]+ (?:[A-Z]\. )?[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\b"
)


def _extract_names_and_title(text: str, lines: list, result: dict):
    """
    Employer name: typically the first non-blank line (letterhead).
    Beneficiary name: first proper-noun pair after "employed"/"worked".
    Signer title: line immediately after the signer name near the signature block.
    """
    # Employer name — first line that looks like an org name
    for line in lines[:6]:
        if not _SKIP_WORDS.match(line) and len(line) > 3:
            result["employerName"] = line
            break

    # Beneficiary name — first name-like token in the employment sentence
    empl_m = re.search(
        r"(?:employed|worked|hired|retained|served)[^\n.]{0,80}",
        text, re.IGNORECASE
    )
    if empl_m:
        names = _NAME_RE.findall(empl_m.group(0))
        if names:
            result["beneficiaryName"] = names[0]

    # Signer title — scan last 20 lines for a title-like line after a name
    tail = lines[-20:]
    for i, line in enumerate(tail):
        if _NAME_RE.match(line) and i + 1 < len(tail):
            candidate = tail[i + 1]
            # Title lines are short and contain role keywords
            if (len(candidate) < 80 and re.search(
                r"\b(?:Director|Manager|President|VP|Vice|Officer|Head|"
                r"Supervisor|Partner|Principal|HR|Human Resources|CEO|CFO|CTO)\b",
                candidate, re.IGNORECASE
            )):
                result["employerTitle"] = candidate
                break


# ── Job title ─────────────────────────────────────────────────────────────────

_TITLE_TRIGGERS = re.compile(
    r"(?:position of|title of|as (?:a|an)|capacity as|role of|"
    r"served as|employed as|worked as)[,:]?\s+([A-Za-z /\-]{3,60})",
    re.IGNORECASE,
)


def _extract_job_title(text: str, result: dict):
    m = _TITLE_TRIGGERS.search(text)
    if m:
        raw = m.group(1).strip().rstrip(".,")
        # Stop at sentence-ending punctuation or line break
        raw = re.split(r"[,\n]", raw)[0].strip()
        if 3 <= len(raw) <= 60:
            result["jobTitle"] = raw


# ── Duties ────────────────────────────────────────────────────────────────────

_DUTIES_START = re.compile(
    r"(?:duties|responsibilities|job duties|role included|role includes|"
    r"tasks|functions|accountabilities)[^\n]{0,40}\n",
    re.IGNORECASE,
)

_CLOSING_RE = re.compile(
    r"(?:sincerely|regards|best wishes|please feel free|"
    r"if you have any questions|should you have)",
    re.IGNORECASE,
)


def _extract_duties(text: str, result: dict):
    """Extract the duties paragraph(s)."""
    m = _DUTIES_START.search(text)
    if m:
        body = text[m.end():]
        # Trim at closing / signature block
        close = _CLOSING_RE.search(body)
        if close:
            body = body[:close.start()]
        result["duties"] = body.strip()
        return

    # Fallback: grab the largest paragraph that isn't a header or closing
    paragraphs = re.split(r"\n{2,}", text)
    candidates = []
    for p in paragraphs:
        p = p.strip()
        if len(p) > 150 and not _CLOSING_RE.search(p):
            candidates.append(p)
    if candidates:
        result["duties"] = max(candidates, key=len)


# ── Skills keyword extraction ─────────────────────────────────────────────────

# Common tech / professional skills that appear in PERM experience letters
_SKILL_PATTERNS = re.compile(
    r"\b("
    r"Python|Java(?:Script)?|TypeScript|C\+\+|C#|Ruby|PHP|Swift|Kotlin|Go|Rust|Scala|"
    r"HTML5?|CSS3?|SQL|NoSQL|React|Angular|Vue|Node(?:\.js)?|Django|Flask|FastAPI|"
    r"Spring|\.NET|AWS|Azure|GCP|Docker|Kubernetes|Terraform|CI\/CD|DevOps|"
    r"Machine Learning|Deep Learning|NLP|TensorFlow|PyTorch|Hadoop|Spark|"
    r"PostgreSQL|MySQL|MongoDB|Redis|Elasticsearch|Kafka|RabbitMQ|"
    r"REST(?:ful)?|GraphQL|gRPC|Microservices|Agile|Scrum|JIRA|Git(?:Hub|Lab)?"
    r")\b",
    re.IGNORECASE,
)


def _extract_skills(result: dict) -> None:
    source = result["duties"] or result["fullText"]
    found = {m.group(0) for m in _SKILL_PATTERNS.finditer(source)}
    result["skills"] = sorted(found, key=str.lower)
