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
import json
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


def _save_named_upload(upload: UploadFile, tmpdir: str, prefix: str) -> str:
    """Save an upload under a unique, traversal-safe temporary filename."""
    filename = Path(upload.filename or "upload").name
    dest = Path(tmpdir) / f"{prefix}-{filename}"
    with dest.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
    if dest.stat().st_size > 30 * 1024 * 1024:
        dest.unlink(missing_ok=True)
        raise HTTPException(413, f"{filename} exceeds the 30 MB file limit")
    return str(dest)


@router.post("/evl-pwd-options")
async def extract_evl_pwd_options(form_9141: UploadFile = File(...)):
    """Read a PWD and return its selectable education/experience routes."""
    if Path(form_9141.filename or "").suffix.lower() != ".pdf":
        raise HTTPException(422, "The prevailing wage determination must be a PDF")
    tmpdir = tempfile.mkdtemp(prefix="evloptions_")
    try:
        pwd_path = _save_named_upload(form_9141, tmpdir, "pwd")
        from perm_verify.evl_compare import VLMError, pwd_route_options
        try:
            result = await run_in_threadpool(pwd_route_options, pwd_path)
        except VLMError as exc:
            raise HTTPException(503, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        result.setdefault("pwd", {}).setdefault("meta", {})["source_pdf"] = (
            Path(form_9141.filename or "ETA-9141.pdf").name)
        return result
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@router.post("/compare-evls")
async def compare_evl_requirements(
    form_9141: UploadFile = File(...),
    evl_files: List[UploadFile] = File(...),
    selected_route_id: Optional[str] = Form(None),
    beneficiary_degree: Optional[str] = Form(None),
    beneficiary_field: Optional[str] = Form(None),
    extracted_pwd_json: Optional[str] = Form(None),
):
    """Compare explicit EVL language with current ETA-9141 requirements."""
    if Path(form_9141.filename or "").suffix.lower() != ".pdf":
        raise HTTPException(422, "The prevailing wage determination must be a PDF")
    if not evl_files:
        raise HTTPException(422, "Upload at least one experience verification letter")
    if len(evl_files) > 20:
        raise HTTPException(422, "A comparison can include at most 20 letters")
    supported = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".txt", ".md"}
    unsupported = [Path(f.filename or "").name for f in evl_files
                   if Path(f.filename or "").suffix.lower() not in supported]
    if unsupported:
        raise HTTPException(422, "Unsupported EVL format: " + ", ".join(unsupported))

    tmpdir = tempfile.mkdtemp(prefix="evlcompare_")
    try:
        pwd_path = _save_named_upload(form_9141, tmpdir, "pwd")
        saved_evls = []
        for index, upload in enumerate(evl_files, 1):
            path = _save_named_upload(upload, tmpdir, f"evl-{index}")
            saved_evls.append((path, Path(upload.filename or f"EVL-{index}").name))
        from perm_verify.evl_compare import RouteSelectionError, VLMError, compare_files
        extracted_pwd = None
        if extracted_pwd_json:
            try:
                extracted_pwd = json.loads(extracted_pwd_json)
            except json.JSONDecodeError as exc:
                raise HTTPException(422, f"extracted_pwd_json is invalid JSON: {exc}")
            if not isinstance(extracted_pwd, dict):
                raise HTTPException(422, "extracted_pwd_json must be a JSON object")
        beneficiary_education = None
        if beneficiary_degree:
            beneficiary_education = {
                "degree": beneficiary_degree,
                "field_of_study": beneficiary_field,
            }
        try:
            result = await run_in_threadpool(
                compare_files, pwd_path, saved_evls, selected_route_id,
                beneficiary_education, extracted_pwd)
        except RouteSelectionError as exc:
            raise HTTPException(422, str(exc))
        except VLMError as exc:
            raise HTTPException(503, str(exc))
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"EVL comparison failed: {exc}")
        # Do not expose a temporary local path that is deleted after this request.
        result.setdefault("pwd", {}).setdefault("meta", {})["source_pdf"] = (
            Path(form_9141.filename or "ETA-9141.pdf").name)
        return result
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


@router.post("/compare-evls-data")
async def compare_evl_requirements_data(payload: dict = Body(...)):
    """Structured EVL comparison entry point for Graphite.

    Body: {
      "pwd": {"requirements": {...}},
      "beneficiary_education": {"degree": "Master's", "field_of_study": "..."},
      "selected_route_id": null,
      "letters": [{"id": "...", "filename": "...", "text": "OCR text..."}]
    }
    """
    pwd = payload.get("pwd")
    letters = payload.get("letters")
    education = payload.get("beneficiary_education")
    if not isinstance(pwd, dict):
        raise HTTPException(422, "payload must include a structured 'pwd' object")
    if not isinstance(letters, list) or not letters:
        raise HTTPException(422, "payload must include a non-empty 'letters' array")
    if len(letters) > 20:
        raise HTTPException(422, "A comparison can include at most 20 letters")
    if education is not None and not isinstance(education, (dict, str)):
        raise HTTPException(422, "beneficiary_education must be an object or degree string")
    from perm_verify.evl_compare import (
        RouteSelectionError, VLMError, compare_structured,
    )
    try:
        return await run_in_threadpool(
            compare_structured, pwd, letters, payload.get("selected_route_id"), education)
    except RouteSelectionError as exc:
        raise HTTPException(422, str(exc))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except VLMError as exc:
        raise HTTPException(503, str(exc))
    except Exception as exc:
        raise HTTPException(500, f"EVL comparison failed: {exc}")


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
