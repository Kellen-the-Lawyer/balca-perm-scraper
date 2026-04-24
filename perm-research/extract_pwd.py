"""
ETA-9141 Prevailing Wage Determination — pdfplumber extractor
Supports both the older form layout (2021, sections E/F) and
the newer form layout (2025+, sections F/G).
No API key required.
"""
import io
import re
import pdfplumber


def _clean(s: str) -> str:
    """Collapse whitespace."""
    return re.sub(r"\s+", " ", s or "").strip()


# pdfplumber renders checked boxes as these characters.
# U+2718 (✘ Heavy Ballot X) is used in newer forms; others in older ones.
# Note: must be a regular string (not r-string) so unicode escapes are resolved.
_CHECK = "[\u2718\u2717\u2612\u2611\u2714\u2713x]"


def extract_pwd_from_bytes(pdf_bytes: bytes) -> dict:
    """Accept raw PDF bytes (used by FastAPI UploadFile)."""
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        pages = [p.extract_text() or "" for p in pdf.pages]
    return _extract_from_pages(pages)


def extract_pwd(pdf_path: str) -> dict:
    """Accept a file path (useful for CLI testing)."""
    with pdfplumber.open(pdf_path) as pdf:
        pages = [p.extract_text() or "" for p in pdf.pages]
    return _extract_from_pages(pages)


def _detect_version(pages: list) -> str:
    """
    Return 'new' if this is the 2025+ form layout (sections F/G),
    or 'old' for the 2021 layout (sections E/F).
    The new form has 'F. Job Offer Information' and 'G. Prevailing Wage'.
    """
    full = "\n".join(pages[:6])
    if re.search(r"\bG\.\s*Prevailing Wage", full, re.IGNORECASE):
        return "new"
    return "old"


def _extract_from_pages(pages: list) -> dict:
    result = {
        "jobTitle": "",
        "city":     "",
        "stateVal": "",
        "travel":   "no",
        "jdRef":    "",
        "primDeg":  "",
        "mrRef":    "",
        "pwdWage":  "",
        "wageUnit": "Year",
    }

    version = _detect_version(pages)

    if version == "new":
        _extract_new(pages, result)
    else:
        _extract_old(pages, result)

    # Format final wage string e.g. "$153,601 / Year"
    if result["pwdWage"] and result["wageUnit"]:
        raw = result["pwdWage"].replace("$", "").replace(",", "").strip()
        try:
            result["pwdWage"] = "${:,.0f} / {}".format(float(raw), result["wageUnit"])
        except ValueError:
            result["pwdWage"] = f"${raw} / {result['wageUnit']}"

    return result


# ── NEW FORM (2025+): sections F = Job Offer, G = Prevailing Wage ─────────────

def _extract_new(pages: list, result: dict):
    # Pages are 0-indexed. The form body spans pages 1-5 (indices 1-5) in most
    # new-layout PDFs, but some have an extra cover or attachment page that shifts
    # everything. We search across a range of candidate pages for each field to
    # be robust to page-offset variations.
    full = "\n".join(pages)          # entire document for fallback searches
    body = "\n".join(pages[1:7])     # pages 1-6 cover all form sections

    # ── F.a.1  Job Title ──────────────────────────────────────────────────────
    # Value may be on same line as label ("1. Job title *    Data Scientist II")
    # or on the next line.
    m = re.search(
        r"1\.\s*Job title\s*\*?\s*(?:\n|[ \t]{2,})([^\n*]{2,80})",
        body, re.IGNORECASE,
    )
    if m:
        result["jobTitle"] = _clean(m.group(1))

    # ── F.a.2  Job Duties ─────────────────────────────────────────────────────
    m = re.search(
        r"2\.\s*Job duties[^\n]*\n(.*?)(?=\nForm ETA|\Z)",
        body, re.IGNORECASE | re.DOTALL,
    )
    inline_duties = ""
    if m:
        candidate = _clean(m.group(1))
        if not re.search(r"please see addendum", candidate, re.IGNORECASE):
            inline_duties = candidate

    addendum_duties = _find_addendum(pages, r"F\.a\.2|Section F\.a\.2|Job Duties")
    result["jdRef"] = addendum_duties or inline_duties

    # ── F.b.1  Education / Primary Degree ─────────────────────────────────────
    edu_block = re.search(
        r"1\.\s*Education:.*?(?=2\.\s*Does the employer require a second|\Z)",
        body, re.IGNORECASE | re.DOTALL,
    )
    result["primDeg"] = _parse_degree(edu_block.group(0) if edu_block else body)

    # ── F.b.5  Special Skills ─────────────────────────────────────────────────
    m = re.search(
        r"5\.\s*Special skills or other requirements.*?(?=\nc\.\s*Alternative|\Z)",
        body, re.IGNORECASE | re.DOTALL,
    )
    inline_mr = ""
    if m:
        candidate = _clean(m.group(0))
        if not re.search(r"please see addendum", candidate, re.IGNORECASE):
            inline_mr = candidate

    addendum_mr = _find_addendum(pages, r"F\.b\.5|Section F\.b\.5|Special Skills")
    result["mrRef"] = addendum_mr or inline_mr

    # ── F.d.3  Travel ─────────────────────────────────────────────────────────
    # The travel field label and checked value may be on the same line.
    # Also handle "Telecommuting is permitted" in the travel note as a yes.
    m = re.search(r"3\.\s*Will travel be required.{0,500}", body, re.IGNORECASE | re.DOTALL)
    if m:
        tb = m.group(0)
        yes_checked = bool(re.search(_CHECK + r"\s*Yes", tb, re.IGNORECASE))
        no_checked  = bool(re.search(_CHECK + r"\s*No",  tb, re.IGNORECASE))
        # Some PDFs render the checkmark directly adjacent: "☑Yes"
        if not yes_checked:
            yes_checked = bool(re.search(r"[☑✘✗✓✔x]\s*Yes", tb, re.IGNORECASE))
        if not no_checked:
            no_checked  = bool(re.search(r"[☑✘✗✓✔x]\s*No",  tb, re.IGNORECASE))
        result["travel"] = "yes" if yes_checked and not no_checked else "no"

    # ── F.e  City & State ─────────────────────────────────────────────────────
    # Three possible layouts pdfplumber produces:
    # (A) Labels on one line, values on next:
    #     "3. City *  4. State *  5. County *\nRichardson  TX  Dallas County"
    # (B) Each label+value on its own line:
    #     "3. City *\nRichardson\n4. State *\nTX"
    # (C) Label and value on same line (table cell):
    #     "3. City *   Richardson"

    # Try layout A first (most common in new form)
    m = re.search(
        r'3\.\s*City[^\n]*4\.\s*State[^\n]*\n(\S[^\n]+)',
        body, re.IGNORECASE,
    )
    if m:
        parts = re.split(r' {2,}', m.group(1).strip())
        if len(parts) >= 1:
            result["city"] = _clean(parts[0])
        if len(parts) >= 2:
            result["stateVal"] = _clean(parts[1])

    # Layout B — city on next line
    if not result["city"]:
        m = re.search(r'3\.\s*City\s*\*?\s*\n([^\n]{1,60})', body, re.IGNORECASE)
        if m:
            result["city"] = _clean(m.group(1).split("4.")[0])
    # Layout B — state on next line
    if not result["stateVal"]:
        m = re.search(r'4\.\s*State\s*\*?\s*\n([A-Z]{2})\b', body, re.IGNORECASE)
        if m:
            result["stateVal"] = _clean(m.group(1))

    # Layout C — same-line inline
    if not result["city"]:
        m = re.search(
            r'3\.\s*City\s*\*?\s+([A-Za-z][^\n\t]{1,40?}?)\s{2,}',
            body, re.IGNORECASE,
        )
        if m:
            result["city"] = _clean(m.group(1))
    if not result["stateVal"]:
        m = re.search(r'4\.\s*State\s*\*?\s+([A-Z]{2})\b', body, re.IGNORECASE)
        if m:
            result["stateVal"] = _clean(m.group(1))

    # ── G.4  Prevailing Wage ──────────────────────────────────────────────────
    # Search all pages for the wage section
    wage_section = "\n".join(pages[4:7]) if len(pages) > 4 else full
    m = re.search(
        r"4\.\s*Prevailing wage[^\n]*\n[^\n]*\$\s*([\d,]{4,})",
        wage_section, re.IGNORECASE,
    )
    if not m:
        m = re.search(r"\$\s*([\d,]{5,})\s*\.\s*00", wage_section)
    if not m:
        m = re.search(r"\$\s*([\d,]{5,})", wage_section)
    if m:
        result["pwdWage"] = m.group(1).replace(",", "")

    # ── G.4.a  Per unit ───────────────────────────────────────────────────────
    unit_block = re.search(
        r"a\.\s*Per:.*?(?:\n[^\n]*){0,3}",
        wage_section, re.IGNORECASE | re.DOTALL,
    )
    if unit_block:
        result["wageUnit"] = _parse_unit(unit_block.group(0))


# ── OLD FORM (2021): sections E = Job Offer, F = Prevailing Wage ──────────────

def _extract_old(pages: list, result: dict):
    body = "\n".join(pages[1:6])  # search across pages 1-5 for robustness
    p4 = pages[3] if len(pages) > 3 else ""

    # ── E.a.1  Job Title ──────────────────────────────────────────────────────
    # Handle both newline and same-line (table cell) placement
    m = re.search(
        r"1\.\s*Job Title\s*\*?\s*(?:\n|[ \t]{2,})([^\n*]{2,80})",
        body, re.IGNORECASE,
    )
    if m:
        result["jobTitle"] = _clean(m.group(1))

    # ── E.a.5  Job Duties ─────────────────────────────────────────────────────
    m = re.search(
        r"5\.\s*Job duties[^\n]*\n(.*?)(?=\n6\.\s*Will travel|\Z)",
        p2, re.IGNORECASE | re.DOTALL,
    )
    if m:
        duties = m.group(1)
        duties = re.sub(r"(?s)^.*?begin in this space\.?\s*\*?\s*\n?", "", duties, flags=re.IGNORECASE)
        duties = re.sub(r"Page \d+ of \d+.*$", "", duties, flags=re.DOTALL)
        result["jdRef"] = _clean(duties)

    # Also check addendum pages for job duties (some old forms use addendum too)
    if not result["jdRef"] or re.search(r"please see addendum", result["jdRef"], re.IGNORECASE):
        add = _find_addendum(pages, r"E\.a\.5|E\.5|Job Duties")
        if add:
            result["jdRef"] = add

    # ── E.a.6  Travel ─────────────────────────────────────────────────────────
    m = re.search(r"6\.\s*Will travel be required.{0,400}", p2, re.IGNORECASE | re.DOTALL)
    if m:
        tb = m.group(0)
        # A checked "Yes" means checkmark directly before "Yes".
        # The old form layout is " Yes ✘ No" when No is checked,
        # so we must NOT match a checkmark that immediately precedes "No".
        yes_checked = bool(re.search(_CHECK + r"\s*Yes", tb, re.IGNORECASE))
        no_checked  = bool(re.search(_CHECK + r"\s*No",  tb, re.IGNORECASE))
        result["travel"] = "yes" if yes_checked and not no_checked else "no"

    # ── E.b.1  Education ──────────────────────────────────────────────────────
    edu_block = re.search(
        r"1\.\s*Education.*?(?=2\.\s*Does the employer|\Z)",
        body, re.IGNORECASE | re.DOTALL,
    )
    result["primDeg"] = _parse_degree(edu_block.group(0) if edu_block else body)

    # ── E.b.5  Special Requirements ───────────────────────────────────────────
    m = re.search(
        r"5\.\s*Special Requirements[^\n]*\n(.*?)(?=\nc\.\s*Place of Employment|\Z)",
        body, re.IGNORECASE | re.DOTALL,
    )
    if m:
        sr = m.group(1)
        sr = re.sub(r"(?s)^.*?job opportunity\.?\s*\*?\s*\n?", "", sr, flags=re.IGNORECASE)
        sr = re.sub(r"Page \d+ of \d+.*$", "", sr, flags=re.DOTALL)
        result["mrRef"] = _clean(sr)

    add_mr = _find_addendum(pages, r"E\.b\.5|E\.B\.5|SPECIAL REQUIREMENTS")
    if add_mr and add_mr not in result["mrRef"]:
        sep = "\n\n" if result["mrRef"] else ""
        result["mrRef"] = result["mrRef"] + sep + add_mr

    # ── E.c  City & State ─────────────────────────────────────────────────────
    # Layout A: labels on one line, values on next
    m = re.search(
        r'3\.\s*City[^\n]*(?:4\.|5\.)\s*State[^\n]*\n(\S[^\n]+)',
        body, re.IGNORECASE,
    )
    if m:
        parts = re.split(r' {2,}', m.group(1).strip())
        if len(parts) >= 1:
            result["city"] = _clean(parts[0])
        if len(parts) >= 2:
            result["stateVal"] = _clean(parts[1])

    # Layout B — newline
    if not result["city"]:
        m = re.search(r'3\.\s*City\s*\*?\s*\n([^\n]{1,60})', body, re.IGNORECASE)
        if m:
            result["city"] = _clean(m.group(1).split("4.")[0].split("5.")[0])
    if not result["stateVal"]:
        m = re.search(r'(?:4\.|5\.)?\s*State[^\n]*\n([A-Z]{2})\b', body, re.IGNORECASE)
        if m:
            result["stateVal"] = _clean(m.group(1))

    # Layout C — same-line
    if not result["city"]:
        m = re.search(r'3\.\s*City\s*\*?\s+([A-Za-z][^\n\t]{1,40?}?)\s{2,}', body, re.IGNORECASE)
        if m:
            result["city"] = _clean(m.group(1))
    if not result["stateVal"]:
        m = re.search(r'(?:4\.|5\.)\s*State\s*[^\n]{0,10}\s+([A-Z]{2})\b', body, re.IGNORECASE)
        if m:
            result["stateVal"] = _clean(m.group(1))

    # ── F.4  Prevailing Wage ──────────────────────────────────────────────────
    m = re.search(
        r"4\.\s*Prevailing wage[\s\S]{0,40}?\$\s*([\d,]{4,}(?:\.\d+)?)",
        p4, re.IGNORECASE,
    )
    if m:
        result["pwdWage"] = m.group(1).replace(",", "")

    # ── F.5  Per unit ─────────────────────────────────────────────────────────
    unit_block = re.search(r"5\.\s*Per:.*?(?:\n[^\n]*){0,3}", p4, re.IGNORECASE | re.DOTALL)
    if unit_block:
        result["wageUnit"] = _parse_unit(unit_block.group(0))


# ── Shared helpers ────────────────────────────────────────────────────────────

DEGREE_MAP = [
    (r"\bNone\b",          "None"),
    (r"High [Ss]chool|GED","High School/GED"),
    (r"Associate",         "Associate's"),
    (r"Bachelor",          "Bachelor's"),
    (r"Master",            "Master's"),
    (r"Doctorate|Ph\.?D",  "Doctorate (Ph.D.)"),
    (r"Other degree",      "Other"),
]


def _parse_degree(text: str) -> str:
    """Find checked degree box in a block of text."""
    for pattern, label in DEGREE_MAP:
        # Require the check mark to be immediately before the degree label word,
        # with optional whitespace. Use word-boundary anchoring to avoid 'GED'
        # matching inside 'High school/GED' for a different label.
        if re.search(_CHECK + r"\s*(?:" + pattern + r")\b", text, re.IGNORECASE):
            return label
    # Fallback: no check mark found but "None" present as first item
    if re.search(r"\bNone\b", text):
        return "None"
    return ""


def _parse_unit(text: str) -> str:
    """Find checked per-unit box in a block of text."""
    for unit in ["Hour", "Week", "Bi-Weekly", "Month", "Year", "Piece Rate"]:
        if re.search(_CHECK + r"\s*" + re.escape(unit), text, re.IGNORECASE):
            return unit
    # Fallback: scan for unit word near a checked box
    if re.search(r"\bYear\b", text):
        return "Year"
    return "Year"


def _find_addendum(pages: list, section_pattern: str) -> str:
    """
    Search all pages for an ADDENDUM page matching section_pattern.
    Returns cleaned body text, or empty string if not found.
    Tries multiple addenda patterns to handle both old and new form naming.
    """
    # Build patterns to match addendum page headers
    header_patterns = [
        # New form: "Addendum for Section F.a.2: Job Duties"
        r"Addendum for Section " + section_pattern,
        # Old form: "ADDENDUM FOR SECTION E.B.5"
        r"ADDENDUM FOR SECTION " + section_pattern,
        # Generic: just the section reference in caps/mixed on an addendum page
        r"ADDENDUM[\s\S]{0,100}" + section_pattern,
    ]

    for page_text in pages[4:]:  # Addenda start from page 5 onwards
        for hpat in header_patterns:
            if re.search(hpat, page_text, re.IGNORECASE):
                # Extract content after the "Addendum for Section X:" line
                body_m = re.search(
                    r"Addendum for Section[^\n]*\n(.*?)(?=Page \d+|\Z)",
                    page_text, re.IGNORECASE | re.DOTALL,
                )
                if body_m:
                    body = _clean(body_m.group(1))
                    if body:
                        return body
                # Fallback: grab everything after the bold ADDENDUM header
                body_m = re.search(
                    r"ADDENDUM\s*\n[^\n]*\n(.*?)(?=Page \d+|\Z)",
                    page_text, re.IGNORECASE | re.DOTALL,
                )
                if body_m:
                    body = _clean(body_m.group(1))
                    if body:
                        return body
    return ""

