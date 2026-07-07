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
from typing import Optional

from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response

from perm_verify.engine import verify

router = APIRouter(prefix="/api/perm-verify", tags=["perm-verify"])


def _save_upload(upload: UploadFile, tmpdir: str) -> str:
    dest = Path(tmpdir) / (upload.filename or "upload.pdf")
    with dest.open("wb") as f:
        shutil.copyfileobj(upload.file, f)
    return str(dest)


@router.post("/run")
async def run_verification(
    form_9089: UploadFile = File(...),
    form_9141: Optional[UploadFile] = File(None),
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
        p9089 = _save_upload(form_9089, tmpdir)
        p9141 = _save_upload(form_9141, tmpdir) if form_9141 else None
        try:
            result = await run_in_threadpool(
                verify, p9089, fd, cite, 3, p9141)
        except Exception as exc:  # extraction/rule errors -> readable 500
            raise HTTPException(500, f"Verification failed: {exc}")
        if render:
            from perm_verify.layout import build_overlay
            result["overlay"] = await run_in_threadpool(
                build_overlay, result, p9089)
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
