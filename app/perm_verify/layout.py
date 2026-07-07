"""Annotated-form overlay for PERM verification results.

Maps each flag's section_item to the extracted field's on-page coordinates
(recorded by extract_9089 in form['_layout']) and renders each PDF page to
a base64 PNG, so the frontend can display the actual form with markers.

Marker semantics:
  RED / YELLOW  — a flag references this field (tooltip = flag message)
  OK (green)    — required field extracted with a value and not flagged
"""
from __future__ import annotations
import base64
import io

import pdfplumber

from .rules import REQUIRED_FIELDS, _get

# flag section_item -> schema path (beyond the REQUIRED_FIELDS inverse)
EXTRA_ITEM_PATHS = {
    "E.3": "E_job_wage.offered_wage_raw",
    "H.c.1": "H_recruitment.swa_job_order_start",
    "H.c.2b": "H_recruitment.ad1_date",
    "H.c.3b": "H_recruitment.ad2_date",
    "H.d": "H_recruitment.additional_steps.employer_website",
    "H.d.7": "H_recruitment.additional_steps.employee_referral",
    "H.e": "H_recruitment.notice_of_posting",
    "H.e.1b": "H_recruitment.notice_of_posting",
    "H.e.1f": "H_recruitment.notice_of_posting",
    "H.b": "H_recruitment.supervised_recruitment",
    "H.b.1c": "H_recruitment.supervised_recruitment",
    "H.b.1d": "H_recruitment.supervised_recruitment",
    "B/C": "B_poc.email",
    "F.c.1": "F_worksite.other_geographic_areas",
    "F.b.2": "F_worksite.appendix_b_attached",
    "G.4b": "G_job_info.kellogg_suitable_combination",
    "G.5/G.5a": "G_job_info.relying_solely_on_experience_with_employer",
    "G.2a": "G_job_info.live_in_1yr_experience",
    "G.2b": "G_job_info.live_in_contract_executed",
    "G.5a": "G_job_info.experience_substantially_comparable",
    "G.5b": "G_job_info.employer_paid_training",
    "AppA.B": "appendix_A.education",
    "AppA.E": "appendix_A.work_experience",
}
ITEM_PATHS = {item: path for item, path in REQUIRED_FIELDS}
ITEM_PATHS.update(EXTRA_ITEM_PATHS)


def _coords_for_item(item, fields):
    path = ITEM_PATHS.get(item)
    if path is None and "/" in item:                # "G.5/G.5a"
        path = ITEM_PATHS.get(item.split("/")[0])
    if path is None and item.count(".") >= 2:       # "H.e.1b" -> "H.e"
        path = ITEM_PATHS.get(".".join(item.split(".")[:2]))
    return fields.get(path) if path else None


def build_overlay(result, pdf_path, dpi=96):
    form = result.get("form", {})
    layout = form.get("_layout", {}) or {}
    fields = layout.get("fields", {})
    pages_meta = layout.get("pages", [])

    markers = []
    flagged_paths = set()
    for i, fl in enumerate(result.get("flags", [])):
        c = _coords_for_item(fl["section_item"], fields)
        if not c:
            continue
        flagged_paths.add(ITEM_PATHS.get(fl["section_item"]))
        markers.append({
            "kind": fl["level"], "page": c["page"], "x": c["x"], "y": c["y"],
            "rule_id": fl["rule_id"], "section_item": fl["section_item"],
            "message": fl["message"], "flag_index": i,
        })
    for item, path in REQUIRED_FIELDS:
        c = fields.get(path)
        if not c or path in flagged_paths:
            continue
        v = _get(form, path)
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        markers.append({"kind": "OK", "page": c["page"], "x": c["x"],
                        "y": c["y"], "section_item": item,
                        "message": f"{item} present and unflagged"})

    images = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            im = page.to_image(resolution=dpi).original
            buf = io.BytesIO()
            im.save(buf, format="PNG", optimize=True)
            images.append(base64.b64encode(buf.getvalue()).decode())

    return {"pages": pages_meta, "images": images, "markers": markers}
