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


# US state two-letter abbreviations (all 50 states + DC + territories)
_US_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","DC","FL","GA","GU","HI","ID",
    "IL","IN","IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT",
    "NE","NV","NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","PR","RI",
    "SC","SD","TN","TX","UT","VT","VA","VI","WA","WV","WI","WY",
}


def _split_city_state_zip(raw_city: str, raw_state: str) -> tuple:
    """
    The ETA-9141 work-location value row is extracted by pdfplumber as a single
    space-separated string, e.g.:

        "Plantation FL Broward County 33322"

    The form layout is always:  City  State  County  Zip
    This function splits that blob into (city, state), discarding county and zip.

    Also handles the simpler cases produced by some PDF layouts:
        raw_city="Richardson TX 75080",  raw_state=""
        raw_city="Richardson TX",        raw_state=""
        raw_city="Richardson",           raw_state="TX 75080"
        raw_city="New York",             raw_state="NY"   <- already correct
    """
    city  = raw_city.strip()
    state = raw_state.strip()

    # Strip trailing zip (5-digit or ZIP+4) from either field.
    zip_re = re.compile(r'\s+\d{5}(?:-\d{4})?\s*$')
    city  = zip_re.sub('', city).strip()
    state = zip_re.sub('', state).strip()

    # If state is already a clean 2-letter code, also strip any county
    # that may be stuck to the end of city.
    if re.fullmatch(r'[A-Z]{2}', state) and state in _US_STATES:
        m = re.search(r'^(.*?)\s+([A-Z]{2})\b', city)
        if m and m.group(2) in _US_STATES:
            city = _clean(m.group(1))
        return city, state

    # Scan the city string for the FIRST 2-letter US state code word.
    # In "Plantation FL Broward County", FL is the first match and it is
    # a valid state code — everything before it is the city.
    for m in re.finditer(r'\b([A-Z]{2})\b', city):
        code = m.group(1)
        if code in _US_STATES:
            return _clean(city[:m.start()]), code

    # Also handle state field containing extra text (e.g. "TX 75080" or "TX Dallas County").
    if state:
        for m in re.finditer(r'\b([A-Z]{2})\b', state):
            code = m.group(1)
            if code in _US_STATES:
                return city, code

    # Fallback: return as-is.
    return city, state


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
        "jobTitle":         "",
        "city":             "",
        "stateVal":         "",
        "travel":           "no",
        "travelDetail":     "",
        "telecommuteDetail":"",
        "jdRef":            "",
        "primDeg":          "",
        "mrRef":            "",
        "pwdWage":          "",
        "pwdWageMin":       None,
        "pwdWageAlt":       None,
        "wageUnit":         "Year",
    }

    version = _detect_version(pages)

    if version == "new":
        _extract_new(pages, result)
    else:
        _extract_old(pages, result)

    # Format final wage string e.g. "$153,601 / Year"
    # Also format pwdWageMin / pwdWageAlt as dollar strings for the frontend banner.
    if result["pwdWage"] and result["wageUnit"]:
        raw = result["pwdWage"].replace("$", "").replace(",", "").strip()
        try:
            result["pwdWage"] = "${:,.0f} / {}".format(float(raw), result["wageUnit"])
        except ValueError:
            result["pwdWage"] = f"${raw} / {result['wageUnit']}"
    # Keep numeric floats for pwdWageMin / pwdWageAlt so the frontend can compare them.
    # (The PermComparer.jsx banner already does: pwdWageMin !== pwdWageAlt)

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
    # pdfplumber produces the title on the SAME line as the label:
    #   "1.Job title * Research Scientist III"
    # The separator after the asterisk may be just one space.
    m = re.search(
        r"1\.\s*Job title\s*\*?\s*([^\n]{2,80})",
        body, re.IGNORECASE,
    )
    if m:
        title = _clean(m.group(1))
        # Drop anything from the next field label onward ("2.Job duties…")
        title = re.split(r'\s+2\.', title)[0].strip()
        if title:
            result["jobTitle"] = title

    # ── F.a.2  Job Duties ─────────────────────────────────────────────────────
    m = re.search(
        r"2\.\s*Job duties[^\n]*\n(.*?)(?=\nForm ETA|\Z)",
        body, re.IGNORECASE | re.DOTALL,
    )
    inline_duties = ""
    if m:
        candidate = _clean(_strip_jd_boilerplate(m.group(1)))
        if candidate and not re.search(r"please see addendum", candidate, re.IGNORECASE):
            inline_duties = candidate

    addendum_duties = _find_addendum(pages, r"F\.a\.2|Section F\.a\.2|Job Duties")
    result["jdRef"] = _strip_footer(addendum_duties or inline_duties)

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
    result["mrRef"] = _strip_footer(addendum_mr or inline_mr)

    # ── F.d.3  Travel ─────────────────────────────────────────────────────────
    # New form (2025+) uses U+F071 (\uf071) for BOTH checked and unchecked
    # boxes — the glyph is identical regardless of state.  The only reliable
    # signal is what follows the "No" option on the checkbox line:
    #   Yes + inline detail : "\uf071 Yes \uf071 No 10% domestic travel…"
    #   Yes + addendum      : "\uf071 Yes \uf071 No Please See Addendum"
    #   No                  : "\uf071 Yes \uf071 No"   (nothing after "No")
    #
    # Strategy: find the line with the travel checkbox, then check if there is
    # any non-whitespace text after the "No" option.

    travel_yes = False
    travel_inline_detail = ""

    # Find the checkbox line that immediately follows the "Will travel" label
    m_label = re.search(
        r"3\.\s*Will travel be required[^\n]*\n([^\n]{1,200})",
        body, re.IGNORECASE,
    )
    if m_label:
        cb_line = m_label.group(1).strip()
        # Strip the two checkbox glyphs + "Yes" + glyph + "No" prefix,
        # then see if anything substantive remains.
        after_no = re.sub(r"^.*?\bNo\b\s*", "", cb_line, count=1, flags=re.IGNORECASE).strip()
        if after_no:
            travel_yes = True
            if not re.search(r"please see addendum", after_no, re.IGNORECASE):
                travel_inline_detail = after_no
        # else: nothing after "No" → No is checked
    else:
        # Fallback: scan the block with old-style checkmarks
        m = re.search(r"3\.\s*Will travel be required.{0,500}", body, re.IGNORECASE | re.DOTALL)
        if m:
            tb = m.group(0)
            yes_checked = bool(re.search(_CHECK + r"\s*Yes", tb, re.IGNORECASE))
            no_checked  = bool(re.search(_CHECK + r"\s*No",  tb, re.IGNORECASE))
            if not yes_checked:
                yes_checked = bool(re.search(r"[☑✘✗✓✔x]\s*Yes", tb, re.IGNORECASE))
            if not no_checked:
                no_checked  = bool(re.search(r"[☑✘✗✓✔x]\s*No",  tb, re.IGNORECASE))
            travel_yes = yes_checked and not no_checked

    result["travel"] = "yes" if travel_yes else "no"

    # ── F.d.3.a  Travel detail text ───────────────────────────────────────────
    # Priority: (1) dedicated addendum F.d.3.a, (2) inline detail on checkbox
    # line, (3) travel language embedded in job duties addendum.
    if travel_yes:
        travel_addendum = _find_addendum(pages, r"F\.d\.3\.a|Travel Details|F\.d\.3")
        if travel_addendum:
            # Strip page footer that bleeds in at end of addendum text
            travel_addendum = re.sub(
                r"\s*FOR DEPARTMENT OF LABOR USE ONLY.*$", "",
                travel_addendum, flags=re.IGNORECASE | re.DOTALL,
            ).strip()
            result["travelDetail"] = travel_addendum
        elif travel_inline_detail:
            result["travelDetail"] = travel_inline_detail
        else:
            # Some PWDs embed travel language in the job duties addendum text
            jd_text = result.get("jdRef", "")
            m_t = re.search(
                r"(\d+%\s*(?:domestic\s+)?travel[^.]*\.)",
                jd_text, re.IGNORECASE,
            )
            if m_t:
                result["travelDetail"] = m_t.group(1).strip()

    # ── Telecommute — extract from travel detail or job duties ─────────────────
    for source in [result.get("travelDetail", ""), result.get("jdRef", ""), result.get("mrRef", "")]:
        m_tc = re.search(
            r"([Tt]elecommut(?:ing|e)[^.]*\.)",
            source,
        )
        if m_tc:
            result["telecommuteDetail"] = m_tc.group(1).strip()
            break

    # ── F.e  City & State ─────────────────────────────────────────────────────
    # Three possible layouts pdfplumber produces:
    # (A) Labels on one line, values on next:
    #     "3. City *  4. State *  5. County *\nRichardson  TX  Dallas County"
    # (B) Each label+value on its own line:
    #     "3. City *\nRichardson\n4. State *\nTX"
    # (C) Label and value on same line (table cell):
    #     "3. City *   Richardson"

    # Try layout A first (most common in new form)
    # pdfplumber sometimes collapses city/state/zip to single-space separation,
    # so we always normalise through _split_city_state_zip.
    m = re.search(
        r'3\.\s*City[^\n]*4\.\s*State[^\n]*\n(\S[^\n]+)',
        body, re.IGNORECASE,
    )
    if m:
        parts = re.split(r' {2,}', m.group(1).strip())
        raw_city  = _clean(parts[0]) if len(parts) >= 1 else ""
        raw_state = _clean(parts[1]) if len(parts) >= 2 else ""
        result["city"], result["stateVal"] = _split_city_state_zip(raw_city, raw_state)

    # Layout B — city on next line
    if not result["city"]:
        m = re.search(r'3\.\s*City\s*\*?\s*\n([^\n]{1,60})', body, re.IGNORECASE)
        if m:
            raw_city = _clean(m.group(1).split("4.")[0])
            city_fixed, state_fixed = _split_city_state_zip(raw_city, result["stateVal"])
            result["city"]    = city_fixed
            if state_fixed:
                result["stateVal"] = state_fixed
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

    # ── G.4 & G.5  Prevailing Wages ──────────────────────────────────────────
    # Item 4 = wage based on minimum requirements (always present).
    # Item 5 = wage based on alternative requirements (present when employer
    #           provided alternative qualification paths; uses DOL fill-char
    #           underscores that must be stripped before parsing).
    # We store both, then set pwdWage to whichever is higher.
    wage_section = "\n".join(pages[4:7]) if len(pages) > 4 else full

    # Item 4 — minimum requirements wage
    m4 = re.search(
        r"4\.\s*Prevailing wage[^\n]*\non the minimum job requirements[^\n]*\$([^\n]{1,30})",
        wage_section, re.IGNORECASE,
    )
    if not m4:
        m4 = re.search(
            r"4\.\s*Prevailing wage[^\n]*\n[^\n]*\$\s*([\d,]{4,})",
            wage_section, re.IGNORECASE,
        )
    wage4 = _parse_wage_amount(m4.group(1)) if m4 else None

    # Item 5 — alternative requirements wage (field filled with underscores)
    m5 = re.search(
        r"5\.\s*Prevailing wage[^\n]*\nThis wage is based on the alternative[^\n]*\$([^\n]{1,40})",
        wage_section, re.IGNORECASE,
    )
    if not m5:
        m5 = re.search(
            r"5\.\s*Prevailing wage[^\n\$]*\$([^\n]{1,40})",
            wage_section, re.IGNORECASE,
        )
    wage5 = _parse_wage_amount(m5.group(1)) if m5 else None

    # Fallback: grab first dollar amount ≥5 digits in wage section
    if wage4 is None:
        mf = re.search(r"\$\s*([\d,]{5,})", wage_section)
        if mf:
            wage4 = _parse_wage_amount(mf.group(0))

    result["pwdWageMin"] = wage4
    result["pwdWageAlt"] = wage5

    # Use the higher wage as the operative prevailing wage
    candidates = [w for w in [wage4, wage5] if w is not None]
    if candidates:
        result["pwdWage"] = str(int(max(candidates)))

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
    # pdfplumber may produce the title on the same line as the label:
    #   "1.Job Title * Senior Software Engineer"
    m = re.search(
        r"1\.\s*Job Title\s*\*?\s*([^\n]{2,80})",
        body, re.IGNORECASE,
    )
    if m:
        title = _clean(m.group(1))
        title = re.split(r'\s+2\.', title)[0].strip()
        if title:
            result["jobTitle"] = title

    # ── E.a.5  Job Duties ─────────────────────────────────────────────────────
    m = re.search(
        r"5\.\s*Job duties[^\n]*\n(.*?)(?=\n6\.\s*Will travel|\Z)",
        p2, re.IGNORECASE | re.DOTALL,
    )
    if m:
        duties = _strip_jd_boilerplate(m.group(1))
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
        raw_city  = _clean(parts[0]) if len(parts) >= 1 else ""
        raw_state = _clean(parts[1]) if len(parts) >= 2 else ""
        result["city"], result["stateVal"] = _split_city_state_zip(raw_city, raw_state)

    # Layout B — newline
    if not result["city"]:
        m = re.search(r'3\.\s*City\s*\*?\s*\n([^\n]{1,60})', body, re.IGNORECASE)
        if m:
            raw_city = _clean(m.group(1).split("4.")[0].split("5.")[0])
            city_fixed, state_fixed = _split_city_state_zip(raw_city, result["stateVal"])
            result["city"]    = city_fixed
            if state_fixed:
                result["stateVal"] = state_fixed
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

    # ── F.4 & F.5  Prevailing Wages ──────────────────────────────────────────
    # Old form: item 4 = minimum wage, item 5 = alternative wage (if any).
    # Item 5 on old forms uses the same underscore fill-character pattern.
    m4 = re.search(
        r"4\.\s*Prevailing wage[\s\S]{0,40}?\$([^\n]{1,30})",
        p4, re.IGNORECASE,
    )
    wage4 = _parse_wage_amount(m4.group(1)) if m4 else None

    m5 = re.search(
        r"5\.\s*Prevailing wage[^\n\$]*\$([^\n]{1,40})",
        p4, re.IGNORECASE,
    )
    wage5 = _parse_wage_amount(m5.group(1)) if m5 else None

    result["pwdWageMin"] = wage4
    result["pwdWageAlt"] = wage5

    candidates = [w for w in [wage4, wage5] if w is not None]
    if candidates:
        result["pwdWage"] = str(int(max(candidates)))

    # ── F.5  Per unit ─────────────────────────────────────────────────────────
    unit_block = re.search(r"5\.\s*Per:.*?(?:\n[^\n]*){0,3}", p4, re.IGNORECASE | re.DOTALL)
    if unit_block:
        result["wageUnit"] = _parse_unit(unit_block.group(0))


# ── Shared helpers ────────────────────────────────────────────────────────────

def _parse_wage_amount(text: str):
    """
    Extract a numeric wage from a string that may contain PDF fill-character
    underscores, e.g. ' 5__9_0_9_3___ ._0_0____' -> 59093.0
    The caller passes the text AFTER the '$', so no '$' is required.
    Returns float or None.
    """
    # Strip underscores that DOL uses as fill characters in typed fields
    cleaned = text.replace('_', '')
    # Match optional '$', then digits (with optional commas), optional decimals
    m = re.search(r'\$?\s*([\d,]{4,})(?:\s*\.\s*\d+)?', cleaned)
    if m:
        try:
            val = float(m.group(1).replace(',', ''))
            if val > 0:
                return val
        except ValueError:
            pass
    return None


def _strip_jd_boilerplate(text: str) -> str:
    """
    Remove ETA-9141 form instruction text that bleeds into the job duties field.

    pdfplumber captures the label row as one match, so the captured group starts
    with the tail of the 2-line instruction header that overflows onto the next
    line, e.g.:
        "MUST begin in this space. For mail-in applications, an addendum may be
         used to complete the response fully.) Design and build software..."

    We strip any leading text up through and including the closing paren of that
    instruction, then clean up page-number footers.
    """
    # Strip everything up to and including the instruction closing paren.
    # Handles both single-line and wrapped versions.
    boilerplate_patterns = [
        # Tail of the wrapped 2-line header (most common in new form)
        r"(?s)^.*?used to complete the response fully\.\)\s*",
        # Single-line version where entire instruction fits on one line
        r"(?s)^.*?begin in this space\.?\s*(?:For mail-in applications[^)]*\))?\s*",
        # Bare "MUST begin in this space." with no following paren
        r"(?s)^.*?begin in this space\.\s*",
    ]
    for pat in boilerplate_patterns:
        cleaned = re.sub(pat, "", text, count=1, flags=re.IGNORECASE)
        if cleaned != text:
            text = cleaned
            break
    # Strip page-number footer that sometimes bleeds in at the end
    text = re.sub(r"Page \d+ of \d+.*$", "", text, flags=re.DOTALL | re.IGNORECASE)
    return text.strip()


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


_FOOTER_RE = re.compile(
    r"\s*(?:FOR DEPARTMENT OF LABOR USE ONLY|PW Tracking Number|Page \d+ of \d+).*$",
    re.IGNORECASE | re.DOTALL,
)

def _strip_footer(text: str) -> str:
    """Strip DOL page-footer boilerplate that pdfplumber captures at end of addendum pages."""
    return _FOOTER_RE.sub("", text).strip()


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
                    body = _clean(_strip_footer(body_m.group(1)))
                    if body:
                        return body
                # Fallback: grab everything after the bold ADDENDUM header
                body_m = re.search(
                    r"ADDENDUM\s*\n[^\n]*\n(.*?)(?=Page \d+|\Z)",
                    page_text, re.IGNORECASE | re.DOTALL,
                )
                if body_m:
                    body = _clean(_strip_footer(body_m.group(1)))
                    if body:
                        return body
    return ""

