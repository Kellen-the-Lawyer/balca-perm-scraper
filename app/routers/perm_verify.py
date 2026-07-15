"""
PERM Verification API Router
============================
POST /api/perm-verify/run
  multipart form:
    form_9089    (file, required)  — FLAG-printed ETA-9089 PDF
    form_9141    (file, optional)  — ETA-9141 determination PDF (Tier 3 + O*NET)
    filing_date  (str,  optional)  — YYYY-MM-DD; defaults to today (review date)
    cite         (bool, optional)  — attach supporting rag_chunks to each flag

Returns the full engine result: extracted form, extracted PWD, filing window,
flags (with citations/support), and summary counts.
"""
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from perm_verify.engine import verify, verify_data

router = APIRouter(prefix="/api/perm-verify", tags=["perm-verify"])


@router.post("/verify-data")
async def run_verification_data(payload: dict = Body(...)):
    """Structured-data verification for external callers (Graphite).

    Body: {
      "form":        {A_employer, B_poc, ..., H_recruitment, appendix_A},
      "pwd":         {pwd_case_number, pw_minimum, pw_per, soc_code, ...}  # optional
      "filing_date": "YYYY-MM-DD",   # optional; defaults to today (review date)
      "cite":        false           # optional; attach supporting rag_chunks
    }
    Returns the same report shape as /run (minus PDF layout data).
    """
    form = payload.get("form")
    if not isinstance(form, dict):
        raise HTTPException(422, "payload must include a 'form' object")
    fd = None
    if payload.get("filing_date"):
        try:
            fd = datetime.strptime(payload["filing_date"], "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(422, "filing_date must be YYYY-MM-DD")
    pwd = payload.get("pwd") if isinstance(payload.get("pwd"), dict) else None
    try:
        return await run_in_threadpool(
            verify_data, form, fd, bool(payload.get("cite", False)), 3, pwd)
    except Exception as exc:
        raise HTTPException(500, f"Verification failed: {exc}")


@router.get("/schema")
async def form_schema():
    """The ETA-9089 field schema (section layout expected by /verify-data)."""
    import json as _json
    from pathlib import Path as _P
    p = _P(__file__).resolve().parent.parent / "perm_verify" / "form_9089_schema.json"
    return _json.loads(p.read_text())


@router.get("/drafting-rules")
async def drafting_rules():
    """Machine-readable drafting constraints for external drafting UIs."""
    from perm_verify.rules import (REQUIRED_FIELDS, MANDATORY_STEP_KEYS,
                                   PROFESSIONAL_MIN_ADDITIONAL_STEPS)
    from perm_verify.extract_9089 import SEC_H_STEPS
    from pathlib import Path as _P
    inv = (_P(__file__).resolve().parent.parent / "perm_verify"
           / "RULES_INVENTORY.md")
    return {
        "required_fields": [{"section_item": s, "path": p}
                            for s, p in REQUIRED_FIELDS],
        "mandatory_recruitment_steps": list(MANDATORY_STEP_KEYS),
        "additional_step_keys": [k for k, _ in SEC_H_STEPS],
        "professional_min_additional_steps": PROFESSIONAL_MIN_ADDITIONAL_STEPS,
        "timing": {
            "quiet_period_days": 30,
            "recruitment_max_age_days": 180,
            "swa_job_order_min_days": 30,
            "notice_of_posting_business_days": 10,
        },
        "date_format": "M/D/YYYY (form fields); YYYY-MM-DD (filing_date)",
        "rules_inventory_md": inv.read_text() if inv.exists() else None,
    }


def _save_upload(upload: UploadFile, tmpdir: str) -> str:
    dest = Path(tmpdir) / (upload.filename or "upload.pdf")
    with dest.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
    return str(dest)


@router.post("/run")
async def run_verification(
    form_9089: List[UploadFile] = File(...),
    form_9141: Optional[UploadFile] = File(None),
    appendix_a: Optional[UploadFile] = File(None),
    filing_date: Optional[str] = Form(None),
    cite: bool = Form(False),
    render: bool = Form(False),
):
    fd = None
    if filing_date:
        try:
            fd = datetime.strptime(filing_date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(422, "filing_date must be YYYY-MM-DD")

    tmpdir = tempfile.mkdtemp(prefix="permverify_")
    try:
        paths_9089 = [_save_upload(f, tmpdir) for f in form_9089]
        p9141 = _save_upload(form_9141, tmpdir) if form_9141 else None
        papx = [_save_upload(appendix_a, tmpdir)] if appendix_a else []
        try:
            result = await run_in_threadpool(
                verify, paths_9089, fd, cite, 3, p9141, papx or None)
        except Exception as exc:  # extraction/rule errors -> readable 500
            raise HTTPException(500, f"Verification failed: {exc}")
        if render:
            is_draft = (((result.get("form") or {}).get("meta") or {})
                        .get("form_variant") == "flag_print_summary_draft")
            if not is_draft:
                from perm_verify.layout import build_overlay
                result["overlay"] = await run_in_threadpool(
                    build_overlay, result, paths_9089[0])
        return result
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@router.post("/export-pdf")
async def export_pdf(payload: dict = Body(...)):
    from perm_verify.report_pdf import build_pdf
    try:
        pdf_bytes = await run_in_threadpool(build_pdf, payload)
    except Exception as exc:
        raise HTTPException(500, f"PDF export failed: {exc}")
    case = ((payload.get("form") or {}).get("meta") or {}).get(
        "perm_case_number", "report")
    return Response(pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition":
                             f'attachment; filename="perm-verify-{case}.pdf"'})
