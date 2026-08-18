"""Compare experience verification letters (EVLs) to ETA-9141 requirements.

The local vision-language model is used for two bounded tasks:

* transcribe the current ETA-9141 Sections F.b/F.c into structured fields; and
* identify explicit EVL language that addresses each PWD requirement.

The report itself is assembled deterministically.  In particular, a coworker
or former-manager letter produces a supporting-evidence advisory, not an
automatic conclusion that the letter is insufficient.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pdfplumber

from .extract_9141 import extract as extract_9141


VLM_URL = os.environ.get(
    "EVL_VLM_URL",
    os.environ.get("AUDIT_VLM_URL", "http://localhost:1234/v1/chat/completions"),
)
VLM_MODEL = os.environ.get(
    "EVL_VLM_MODEL",
    os.environ.get("AUDIT_VLM_MODEL", "qwen/qwen3-vl-8b"),
)

# Optional remote backend for PWD parsing ONLY (all three must be set).
# EVLs contain employee PII and always stay on the local VLM regardless.
# Example: PWD_LLM_URL=https://api.openai.com/v1/chat/completions
#          PWD_LLM_MODEL=gpt-5.6-luna
#          PWD_LLM_API_KEY=<key>
PWD_LLM_URL = os.environ.get("PWD_LLM_URL", "")
PWD_LLM_MODEL = os.environ.get("PWD_LLM_MODEL", "")
PWD_LLM_API_KEY = os.environ.get("PWD_LLM_API_KEY", "")

MAX_PDF_PAGES = 30
MAX_VISION_PAGES = 12
MAX_TEXT_CHARS = 80_000

RELATIONSHIP_ADVISORY = {"coworker", "former_manager"}
RELATIONSHIP_LABELS = {
    "hr_or_company_official": "HR or company official",
    "current_manager": "Current manager",
    "former_manager": "Former manager",
    "coworker": "Coworker",
    "trainer": "Trainer",
    "other": "Other",
    "unknown": "Unknown",
}

EXPERIENCE_SCOPES = {
    "standalone", "some_experience", "full_term", "explicit_duration", "ambiguous"
}

DEGREE_RANK = {
    "none": 0,
    "high_school": 1,
    "associates": 2,
    "bachelors": 3,
    "masters": 4,
    "professional": 4,
    "doctorate": 5,
}

PWD_PROMPT = """You are extracting the CURRENT ETA-9141 Application for
Prevailing Wage Determination. Focus on Section F.b, Minimum Job Requirements,
Section F.c, Alternative Job Requirements, and every related addendum.

Return ONLY valid JSON using this exact structure:
{
  "job_title": string|null,
  "primary": {
    "education_level": string|null,
    "other_degree": string|null,
    "fields_of_study": [string],
    "second_degree": string|null,
    "training_months": integer|null,
    "training_fields": [string],
    "experience_months": integer|null,
    "experience_occupation": string|null,
    "special_requirements": [
      {
        "category": "license_certification|foreign_language|residency_fellowship|other",
        "text": string,
        "source_clause": string,
        "experience_scope": "standalone|some_experience|full_term|explicit_duration|ambiguous",
        "required_months": integer|null
      }
    ]
  },
  "alternative": null OR {
    "education_level": string|null,
    "other_degree": string|null,
    "fields_of_study": [string],
    "second_degree": string|null,
    "training_months": integer|null,
    "training_fields": [string],
    "experience_months": integer|null,
    "experience_occupation": string|null,
    "special_requirements_mode": "inherit|replace",
    "special_requirements": [
      {
        "category": "license_certification|foreign_language|residency_fellowship|other",
        "text": string,
        "source_clause": string,
        "experience_scope": "standalone|some_experience|full_term|explicit_duration|ambiguous",
        "required_months": integer|null
      }
    ]
  },
  "extraction_notes": [string]
}

Rules:
- Preserve the actual requirement wording. Do not modernize or summarize it.
- The PWD's own list punctuation defines the atomic unit. Create one
  special_requirements entry per item that the PWD itself delimits with a
  semicolon, a numbered item (1., 2., (a), (i)), or a bullet/line item. NEVER
  split below that floor: commas, "and", and "or" INSIDE one delimited item
  are part of that single item and must stay together in one entry.
- Reproduce each delimited item's text verbatim, including every "and" and
  "or" connector exactly as written. "Python and Java" (both required) and
  "Python or Java" (either suffices) are legally different requirements;
  altering, dropping, or splitting these connectors changes the requirement.
  Do not paraphrase connectors or reorder list members.
- Example: "Experience must include: SQL; Financial KPIs and P&L statement;
  e-commerce pricing, assortment, fulfillment, and inventory management
  strategies" produces exactly three entries: "SQL", "Financial KPIs and P&L
  statement", and "e-commerce pricing, assortment, fulfillment, and inventory
  management strategies". Never a separate entry for "assortment" or
  "fulfillment".
- Keep qualifications joined by "and" in the same route. Preserve "or" within
  an individual requirement when the PWD itself permits either option.
- Education and its corresponding experience duration form one qualification
  route. Do not merge the experience duration from one education option into
  another option.
- For alternative.special_requirements_mode use inherit unless the PWD
  expressly says the alternative special requirements replace the primary
  ones. The alternative array may contain only changed/additional items; the
  application will carry unchanged primary items into the alternative route.
- experience_scope is standalone when the item merely must be stated.
- Use some_experience for wording such as "experience must include X": the
  letter must expressly show X during qualifying employment, but the PWD does
  not require X for the entire base experience period.
- Use full_term only when the PWD says "full term," "entire period,"
  "throughout," "all three years," or an equivalent unambiguous formulation.
  Set required_months to that route's full base experience duration.
- Use explicit_duration when the PWD independently assigns a duration to an
  item, such as "two years with X." Set required_months to that exact duration.
- Use ambiguous when the duration linkage cannot be read confidently. Explain
  the ambiguity in extraction_notes; never silently choose the stricter or
  looser interpretation.
- Mixed durations must remain separate. Example: a five-year base requirement
  with three years of X and one year of Y produces two separate duration-bound
  requirements (36 months and 12 months).
- The text field is the delimited item's own wording, verbatim, without the
  surrounding controlling clause. For "experience must include: Python and
  SQL; Kubernetes" return two entries whose text values are "Python and SQL"
  and "Kubernetes", each with source_clause preserving the full sentence.
- The ONLY permitted split inside one delimited item is when the PWD assigns
  distinct explicit durations to distinct items within it: "two years with
  AWS and one year with Tableau" returns text "AWS" with 24 required_months
  and text "Tableau" with 12 required_months, because each duration binds its
  own item.
- Never return two entries with the same text merely because their durations
  differ. Bind every duration to the specific skill or activity it modifies.
- A zero or a checked No means null, not a requirement.
- Conditions of employment are not qualification requirements and must NOT
  appear in special_requirements: travel percentages or travel obligations,
  telecommuting/remote/hybrid work arrangements, work schedules or shifts,
  relocation, on-call duty, and similar terms of the job. Record them in
  extraction_notes if they appear inside the requirements text.
- Do not infer requirements from the job duties, SOC title, or wage level.
- Do not invent text that is unreadable. Record uncertainty in extraction_notes.
"""

ATOMIC_REPAIR_PROMPT = """The JSON below is an attempted extraction of current
ETA-9141 requirements. Correct ONLY the special_requirements arrays so every
entry represents one atomic skill, activity, license, language, or other item.
Return the entire corrected JSON object and preserve all other fields.

Rules:
- The PWD's own list punctuation defines the atomic unit: one entry per item
  the PWD delimits with a semicolon, numbered item, or bullet/line item. Never
  split below that floor; commas, "and", and "or" inside one delimited item
  stay together in one entry.
- text is the delimited item's wording verbatim, preserving every "and"/"or"
  connector exactly as written ("Python and Java" requires both; "Python or
  Java" permits either — these are legally different and must not be altered
  or split); source_clause preserves the full wording.
- MERGE entries that are comma or "and"/"or" fragments of a single delimited
  item back into one entry carrying that item's full verbatim text.
- "experience must include: Python and SQL; Kubernetes" becomes exactly two
  entries: "Python and SQL" and "Kubernetes".
- The only split inside one delimited item is for distinct explicit
  durations: "two years with AWS and one year with Tableau" becomes AWS/24
  months and Tableau/12 months.
- Never duplicate the same full clause as the text for multiple items.
- Do not invent or infer an item not present in source_clause.

ATTEMPTED JSON:
"""

EVL_PROMPT = """You are extracting facts from one experience verification
letter for a PERM-based I-140 review. Return ONLY valid JSON:
{
  "beneficiary_name": string|null,
  "employer_name": string|null,
  "employer_address": string|null,
  "writer_name": string|null,
  "writer_title": string|null,
  "writer_address": string|null,
  "writer_relationship": "hr_or_company_official|current_manager|former_manager|coworker|trainer|other|unknown",
  "written_on_employer_behalf": true|false|null,
  "on_letterhead": true|false|null,
  "signed": true|false|null,
  "start_date": "YYYY-MM-DD"|null,
  "end_date": "YYYY-MM-DD"|null,
  "currently_employed": true|false|null,
  "full_time": true|false|null,
  "hours_per_week": number|null,
  "job_titles": [string],
  "explicit_facts": [string],
  "experience_components": [
    {
      "item": string,
      "start_date": "YYYY-MM-DD"|null,
      "end_date": "YYYY-MM-DD"|null,
      "duration_months": integer|null,
      "applies_to_full_employment": true|false|null,
      "source_quote": string
    }
  ],
  "source_quotes": [string],
  "uncertainties": [string]
}

Rules:
- Extract only facts explicitly stated or visibly present in the letter.
- explicit_facts must preserve every stated skill, technology, method,
  license, language, training, degree, occupation, duty, and duration fact.
- Create a separate experience_components entry for every skill or activity
  whose duration can matter. Do not assign the letter's overall employment
  duration to an item unless the letter actually connects that item to the
  whole employment period. Preserve an independently stated shorter duration.
- applies_to_full_employment is true only when the wording links the item to
  the entire stated employment period; false when the letter limits it to a
  shorter period; otherwise null.
- Do not infer skills from a job title or from general responsibilities.
- Use former_manager when the writer says they formerly supervised the worker
  or is no longer writing as the employer's authorized representative.
- Use coworker when the writer describes a peer relationship.
- An official company/HR letter can be hr_or_company_official even if its
  author once managed the beneficiary, if the letter is issued on behalf of
  the employer.
- A visible employer address on letterhead may also be the writer's business
  address; populate both fields when that is what the document shows.
- source_quotes should be short exact excerpts supporting extracted facts.
- Use null and uncertainties rather than guessing.
"""

COVERAGE_PROMPT = """Compare the supplied atomic PWD requirements against the
experience verification letters. Return ONLY valid JSON:
{
  "assessments": [
    {
      "requirement_id": string,
      "status": "covered|partial|missing|unclear",
      "evl_ids": [string],
      "evidence_quotes": [string],
      "explanation": string
    }
  ]
}

Rules:
- Return exactly one assessment for every supplied requirement_id.
- Credit only explicit language in an EVL. Never infer a skill from a title,
  industry, project, broad duty, seniority, or related skill.
- "covered" means the EVLs expressly state the entire requirement.
- "partial" means only part of a compound requirement is express, or the
  evidence covers less than the required duration.
- "missing" means no EVL expressly addresses it.
- "unclear" means relevant wording exists but is too ambiguous to decide.
- Multiple EVLs may collectively cover one requirement.
- Education has already selected the applicable route and is not being proved
  by an EVL. Evaluate only the supplied experience/document requirements.
- For a base_experience requirement, count only expressly dated qualifying
  employment and do not double-count overlapping calendar periods.
- For some_experience, an express statement that the skill occurred during
  qualifying employment is enough; do NOT require the route's full duration.
- For full_term, the evidence must link the item to at least the route's full
  required duration. A shorter stated period is partial.
- For explicit_duration, the evidence must link the item to at least its own
  required_months. Do not substitute the general employment duration when the
  letter limits the skill to a shorter period.
- Treat ambiguous scope as unclear unless the EVL necessarily satisfies every
  plausible reading of the PWD language.
- Quotes must come from the supplied EVL text. Do not fabricate quotations.
- This is document-coverage review, not a legal conclusion about petition
  sufficiency.
"""


class VLMError(RuntimeError):
    """Raised when the local document model cannot return usable JSON."""


class RouteSelectionError(ValueError):
    """Raised when the applicable education/experience route is unresolved."""


def _json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise VLMError("Local model returned no JSON object")
        try:
            value = json.loads(text[start:end + 1])
        except json.JSONDecodeError as exc:
            raise VLMError(f"Local model returned invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise VLMError("Local model JSON response was not an object")
    return value


def _chat(content: list[dict[str, Any]], max_tokens: int = 7000,
          remote: bool = False) -> dict[str, Any]:
    use_remote = remote and PWD_LLM_URL and PWD_LLM_MODEL and PWD_LLM_API_KEY
    if use_remote:
        # OpenAI-compatible remote: newer models reject `temperature` and
        # `max_tokens`; use defaults and `max_completion_tokens` instead.
        payload = {
            "model": PWD_LLM_MODEL,
            "max_completion_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}],
        }
        url = PWD_LLM_URL
        headers = {"Content-Type": "application/json",
                   "Authorization": f"Bearer {PWD_LLM_API_KEY}"}
    else:
        payload = {
            "model": VLM_MODEL,
            "temperature": 0,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}],
        }
        url = VLM_URL
        headers = {"Content-Type": "application/json"}
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
    )
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            result = json.loads(response.read())
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        where = "the remote PWD model" if use_remote else \
            f"the local document model at {VLM_URL}"
        raise VLMError(f"Cannot reach {where}: {exc}") from exc
    try:
        raw = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise VLMError("The document model returned an unexpected response") from exc
    return _json_object(raw)


def _pdf_text(path: str) -> tuple[str, list[str]]:
    page_text: list[str] = []
    with pdfplumber.open(path) as pdf:
        if len(pdf.pages) > MAX_PDF_PAGES:
            raise ValueError(f"Document exceeds the {MAX_PDF_PAGES}-page limit")
        for page in pdf.pages:
            page_text.append(page.extract_text() or "")
    return "\n\n".join(page_text)[:MAX_TEXT_CHARS], page_text


def _render_pdf_pages(path: str, page_indexes: list[int]) -> list[str]:
    """Render selected pages to JPEG data URLs with pypdfium2."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(path)
    urls: list[str] = []
    try:
        for index in page_indexes[:MAX_VISION_PAGES]:
            if index < 0 or index >= len(pdf):
                continue
            bitmap = pdf[index].render(scale=1.8)
            image = bitmap.to_pil().convert("RGB")
            buf = io.BytesIO()
            image.save(buf, format="JPEG", quality=82, optimize=True)
            encoded = base64.b64encode(buf.getvalue()).decode("ascii")
            urls.append(f"data:image/jpeg;base64,{encoded}")
    finally:
        pdf.close()
    return urls


def _image_url(path: str) -> str:
    suffix = Path(path).suffix.lower()
    mime = {".png": "image/png", ".webp": "image/webp"}.get(suffix, "image/jpeg")
    return f"data:{mime};base64,{base64.b64encode(Path(path).read_bytes()).decode('ascii')}"


def _document_content(path: str, prompt: str, pwd: bool = False) -> tuple[list[dict[str, Any]], str]:
    suffix = Path(path).suffix.lower()
    if suffix == ".pdf":
        text, pages = _pdf_text(path)
        content: list[dict[str, Any]] = [
            {"type": "text", "text": f"{prompt}\n\nEXTRACTED DOCUMENT TEXT:\n{text}"}
        ]
        if pwd:
            markers = (
                "minimum job requirements", "alternative job requirements",
                "addendum for section f.b", "addendum for section f.c",
            )
            selected = [i for i, page in enumerate(pages)
                        if any(m in page.lower() for m in markers)]
            if not selected:
                selected = list(range(len(pages)))
            for url in _render_pdf_pages(path, selected):
                content.append({"type": "image_url", "image_url": {"url": url}})
        elif len(re.sub(r"\s+", "", text)) < 120:
            for url in _render_pdf_pages(path, list(range(len(pages)))):
                content.append({"type": "image_url", "image_url": {"url": url}})
        return content, text
    if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
        return ([
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": _image_url(path)}},
        ], "")
    if suffix in {".txt", ".md"}:
        text = Path(path).read_text(errors="replace")[:MAX_TEXT_CHARS]
        return ([{"type": "text", "text": f"{prompt}\n\nDOCUMENT TEXT:\n{text}"}], text)
    raise ValueError("Supported EVL formats are PDF, JPG, JPEG, PNG, WEBP, TXT, and MD")


def _clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned = []
    for item in value:
        text = _nullable_text(item)
        if text:
            cleaned.append(text)
    return cleaned


def _clean_requirement_set(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    special = []
    for item in source.get("special_requirements") or []:
        if isinstance(item, dict) and str(item.get("text") or "").strip():
            text = str(item["text"]).strip()
            source_clause = _nullable_text(item.get("source_clause")) or text
            scope = str(item.get("experience_scope") or "").strip().lower()
            required_months = _positive_int(item.get("required_months"))
            if scope not in EXPERIENCE_SCOPES:
                scope, inferred_months = _infer_experience_scope(source_clause)
                required_months = required_months or inferred_months
            elif scope == "explicit_duration" and not required_months:
                _, required_months = _infer_experience_scope(source_clause)
            special.append({
                "category": str(item.get("category") or "other"),
                "text": text,
                "source_clause": source_clause,
                "experience_scope": scope,
                "required_months": required_months,
            })
    return {
        "education_level": _nullable_text(source.get("education_level")),
        "other_degree": _nullable_text(source.get("other_degree")),
        "fields_of_study": _clean_list(source.get("fields_of_study")),
        "second_degree": _nullable_text(source.get("second_degree")),
        "training_months": _positive_int(source.get("training_months")),
        "training_fields": _clean_list(source.get("training_fields")),
        "experience_months": _positive_int(source.get("experience_months")),
        "experience_occupation": _nullable_text(source.get("experience_occupation")),
        "special_requirements_mode": (
            "replace" if str(source.get("special_requirements_mode") or "").lower() == "replace"
            else "inherit"
        ),
        "special_requirements": special,
    }


def _nullable_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return None if not text or text.lower() in {"n/a", "none", "null"} else text


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _duration_months(text: str) -> int | None:
    """Read a simple explicit duration without binding a base duration to a skill."""
    words = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    }
    pattern = (r"\b(\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten)\s*"
               r"(years?|months?)\b")
    matches = list(re.finditer(pattern, text, re.I))
    if not matches:
        return None
    match = matches[-1]
    raw = match.group(1).lower()
    number = float(words.get(raw, raw))
    return round(number * 12) if match.group(2).lower().startswith("year") else round(number)


def _infer_experience_scope(source_clause: str) -> tuple[str, int | None]:
    text = re.sub(r"\s+", " ", source_clause or "").strip().lower()
    full_term = (
        "full term", "entire term", "entire period", "throughout",
        "for all ", "during all ", "all years", "all months",
    )
    if any(marker in text for marker in full_term) or re.search(
            r"\ball\s+(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
            r"(?:years?|months?)\b", text):
        return "full_term", _duration_months(text)

    # An independently stated duration must be close to the skill-bound phrase.
    explicit = re.search(
        r"\b(?:at least\s+)?(?:\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten)\s*"
        r"(?:years?|months?)\s+(?:(?:of\s+)?experience\s+)?(?:in|with|using|developing|performing)\b",
        text,
    )
    if explicit:
        return "explicit_duration", _duration_months(explicit.group(0))

    some_experience = (
        "experience must include", "experience to include", "experience includes",
        "experience with", "experience in", "experience using", "experience developing",
        "experience performing", "must have experience", "including experience",
    )
    if any(marker in text for marker in some_experience):
        return "some_experience", None
    return "standalone", None


def _degree_key(value: Any) -> str | None:
    text = re.sub(r"[^a-z]", "", str(value or "").lower())
    if not text or text in {"none", "nodegree"}:
        return "none"
    if "highschool" in text or "ged" in text:
        return "high_school"
    if "associate" in text:
        return "associates"
    if "bachelor" in text or text in {"bs", "ba"}:
        return "bachelors"
    if "master" in text or text in {"ms", "ma", "mba"}:
        return "masters"
    if any(item in text for item in ("jurisdoctor", "medicaldoctor", "professional")):
        return "professional"
    if "doctor" in text or "phd" in text:
        return "doctorate"
    return None


def _needs_atomic_repair(raw: dict[str, Any]) -> bool:
    controlling = (
        "experience must include", "full term", "entire term", "entire period",
        "of the required experience", "years must be", "months must be",
    )
    for route_key in ("primary", "alternative"):
        route = raw.get(route_key)
        if not isinstance(route, dict):
            continue
        seen: set[tuple[str, str]] = set()
        for item in route.get("special_requirements") or []:
            if not isinstance(item, dict):
                continue
            text = re.sub(r"\s+", " ", str(item.get("text") or "")).strip().casefold()
            source = re.sub(
                r"\s+", " ", str(item.get("source_clause") or text)).strip().casefold()
            pair = (text, source)
            if pair in seen:
                return True
            seen.add(pair)
            duration_count = len(re.findall(
                r"\b(?:\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten)\s*"
                r"(?:years?|months?)\b", text, re.I))
            if any(marker in text for marker in controlling) or duration_count > 1:
                return True
            if text == source and (
                    any(marker in source for marker in controlling)
                    or ";" in source.rstrip(";")):
                return True
        # Over-split detection: two or more entries whose texts are fragments
        # of the SAME semicolon/bullet/number-delimited segment of a shared
        # source clause were split below the atomic floor (e.g. "assortment"
        # and "fulfillment" carved out of one listed item). The only permitted
        # multi-entry segment is distinct explicit durations (AWS/24 months
        # and Tableau/12 months from one clause).
        by_clause: dict[str, list[dict[str, Any]]] = {}
        for item in route.get("special_requirements") or []:
            if not isinstance(item, dict):
                continue
            # Collapse spaces/tabs but keep newlines so bullet and numbered
            # list markers survive for segment splitting below.
            clause = re.sub(
                r"[^\S\n]+", " ", str(item.get("source_clause") or "")).strip()
            if clause:
                by_clause.setdefault(clause.casefold(), []).append(item)
        for clause, items in by_clause.items():
            if len(items) < 2:
                continue
            segments = [re.sub(r"\s+", " ", seg).strip() for seg in re.split(
                r";|\n\s*[-•*]\s+|\n\s*(?:\d+|[a-z]|[ivx]+)[.)]\s+",
                clause) if seg.strip()]
            seg_hits: dict[int, list[dict[str, Any]]] = {}
            for item in items:
                text = re.sub(
                    r"\s+", " ", str(item.get("text") or "")).strip().casefold()
                if not text:
                    continue
                matched = [i for i, seg in enumerate(segments) if text in seg]
                if len(matched) == 1:
                    seg_hits.setdefault(matched[0], []).append(item)
            for hits in seg_hits.values():
                if len(hits) < 2:
                    continue
                if all(item.get("experience_scope") == "explicit_duration"
                       and item.get("required_months")
                       for item in hits):
                    continue
                return True
    return False


def _ensure_atomic_requirements(raw: dict[str, Any],
                                remote: bool = False) -> dict[str, Any]:
    if not _needs_atomic_repair(raw):
        return raw
    repaired = _chat([{
        "type": "text",
        "text": ATOMIC_REPAIR_PROMPT + json.dumps(raw, ensure_ascii=False),
    }], remote=remote)
    if _needs_atomic_repair(repaired):
        raise VLMError(
            "A complex PWD experience clause could not be separated into reliable "
            "skill-and-duration requirements; review the PWD wording manually")
    return repaired


def _requirement_set_has_values(requirements: Any) -> bool:
    if not isinstance(requirements, dict):
        return False
    return any((
        _nullable_text(requirements.get("education_level")),
        _nullable_text(requirements.get("other_degree")),
        _clean_list(requirements.get("fields_of_study")),
        _nullable_text(requirements.get("second_degree")),
        _positive_int(requirements.get("training_months")),
        _clean_list(requirements.get("training_fields")),
        _positive_int(requirements.get("experience_months")),
        _nullable_text(requirements.get("experience_occupation")),
        requirements.get("special_requirements"),
    ))


def _effective_alternative(
    primary: dict[str, Any], alternative: dict[str, Any]
) -> tuple[dict[str, Any], set[str]]:
    """Fill unchanged alternative-route groups from the primary route.

    Section F.c commonly states only the qualifications that differ from
    Section F.b. Blank F.c groups therefore continue to use the corresponding
    F.b requirements. This prevents an alternate route from silently shedding
    a license, language, training, or other requirement that still applies.
    """
    effective = dict(alternative)
    inherited: set[str] = set()
    groups = {
        "education": ("education_level", "other_degree", "fields_of_study", "second_degree"),
        "training": ("training_months", "training_fields"),
        "experience": ("experience_months", "experience_occupation"),
    }
    for group, keys in groups.items():
        present = any(
            _clean_list(alternative.get(key)) if key in {"fields_of_study", "training_fields"}
            else alternative.get(key)
            for key in keys
        )
        if present:
            continue
        for key in keys:
            effective[key] = primary.get(key)
        inherited.add(group)
    if alternative.get("special_requirements_mode") == "replace":
        effective["special_requirements"] = alternative.get("special_requirements") or []
    else:
        merged: dict[str, dict[str, Any]] = {}
        for item in primary.get("special_requirements") or []:
            if isinstance(item, dict) and _nullable_text(item.get("text")):
                copied = dict(item)
                copied["inherited_from_primary"] = True
                merged[str(item["text"]).strip().casefold()] = copied
        for item in alternative.get("special_requirements") or []:
            if isinstance(item, dict) and _nullable_text(item.get("text")):
                copied = dict(item)
                copied["inherited_from_primary"] = False
                merged[str(item["text"]).strip().casefold()] = copied
        effective["special_requirements"] = list(merged.values())
    return effective, inherited


def extract_pwd_requirements(path: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    base = extract_9141(path)
    content, _ = _document_content(path, PWD_PROMPT, pwd=True)
    # PWDs contain no PII, so a configured remote model is allowed here;
    # EVL extraction below never sets remote and always stays local.
    remote = bool(PWD_LLM_URL and PWD_LLM_MODEL and PWD_LLM_API_KEY)
    raw = _ensure_atomic_requirements(_chat(content, remote=remote),
                                      remote=remote)
    structured = {
        "job_title": _nullable_text(raw.get("job_title")) or base.get("job_title"),
        "primary": _clean_requirement_set(raw.get("primary")),
        "alternative": (_clean_requirement_set(raw.get("alternative"))
                        if isinstance(raw.get("alternative"), dict) else None),
        "extraction_notes": _clean_list(raw.get("extraction_notes")),
    }
    # Preserve reliable values already obtained by the deterministic extractor.
    primary = structured["primary"]
    primary["education_level"] = primary["education_level"] or base.get("education_required")
    primary["experience_months"] = (
        primary["experience_months"] or base.get("experience_months_required"))
    primary["experience_occupation"] = (
        primary["experience_occupation"] or base.get("experience_occupation"))
    base["requirements"] = structured
    return base, build_atomic_requirements(structured)


def extract_evl(path: str, evl_id: str, filename: str) -> dict[str, Any]:
    content, text = _document_content(path, EVL_PROMPT)
    raw = _chat(content)
    return _clean_letter(raw, text, evl_id, filename)


def extract_evl_text(text: str, evl_id: str, filename: str) -> dict[str, Any]:
    """Extract an EVL from OCR/text supplied by a structured caller."""
    document_text = str(text or "")[:MAX_TEXT_CHARS]
    if not document_text.strip():
        raise ValueError(f"{filename} contains no letter text")
    raw = _chat([{
        "type": "text",
        "text": f"{EVL_PROMPT}\n\nDOCUMENT TEXT:\n{document_text}",
    }])
    return _clean_letter(raw, document_text, evl_id, filename)


def _clean_letter(
    raw: dict[str, Any], text: str, evl_id: str, filename: str
) -> dict[str, Any]:
    relationship = str(raw.get("writer_relationship") or "unknown")
    if relationship not in RELATIONSHIP_LABELS:
        relationship = "unknown"
    experience_components = []
    for item in raw.get("experience_components") or []:
        if not isinstance(item, dict) or not _nullable_text(item.get("item")):
            continue
        experience_components.append({
            "item": _nullable_text(item.get("item")),
            "start_date": _iso_date(item.get("start_date")),
            "end_date": _iso_date(item.get("end_date")),
            "duration_months": _positive_int(item.get("duration_months")),
            "applies_to_full_employment": _nullable_bool(
                item.get("applies_to_full_employment")),
            "source_quote": _nullable_text(item.get("source_quote")),
        })
    letter = {
        "id": evl_id,
        "filename": filename,
        "beneficiary_name": _nullable_text(raw.get("beneficiary_name")),
        "employer_name": _nullable_text(raw.get("employer_name")),
        "employer_address": _nullable_text(raw.get("employer_address")),
        "writer_name": _nullable_text(raw.get("writer_name")),
        "writer_title": _nullable_text(raw.get("writer_title")),
        "writer_address": _nullable_text(raw.get("writer_address")),
        "writer_relationship": relationship,
        "writer_relationship_label": RELATIONSHIP_LABELS[relationship],
        "written_on_employer_behalf": _nullable_bool(raw.get("written_on_employer_behalf")),
        "on_letterhead": _nullable_bool(raw.get("on_letterhead")),
        "signed": _nullable_bool(raw.get("signed")),
        "start_date": _iso_date(raw.get("start_date")),
        "end_date": _iso_date(raw.get("end_date")),
        "currently_employed": _nullable_bool(raw.get("currently_employed")),
        "full_time": _nullable_bool(raw.get("full_time")),
        "hours_per_week": _number(raw.get("hours_per_week")),
        "job_titles": _clean_list(raw.get("job_titles")),
        "explicit_facts": _clean_list(raw.get("explicit_facts")),
        "experience_components": experience_components,
        "source_quotes": _clean_list(raw.get("source_quotes")),
        "uncertainties": _clean_list(raw.get("uncertainties")),
        "document_text": text,
    }
    return letter


def _nullable_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _iso_date(value: Any) -> str | None:
    text = _nullable_text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def build_atomic_requirements(structured: dict[str, Any]) -> list[dict[str, Any]]:
    """Build degree-selected routes whose checklists contain EVL evidence only."""
    routes: list[dict[str, Any]] = []
    primary = structured.get("primary") if isinstance(structured.get("primary"), dict) else {}
    for route_id, label in (("primary", "Primary requirements"),
                            ("alternative", "Alternative requirements")):
        req = structured.get(route_id)
        if not isinstance(req, dict):
            continue
        if route_id == "alternative" and not _requirement_set_has_values(req):
            continue
        inherited_groups: set[str] = set()
        if route_id == "alternative":
            req, inherited_groups = _effective_alternative(primary, req)
        items: list[dict[str, Any]] = []

        def add(
            key: str,
            category: str,
            text: str,
            expected: Any = None,
            experience_scope: str = "standalone",
            required_months: int | None = None,
            source_clause: str | None = None,
            inherited_override: bool | None = None,
        ) -> None:
            group = ("special" if key.startswith("special_") else
                     "education" if category == "education" else category)
            items.append({"id": f"{route_id}.{key}", "route": route_id,
                          "category": category, "text": text, "expected": expected,
                          "experience_scope": experience_scope,
                          "required_months": required_months,
                          "source_clause": source_clause or text,
                          "inherited_from_primary": (
                              group in inherited_groups if inherited_override is None
                              else inherited_override)})

        level = _nullable_text(req.get("education_level"))
        other = _nullable_text(req.get("other_degree"))
        education = None
        education_text = "No degree requirement"
        if level and level.lower() != "none":
            education = other if level.lower().startswith("other") and other else level
            education_text = education if (
                re.search(r"\b(degree|diploma|ged)\b", education, re.I)
                or "high school" in education.lower()
            ) else f"{education} degree"
        fields = _clean_list(req.get("fields_of_study"))
        second = _nullable_text(req.get("second_degree"))
        qualification = {
            "education_level": education,
            "education_key": _degree_key(education),
            "education_display": education_text,
            "fields_of_study": fields,
            "second_degree": second,
        }
        months = _positive_int(req.get("training_months"))
        training = _clean_list(req.get("training_fields"))
        if months:
            add("training_duration", "training", f"{months} months of training", months,
                experience_scope="explicit_duration", required_months=months)
        if training:
            add("training_fields", "training", "Training in " + " or ".join(training), training)
        base_months = _positive_int(req.get("experience_months"))
        occupation = _nullable_text(req.get("experience_occupation"))
        if base_months:
            text = f"{base_months} months of employment experience"
            if occupation:
                text += f" in {occupation}"
            add("experience", "base_experience", text,
                {"months": base_months, "occupation": occupation},
                experience_scope="base_experience", required_months=base_months)
        elif occupation:
            add("experience_occupation", "base_experience",
                f"Employment experience in {occupation}", occupation,
                experience_scope="base_experience")
        for index, special in enumerate(req.get("special_requirements") or [], 1):
            if not isinstance(special, dict) or not _nullable_text(special.get("text")):
                continue
            source_clause = _nullable_text(special.get("source_clause")) or str(special["text"])
            scope = str(special.get("experience_scope") or "").strip().lower()
            required_months = _positive_int(special.get("required_months"))
            if scope not in EXPERIENCE_SCOPES:
                scope, inferred_months = _infer_experience_scope(source_clause)
                required_months = required_months or inferred_months
            if scope == "full_term":
                required_months = base_months
            if scope == "explicit_duration" and not required_months:
                scope = "ambiguous"
            add(f"special_{index}", str(special.get("category") or "other"),
                str(special["text"]).strip(), str(special["text"]).strip(),
                experience_scope=scope, required_months=required_months,
                source_clause=source_clause,
                inherited_override=special.get("inherited_from_primary"))
        if items:
            experience_display = (
                f"{base_months // 12:g} year{'s' if base_months != 12 else ''} experience"
                if base_months and base_months % 12 == 0
                else f"{base_months} months experience" if base_months
                else "No stated experience duration"
            )
            field_display = " in " + " or ".join(fields) if fields else ""
            education_choice = education_text + field_display
            if second:
                education_choice += f" + second degree: {second}"
            routes.append({
                "id": route_id,
                "label": label,
                "qualification": qualification,
                "experience_months": base_months,
                "experience_occupation": occupation,
                "selection_label": f"{education_choice} + {experience_display}",
                "requirements": items,
            })
    return routes


def select_qualification_route(
    routes: list[dict[str, Any]],
    selected_route_id: str | None = None,
    beneficiary_education: dict[str, Any] | str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Select the experience route explicitly or from Graphite degree data."""
    if not routes:
        raise RouteSelectionError("The PWD contains no usable qualification route")
    if selected_route_id:
        route = next((item for item in routes if item["id"] == selected_route_id), None)
        if not route:
            raise RouteSelectionError(f"Unknown PWD qualification route: {selected_route_id}")
        return route, {
            "source": "user_selected_route",
            "route_id": route["id"],
            "beneficiary_degree": None,
            "message": "The user selected the education/experience option shown on the PWD.",
        }

    degree = (beneficiary_education.get("degree") or
              beneficiary_education.get("degree_level") or
              beneficiary_education.get("level")) if isinstance(
                  beneficiary_education, dict) else beneficiary_education
    degree_key = _degree_key(degree) if degree is not None else None
    if degree_key is not None:
        beneficiary_rank = DEGREE_RANK.get(degree_key)
        candidates = []
        for route in routes:
            route_key = (route.get("qualification") or {}).get("education_key")
            route_rank = DEGREE_RANK.get(route_key)
            if route_key == degree_key or (
                    beneficiary_rank is not None and route_rank is not None
                    and route_rank <= beneficiary_rank):
                candidates.append((route_rank if route_rank is not None else -1, route))
        if candidates:
            best_rank = max(rank for rank, _ in candidates)
            best = [route for rank, route in candidates if rank == best_rank]
            if len(best) == 1:
                route = best[0]
                return route, {
                    "source": "beneficiary_education",
                    "route_id": route["id"],
                    "beneficiary_degree": _nullable_text(degree),
                    "beneficiary_degree_key": degree_key,
                    "message": (
                        "The route was selected from the beneficiary's stored degree level. "
                        "Degree field, equivalency, and any second-degree requirement remain "
                        "separate legal-team checks."
                    ),
                }
            raise RouteSelectionError(
                "More than one PWD route matches the beneficiary's degree; select a route explicitly")
        raise RouteSelectionError(
            f"No PWD education/experience option matches beneficiary degree {degree!s}")

    if len(routes) == 1:
        route = routes[0]
        return route, {
            "source": "only_route",
            "route_id": route["id"],
            "beneficiary_degree": None,
            "message": "The PWD contains one education/experience option.",
        }
    raise RouteSelectionError(
        "Select the beneficiary's PWD education/experience option before reviewing the EVLs")


def _coverage_assessments(routes: list[dict[str, Any]], letters: list[dict[str, Any]]) -> dict[str, Any]:
    requirements = [item for route in routes for item in route["requirements"]]
    letter_payload = []
    for letter in letters:
        letter_payload.append({
            "id": letter["id"],
            "filename": letter["filename"],
            "extracted_facts": letter.get("explicit_facts", []),
            "job_titles": letter.get("job_titles", []),
            "start_date": letter.get("start_date"),
            "end_date": letter.get("end_date"),
            "currently_employed": letter.get("currently_employed"),
            "full_time": letter.get("full_time"),
            "hours_per_week": letter.get("hours_per_week"),
            "source_quotes": letter.get("source_quotes", []),
            "experience_components": letter.get("experience_components", []),
            "document_text": letter.get("document_text", "")[:MAX_TEXT_CHARS],
        })
    prompt = (COVERAGE_PROMPT + "\n\nPWD REQUIREMENTS:\n" +
              json.dumps(requirements, ensure_ascii=False) +
              "\n\nEXPERIENCE VERIFICATION LETTERS:\n" +
              json.dumps(letter_payload, ensure_ascii=False))
    return _chat([{"type": "text", "text": prompt}], max_tokens=8000)


def _formal_findings(letter: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def finding(code: str, level: str, message: str) -> None:
        findings.append({"code": code, "level": level, "evl_id": letter["id"],
                         "filename": letter["filename"], "message": message})

    missing_writer = [label for key, label in (
        ("writer_name", "writer name"), ("writer_title", "writer title"))
        if not letter.get(key)]
    if not letter.get("writer_address") and not letter.get("employer_address"):
        missing_writer.append("writer/address information")
    if missing_writer:
        finding("EVL-DOC-001", "missing",
                "Missing regulatory writer information: " + ", ".join(missing_writer) + ".")
    if not letter.get("employer_name"):
        finding("EVL-DOC-002", "review", "The employer is not clearly identified.")
    if not letter.get("start_date") or (
            not letter.get("end_date") and not letter.get("currently_employed")):
        finding("EVL-DOC-003", "missing",
                "The employment period cannot be calculated from exact start/end information.")
    if letter.get("full_time") is None and letter.get("hours_per_week") is None:
        finding("EVL-DOC-004", "review",
                "The letter does not state full-time/part-time status or weekly hours.")
    if letter.get("signed") is False:
        finding("EVL-DOC-005", "missing", "The submitted letter appears unsigned.")
    elif letter.get("signed") is None:
        finding("EVL-DOC-005", "review", "A signature could not be confirmed.")
    if letter.get("on_letterhead") is False:
        finding("EVL-DOC-006", "review", "The letter does not appear to use employer letterhead.")
    return findings


def _support_advisory(letter: dict[str, Any]) -> dict[str, Any] | None:
    relationship = letter.get("writer_relationship")
    if relationship not in RELATIONSHIP_ADVISORY:
        return None
    label = RELATIONSHIP_LABELS.get(relationship, relationship)
    return {
        "code": "EVL-SUPPORT-001",
        "level": "advisory",
        "evl_id": letter["id"],
        "filename": letter["filename"],
        "relationship": relationship,
        "message": (
            f"This appears to be a {label.lower()} letter. Consider including proof that an "
            "employer-issued letter was unavailable and objective employment records such as "
            "payroll, tax, contract, personnel, or government employment records. If the case "
            "ultimately relies on affidavits because both primary and secondary evidence are "
            "unavailable, consider at least two affidavits from non-parties with direct personal "
            "knowledge. This is a supporting-evidence advisory, not a finding that the letter is "
            "insufficient."
        ),
    }


def build_report(
    pwd: dict[str, Any],
    routes: list[dict[str, Any]],
    letters: list[dict[str, Any]],
    model_assessments: dict[str, Any],
    qualification_selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    valid_statuses = ("covered", "partial", "missing", "unclear")
    valid_evl_ids = {letter["id"] for letter in letters}

    def normalized(text: Any) -> str:
        return re.sub(r"\s+", " ", str(text or "")).strip().casefold()

    evidence_by_evl = {
        letter["id"]: normalized(" ".join([
            letter.get("document_text", ""),
            *letter.get("source_quotes", []),
        ]))
        for letter in letters
    }
    by_id: dict[str, dict[str, Any]] = {}
    for assessment in model_assessments.get("assessments") or []:
        if not isinstance(assessment, dict):
            continue
        req_id = str(assessment.get("requirement_id") or "")
        status = str(assessment.get("status") or "unclear")
        if req_id and status in valid_statuses:
            evl_ids = [item for item in _clean_list(assessment.get("evl_ids"))
                       if item in valid_evl_ids]
            candidate_quotes = _clean_list(assessment.get("evidence_quotes"))
            quote_sources = evl_ids or list(valid_evl_ids)
            evidence_quotes = [quote for quote in candidate_quotes
                               if normalized(quote) and any(
                                   normalized(quote) in evidence_by_evl[evl_id]
                                   for evl_id in quote_sources)]
            explanation = str(assessment.get("explanation") or "").strip()
            if status in {"covered", "partial"} and not evidence_quotes:
                status = "unclear"
                explanation = (explanation + " " if explanation else "") + (
                    "The stated evidence quote could not be verified against the extracted letter text.")
            by_id[req_id] = {
                "status": status,
                "evl_ids": evl_ids,
                "evidence_quotes": evidence_quotes,
                "explanation": explanation,
            }

    route_reports = []
    all_items: list[dict[str, Any]] = []
    for route in routes:
        items = []
        for requirement in route["requirements"]:
            assessment = by_id.get(requirement["id"], {
                "status": "unclear", "evl_ids": [], "evidence_quotes": [],
                "explanation": "The local model did not return an assessment for this requirement.",
            })
            item = {**requirement, **assessment}
            items.append(item)
            all_items.append(item)
        counts = {status: sum(1 for item in items if item["status"] == status)
                  for status in valid_statuses}
        status = "covered" if items and counts["covered"] == len(items) else (
            "gaps" if counts["missing"] or counts["partial"] else "review")
        route_reports.append({**route, "requirements": items, "counts": counts, "status": status})

    formal = [finding for letter in letters for finding in _formal_findings(letter)]
    advisories = [advisory for letter in letters
                  if (advisory := _support_advisory(letter)) is not None]
    counts = {status: sum(1 for item in all_items if item["status"] == status)
              for status in valid_statuses}
    complete_routes = [route["id"] for route in route_reports if route["status"] == "covered"]
    overall = "covered" if complete_routes else (
        "gaps" if counts["missing"] or counts["partial"] else "review")
    public_letters = [{key: value for key, value in letter.items() if key != "document_text"}
                      for letter in letters]
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "pwd": pwd,
        "qualification_selection": qualification_selection,
        "routes": route_reports,
        "letters": public_letters,
        "document_findings": formal,
        "supporting_evidence_advisories": advisories,
        "summary": {
            "status": overall,
            "letters_reviewed": len(letters),
            "total_requirements": len(all_items),
            **counts,
            "complete_routes": complete_routes,
        },
        "methodology": {
            "coverage_rule": "Explicit EVL language only; no inference from titles or generalized duties.",
            "route_rule": (
                "Education selects the applicable PWD route; the EVL must cover that route's "
                "experience and other document requirements."
            ),
            "duration_rule": (
                "Some-experience, full-term, and independently stated duration clauses are "
                "evaluated according to their distinct PWD wording."
            ),
            "advisory_rule": (
                "Coworker and former-manager letters trigger supporting-evidence guidance, "
                "not automatic insufficiency."
            ),
            "authorities": [
                {
                    "citation": "Current ETA-9141, Sections F.b and F.c",
                    "rule": "Source of the primary and alternative job-requirement checklists.",
                    "url": ("https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/"
                            "Form%20ETA-9141%20-%20508%20Compliant%20-%20"
                            "Expires%2007-31-2026.pdf"),
                },
                {
                    "citation": "8 CFR 204.5(g)(1)",
                    "rule": "Writer identity/address/title and experience or training evidence.",
                    "url": ("https://www.ecfr.gov/current/title-8/chapter-I/subchapter-B/"
                            "part-204/section-204.5#p-204.5(g)(1)"),
                },
                {
                    "citation": "8 CFR 103.2(b)(2)",
                    "rule": "Primary evidence, secondary evidence, and affidavit framework.",
                    "url": ("https://www.ecfr.gov/current/title-8/chapter-I/subchapter-B/"
                            "part-103/section-103.2#p-103.2(b)(2)"),
                },
            ],
        },
    }


def pwd_route_options(pwd_path: str) -> dict[str, Any]:
    """Extract a PWD and return its selectable education/experience options."""
    pwd, routes = extract_pwd_requirements(pwd_path)
    if not routes:
        raise VLMError("No education/experience options could be extracted from the PWD")
    return {"pwd": pwd, "route_options": routes}


def _routes_from_pwd(pwd: dict[str, Any]) -> list[dict[str, Any]]:
    structured = pwd.get("requirements") if isinstance(pwd, dict) else None
    if not isinstance(structured, dict):
        raise ValueError("PWD data must include the extracted 'requirements' object")
    routes = build_atomic_requirements(structured)
    if not routes:
        raise VLMError("No education/experience options could be built from the PWD")
    return routes


def compare_files(
    pwd_path: str,
    evl_files: list[tuple[str, str]],
    selected_route_id: str | None = None,
    beneficiary_education: dict[str, Any] | str | None = None,
    extracted_pwd: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract a PWD and EVLs, assess explicit coverage, and build a report.

    ``evl_files`` contains ``(saved_path, original_filename)`` tuples.
    """
    if extracted_pwd is not None:
        pwd = extracted_pwd
        routes = _routes_from_pwd(pwd)
    else:
        pwd, routes = extract_pwd_requirements(pwd_path)
    route, selection = select_qualification_route(
        routes, selected_route_id=selected_route_id,
        beneficiary_education=beneficiary_education)
    letters = [extract_evl(path, f"EVL-{index}", filename)
               for index, (path, filename) in enumerate(evl_files, 1)]
    model_assessments = _coverage_assessments([route], letters)
    report = build_report(pwd, [route], letters, model_assessments, selection)
    report["route_options"] = routes
    return report


def compare_structured(
    pwd: dict[str, Any],
    letter_inputs: list[dict[str, Any]],
    selected_route_id: str | None = None,
    beneficiary_education: dict[str, Any] | str | None = None,
) -> dict[str, Any]:
    """Graphite entry point using structured PWD data and OCR/extracted EVL text."""
    routes = _routes_from_pwd(pwd)
    route, selection = select_qualification_route(
        routes, selected_route_id=selected_route_id,
        beneficiary_education=beneficiary_education)
    letters = []
    for index, item in enumerate(letter_inputs, 1):
        if not isinstance(item, dict):
            raise ValueError("Each letter must be an object with filename and text")
        filename = _nullable_text(item.get("filename")) or f"EVL-{index}.txt"
        letters.append(extract_evl_text(
            str(item.get("text") or item.get("document_text") or item.get("fullText") or ""),
            str(item.get("id") or f"EVL-{index}"), filename))
    if not letters:
        raise ValueError("At least one experience verification letter is required")
    model_assessments = _coverage_assessments([route], letters)
    report = build_report(pwd, [route], letters, model_assessments, selection)
    report["route_options"] = routes
    return report
