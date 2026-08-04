"""
Extractor for FLAG ETA-9089 **Print Summary (draft)** PDFs.

The FLAG portal's "Print Summary" renders the application as a two-column
web printout (label left in ArialMT, value right in Arial-Black), with
accordion section headers and — unlike the final certified form — the
Preliminary Questions block, Section C attorney info, and appendices.
Field item numbers match the final form's numbering, so this extractor
maps (section, item number) -> the same schema paths extract_9089 emits;
the output dict feeds engine.verify_data() unchanged.

Notes / assumptions:
- The draft never shows the prevailing wage amount (only the PWD case
  number), so Tier 3 needs the 9141 supplied separately.
- H.e (Notice of Posting) and Section I (labor condition certification)
  appear only as boilerplate statements in the printout; their presence
  is treated as an affirmative answer.
- A draft may arrive as one PDF or as main + Appendix A PDFs; extract()
  accepts a list of paths.
"""
from __future__ import annotations

import re

import pdfplumber

SECTION_RE = re.compile(
    r"^(Preliminary Questions|[A-J](\.[a-z])?:|APX [A-Z](\.[A-Z])?:|Field: Appendix)")
ITEM_RE = re.compile(r"^(\d+[a-z]?|[a-z]\.\d+(\.[a-z])?[a-z]?|\d+[a-z]\.)\s")
VALUE_MIN_X = 280  # values render right of this; bold boilerplate sits left


def looks_like_draft(pdf_path) -> bool:
    """True if the PDF is a FLAG Print Summary rather than the final form."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            text = (pdf.pages[0].extract_text() or "")[:2000]
    except Exception:
        return False
    return ("Print Summary" in text
            or "Select what form/section" in text
            or "Preliminary Questions" in text)


def _cluster_lines(words, tol=6):
    lines, cur, last_top = [], [], None
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if last_top is not None and w["top"] - last_top > tol:
            lines.append(cur)
            cur = []
        cur.append(w)
        last_top = w["top"]
    if cur:
        lines.append(cur)
    return lines


def parse_fields(paths):
    """Parse one or more Print Summary PDFs into [{section, label, value}]."""
    fields, section = [], None
    for path in paths:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                words = page.extract_words(extra_attrs=["fontname"])
                for ws in _cluster_lines(words):
                    ws = sorted(ws, key=lambda w: w["x0"])
                    lab = [w["text"] for w in ws
                           if "Arial-Black" not in w["fontname"]
                           and "SegoeUI" not in w["fontname"]]
                    blacks = [w for w in ws if "Arial-Black" in w["fontname"]]
                    boiler = any(w["x0"] < VALUE_MIN_X for w in blacks)
                    val = [] if boiler else [w["text"] for w in blacks]
                    ltext = " ".join(lab).strip()
                    vtext = " ".join(val).strip()
                    if SECTION_RE.match(ltext) and not vtext:
                        section = ltext.rstrip(":")
                        # header pseudo-field: registers boilerplate-only
                        # sections (H.e, I) and blocks label merging across
                        # section boundaries
                        fields.append({"section": section, "label": "",
                                       "value": "", "_header": True})
                        continue
                    if not ltext and not vtext:
                        continue
                    prev_header = bool(fields and fields[-1].get("_header"))
                    starts_new = bool(ITEM_RE.match(ltext)) or prev_header or \
                        (vtext and ltext and fields and fields[-1]["value"])
                    if starts_new and ltext:
                        fields.append({"section": section, "label": ltext,
                                       "value": vtext})
                    elif fields:
                        if ltext:
                            fields[-1]["label"] += " " + ltext
                        if vtext:
                            fields[-1]["value"] = (
                                fields[-1]["value"] + " " + vtext).strip()
                    elif ltext:
                        fields.append({"section": section, "label": ltext,
                                       "value": vtext})
    return fields


# ---------------------------------------------------------------------------
# (section-header prefix, item number) -> schema path
# Item numbers match the final ETA-9089 numbering used by extract_9089.
# ---------------------------------------------------------------------------

A_MAP = {"1": "legal_business_name", "2": "dba", "3": "address1",
         "4": "address2", "5": "city", "6": "state", "7": "postal_code",
         "8": "country", "9": "province", "10": "phone", "11": "extension",
         "12": "fein", "13": "naics_code",
         "14": "num_employees_in_area", "15": "year_commenced_business",
         "16": "closely_held_ownership_interest",
         "17": "familial_relationship"}

B_MAP = {"1": "last_name", "2": "first_name", "3": "middle_name",
         "4": "job_title", "5": "address1", "6": "address2", "7": "city",
         "8": "state", "9": "postal_code", "10": "country", "11": "province",
         "12": "phone", "13": "extension", "14": "email"}

C_MAP = {"1": "representation_type", "2": "last_name", "3": "first_name",
         "4": "middle_name", "5": "address1", "6": "address2", "7": "city",
         "8": "state", "9": "postal_code", "10": "country", "11": "province",
         "12": "phone", "13": "extension", "14": "email",
         "15": "law_firm_name", "16": "law_firm_fein",
         "17": "state_bar_number", "18": "state_of_good_standing",
         "19": "highest_court_name"}

D_MAP = {"1": "appendix_a_attached", "2": "dual_representation"}

E_MAP = {"1": "pwd_case_number",
         "2": "supervised_recruitment_9141_attached",
         "4": "wage_per", "5": "wage_conditions"}
# E.3 From/To handled specially (duplicate item number).

FA_MAP = {"a.1": "worksite_type", "a.2": "address1", "a.3": "address2",
          "a.4": "city", "a.5": "county", "a.6": "state",
          "a.7": "postal_code", "a.8": "msa_oes_area_code",
          "a.8.a": "msa_oes_area_title"}

FB_MAP = {"b.1": "additional_worksites", "b.2": "appendix_b_attached"}
FC_MAP = {"c.1": "other_geographic_areas"}

G_MAP = {"1": "full_time_35hrs", "2": "live_in_domestic",
         "2a": "live_in_1yr_experience", "2b": "live_in_contract_executed",
         "2c": "live_in_contract_copy_provided",
         "3": "accept_foreign_degree_equivalent",
         "4": "fw_currently_employed",
         "4a": "fw_qualifies_only_by_alternative_reqs",
         "4b": "kellogg_suitable_combination",
         "5": "relying_solely_on_experience_with_employer",
         "5a": "experience_substantially_comparable",
         "5b": "employer_paid_training", "6": "live_on_premises",
         "7": "combination_of_occupations", "8": "foreign_language",
         "9": "exceeds_svp", "10": "credentialing_service",
         "11": "employer_received_payment", "12": "layoff_6mo"}

HC_MAP = {"c.1a": "swa_job_order_start", "c.1b": "swa_job_order_end",
          "c.2": "sunday_edition_exists", "c.2a": "ad1_newspaper_name",
          "c.2b": "ad1_date", "c.3": "ad2_type", "c.3a": "ad2_name",
          "c.3b": "ad2_date"}

# H.d additional professional steps: item prefix -> step code
HD_STEPS = {"1": "job_fair", "2": "employer_website",
            "3": "job_search_website", "4": "on_campus", "5": "trade_org",
            "6": "private_firm", "7": "employee_referral",
            "8": "campus_placement", "9": "local_ethnic_newspaper",
            "10": "radio_tv"}

APXA_CONTACT_MAP = {"1": "last_name", "2": "first_name", "3": "middle_name",
                    "4": "address1", "5": "address2", "6": "city",
                    "7": "state", "8": "postal_code", "9": "country",
                    "10": "province", "11": "dob",
                    "12": "class_of_admission", "13": "a_number",
                    "14": "country_of_birth",
                    "15": "country_of_citizenship"}

OCC_TYPE_NORMALIZE = (("1a", "1a_professional"),
                      ("1b", "1b_nonprofessional"),
                      ("1c", "1c_college_university_teacher"),
                      ("1d", "1d_schedule_a_sheepherder"))


def _set(out, path, value):
    parts = path.split(".")
    d = out
    for p in parts[:-1]:
        d = d.setdefault(p, {})
    d[parts[-1]] = value


def _item_no(label):
    m = ITEM_RE.match(label)
    return m.group(1).rstrip(".") if m else None


def _num(v):
    try:
        return float(str(v).replace(",", "").replace("$", ""))
    except (ValueError, TypeError):
        return None


def _norm(v):
    """Normalize a print-summary value to match extract_9089's output.

    FLAG renders yes/no answers in lower case ('yes'), while the geometry
    extractor reads checkbox labels and yields 'Yes'.  Every rule compares
    with exact case (`yes = lambda p: str(_get(form, p)) == "Yes"` and ~30
    other sites), so without this the whole draft path silently under-flags.
    Only bare yes/no tokens are touched; free text passes through unchanged.
    """
    v = (v or "").strip()
    if v in ("", "N/A", "n/a"):
        return None
    return {"yes": "Yes", "no": "No"}.get(v.lower(), v)


def to_form(fields):
    """Map parsed fields into the extract_9089-shaped dict."""
    out = {"meta": {"form_variant": "flag_print_summary_draft"}}
    sections_seen = set()
    apx_group, apx_rec = None, {}

    def flush_apx():
        nonlocal apx_rec
        if apx_group and apx_rec:
            if apx_group == "supplemental":
                out.setdefault("appendix_C", {}).setdefault(
                    "entries", []).append(apx_rec)
            else:
                out.setdefault("appendix_A", {}).setdefault(
                    apx_group, []).append(apx_rec)
        apx_rec = {}

    for f in fields:
        sec = f["section"] or ""
        sections_seen.add(sec.split(":")[0].strip())
        if f.get("_header"):
            continue
        label, raw = f["label"], f["value"]
        val = _norm(raw)
        item = _item_no(label)

        if sec.startswith("Preliminary") or sec == "":
            if "Occupation Type" in label and val:
                occ = val
                for prefix, code in OCC_TYPE_NORMALIZE:
                    if val.lower().startswith(prefix):
                        occ = code
                        break
                _set(out, "H_recruitment.occupation_type", occ)
            elif "supervised recruitment" in label and val:
                _set(out, "H_recruitment.supervised_recruitment", val)
            continue

        if sec.startswith("A:") and item in A_MAP:
            _set(out, f"A_employer.{A_MAP[item]}", val)
        elif sec.startswith("B:") and item in B_MAP:
            _set(out, f"B_poc.{B_MAP[item]}", val)
        elif sec.startswith("C:") and item in C_MAP:
            _set(out, f"C_attorney_agent.{C_MAP[item]}", val)
        elif sec.startswith("D:") and item in D_MAP:
            _set(out, f"D_foreign_worker_flags.{D_MAP[item]}", val)
        elif sec.startswith("E:"):
            if item == "3":
                key = ("offered_wage_from"
                       if label.split()[1].lower().startswith("from")
                       else "offered_wage_to")
                _set(out, f"E_job_wage.{key}", _num(val))
            elif item in E_MAP:
                _set(out, f"E_job_wage.{E_MAP[item]}", val)
        elif sec.startswith("F.a") and item in FA_MAP:
            _set(out, f"F_worksite.{FA_MAP[item]}", val)
        elif sec.startswith("F.b") and item in FB_MAP:
            _set(out, f"F_worksite.{FB_MAP[item]}", val)
        elif sec.startswith("F.c") and item in FC_MAP:
            _set(out, f"F_worksite.{FC_MAP[item]}", val)
        elif sec.startswith("G:") and item in G_MAP:
            _set(out, f"G_job_info.{G_MAP[item]}", val)
        elif sec.startswith("H.c") and item in HC_MAP:
            _set(out, f"H_recruitment.{HC_MAP[item]}", val)
        elif sec.startswith("H.d") and item:
            m = re.match(r"^(\d+)([ab])$", item)
            if m and m.group(1) in HD_STEPS and val:
                code, ab = HD_STEPS[m.group(1)], m.group(2)
                key = "from" if ab == "a" else "to"
                _set(out,
                     f"H_recruitment.additional_steps.{code}.{key}", val)
        elif sec.startswith("APX A.A") and item in APXA_CONTACT_MAP:
            _set(out, f"appendix_A.contact.{APXA_CONTACT_MAP[item]}", val)
        elif sec.startswith(("APX A.B", "APX A.C", "APX A.D", "APX A.E")):
            group = {"APX A.B": "education", "APX A.C": "training",
                     "APX A.D": "skills", "APX A.E": "work_experience"}[
                         sec.split(":")[0].strip()]
            new_rec_label = {"education": "Education Type",
                             "training": "Training Type",
                             "skills": "Training provider",
                             "work_experience": "Employer Name"}[group]
            if group != apx_group:
                flush_apx()
                apx_group = group
            lab_clean = re.sub(r"^[A-Z] [A-Z]\w.*?(?=[A-Z][a-z])", "",
                               label).strip() or label
            if lab_clean.startswith(new_rec_label) and apx_rec:
                flush_apx()
            if val is not None:
                key = (lab_clean.lower().replace("/", "_")
                       .replace(" ", "_").replace("(", "").replace(")", ""))
                apx_rec[key] = val
        elif sec.startswith("APX C"):
            if group_c_start(label) and apx_rec and apx_group == "supplemental":
                flush_apx()
            if apx_group != "supplemental":
                flush_apx()
                apx_group = "supplemental"
            if val is not None:
                key = ("section_item" if "item number" in label
                       else "section_name" if "Section name" in label
                       else "information")
                apx_rec[key] = val
    flush_apx()

    # Boilerplate-only sections: presence in the printout == attested.
    # notice_of_posting is a list of option codes; the draft's H.e block is
    # the physical-posting statement, so its presence maps to 1b.
    if "H.e" in sections_seen:
        _set(out, "H_recruitment.notice_of_posting", ["1b_physical_notice"])
    if "I" in sections_seen:
        _set(out, "I_attestations.certify_labor_condition_statements", "Yes")
    return out, sections_seen


def group_c_start(label):
    return "item number" in label


def _dedupe(form):
    """Drop exact-duplicate appendix records. The main draft PDF already
    contains the appendices, so a standalone Appendix A upload alongside
    it duplicates every record."""
    for container, groups in (("appendix_A", ("education", "training",
                                              "skills", "work_experience")),
                              ("appendix_C", ("entries",))):
        d = form.get(container) or {}
        for g in groups:
            recs = d.get(g)
            if isinstance(recs, list):
                seen, out = set(), []
                for r in recs:
                    key = tuple(sorted(r.items()))
                    if key not in seen:
                        seen.add(key)
                        out.append(r)
                d[g] = out
    return form


def _beneficiary_name(fields):
    """(last, first) of the foreign worker from one file's parsed fields."""
    last = first = None
    for f in fields:
        sec = (f.get("section") or "")
        if not sec.startswith("APX A.A"):
            continue
        item = _item_no(f["label"])
        v = _norm(f["value"])
        if item == "1" and v:
            last = v
        elif item == "2" and v:
            first = v
        if last and first:
            break
    if last or first:
        return ((last or "").strip().upper(), (first or "").strip().upper())
    return None


def extract(paths):
    """Extract a FLAG Print Summary draft (one or more PDFs) into the
    standard 9089 form dict consumed by engine.verify_data().

    When multiple files are supplied, the foreign worker's name is read
    from each file that contains Appendix A.A; if the files disagree, the
    mismatch is recorded in meta.beneficiary_mismatch so the rules engine
    can flag documents mixed across cases (same employer, different
    worker is the classic paralegal upload error)."""
    import os
    if isinstance(paths, (str, bytes)) or hasattr(paths, "__fspath__"):
        paths = [paths]
    all_fields, per_file_names = [], []
    for p in paths:
        f = parse_fields([p])
        all_fields.extend(f)
        nm = _beneficiary_name(f)
        if nm:
            per_file_names.append(
                {"file": os.path.basename(str(p)),
                 "last_name": nm[0], "first_name": nm[1]})
    form, _ = to_form(all_fields)
    distinct = {(n["last_name"], n["first_name"]) for n in per_file_names}
    if len(distinct) > 1:
        form.setdefault("meta", {})["beneficiary_mismatch"] = per_file_names
    return _dedupe(form)
