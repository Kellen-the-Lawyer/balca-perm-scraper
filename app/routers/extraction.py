"""PDF/DOCX text extraction, extraction status, and quality signals."""
import os
import re
import json
import io
from datetime import date as _date
from typing import Any, Optional

import httpx
from fastapi import APIRouter, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import text

from core import *  # noqa: F401,F403 -- shared db, config, helpers

from extract_pwd import extract_pwd_from_bytes
from extract_experience_letter import extract_letter_from_bytes

router = APIRouter()

@router.post("/api/extract-pwd")
async def extract_pwd_endpoint(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")
    pdf_bytes = await file.read()
    try:
        result = extract_pwd_from_bytes(pdf_bytes)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Extraction failed: {e}")
    return result


@router.post("/api/extract-pwd-debug")
async def extract_pwd_debug(file: UploadFile = File(...)):
    """Returns parsed fields + raw page text for diagnosing extraction failures."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")
    pdf_bytes = await file.read()
    try:
        import pdfplumber, io
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            pages = [p.extract_text() or "" for p in pdf.pages]
        result = extract_pwd_from_bytes(pdf_bytes)
        return {
            "parsed": result,
            "page_count": len(pages),
            "pages": {f"page_{i+1}": pages[i][:2000] for i in range(min(len(pages), 8))}
        }
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Debug extraction failed: {e}")


# ── Generic PDF text extraction (no AI) ──────────────────────────────────────

def _docx_to_text(data: bytes) -> str:
    """Extract plain text from a .docx (Office Open XML) using only the stdlib.
    Preserves paragraph and table-row breaks and tab stops. No AI involved."""
    import zipfile, io, re, html
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    # Paragraph and table-row ends become newlines; tabs become tabs.
    xml = xml.replace("</w:p>", "\n").replace("</w:tr>", "\n")
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    text = html.unescape(text)
    # Collapse runs of blank lines.
    return re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", text).strip()


@router.post("/api/extract-text")
async def extract_text_endpoint(file: UploadFile = File(...)):
    """Extract all text from a PDF or Word (.docx) document. No AI involved."""
    name = (file.filename or "").lower()
    data = await file.read()
    try:
        if name.endswith(".docx"):
            text = _docx_to_text(data)
        elif name.endswith(".pdf"):
            import pdfplumber, io
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                pages = [p.extract_text() or "" for p in pdf.pages]
            text = "\n\n".join(p for p in pages if p.strip())
        elif name.endswith(".doc"):
            raise HTTPException(status_code=400, detail="Legacy .doc files are not supported — please save as .docx or PDF.")
        else:
            raise HTTPException(status_code=400, detail="File must be a PDF or Word (.docx) document.")
        if not text.strip():
            raise HTTPException(status_code=422, detail="No text could be extracted from this document.")
        return {"text": text}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Extraction failed: {e}")


async def _mark_extraction_failure(corpus: str, decision_id: int, error: str) -> None:
    table = "decisions" if corpus == "balca" else "aao_decisions"
    await database.execute(
        text(f"""
            UPDATE {table}
            SET extraction_status = 'failed',
                extraction_error = :error,
                extraction_attempts = COALESCE(extraction_attempts, 0) + 1,
                extracted_at = NOW(),
                text_extracted = FALSE
            WHERE id = :id
        """).bindparams(id=decision_id, error=error[:2000])
    )


async def _update_extracted_text(corpus: str, decision_id: int, extracted: dict[str, Any]) -> None:
    table = "decisions" if corpus == "balca" else "aao_decisions"
    await database.execute(
        text(f"""
            UPDATE {table}
            SET full_text = :full_text,
                text_extracted = TRUE,
                extraction_status = :status,
                extraction_error = NULL,
                extraction_attempts = COALESCE(extraction_attempts, 0) + 1,
                extracted_at = NOW(),
                extraction_page_count = :page_count,
                extraction_char_count = :char_count,
                extraction_quality = :quality
            WHERE id = :id
        """).bindparams(
            id=decision_id,
            full_text=extracted["full_text"],
            status="extracted" if extracted["full_text"].strip() else "empty",
            page_count=extracted["page_count"],
            char_count=extracted["char_count"],
            quality=extracted["quality"],
        )
    )


async def _extraction_targets(corpus: str, status_filter: str, limit: int, ids: list[int] | None):
    if corpus == "balca":
        table = "decisions"
        path_expr = "filename"
    elif corpus == "aao":
        table = "aao_decisions"
        path_expr = "pdf_path"
    else:
        raise HTTPException(status_code=400, detail="corpus must be 'balca' or 'aao'")

    bind: dict[str, Any] = {"limit": limit}
    conditions = []
    if ids:
        conditions.append("id = ANY(:ids)")
        bind["ids"] = ids
    elif status_filter == "repairable":
        conditions.append("""(
            extraction_status IN ('unknown', 'failed', 'empty', 'low_text', 'not_found')
            OR text_extracted IS NOT TRUE
            OR full_text IS NULL
            OR full_text = ''
        )""")
    elif status_filter != "all":
        conditions.append("extraction_status = :status")
        bind["status"] = status_filter

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    return await database.fetch_all(
        text(f"""
            SELECT id, {path_expr} AS pdf_ref, extraction_status, extraction_attempts
            FROM {table}
            {where}
            ORDER BY COALESCE(extraction_attempts, 0), id
            LIMIT :limit
        """).bindparams(**bind)
    )


@router.get("/api/extraction/status")
async def extraction_status(corpus: str = Query(default="balca")):
    if corpus == "balca":
        table = "decisions"
    elif corpus == "aao":
        table = "aao_decisions"
    else:
        raise HTTPException(status_code=400, detail="corpus must be 'balca' or 'aao'")
    rows = await database.fetch_all(text(f"""
        SELECT COALESCE(extraction_status, 'unknown') AS status,
               COUNT(*) AS count,
               SUM(CASE WHEN text_extracted IS TRUE THEN 1 ELSE 0 END) AS extracted_count,
               SUM(CASE WHEN full_text IS NULL OR full_text = '' THEN 1 ELSE 0 END) AS empty_text_count
        FROM {table}
        GROUP BY COALESCE(extraction_status, 'unknown')
        ORDER BY count DESC
    """))
    return {"corpus": corpus, "statuses": [dict(row) for row in rows]}


@router.get("/api/extraction/failures")
async def extraction_failures(
    corpus: str = Query(default="balca"),
    limit: int = Query(default=50, ge=1, le=500),
):
    if corpus == "balca":
        table = "decisions"
        label = "case_number"
    elif corpus == "aao":
        table = "aao_decisions"
        label = "COALESCE(title, filename)"
    else:
        raise HTTPException(status_code=400, detail="corpus must be 'balca' or 'aao'")
    rows = await database.fetch_all(text(f"""
        SELECT id, {label} AS label, extraction_status, extraction_error,
               extraction_attempts, extracted_at::text, extraction_char_count,
               extraction_page_count, extraction_quality
        FROM {table}
        WHERE extraction_status IN ('failed', 'empty', 'low_text', 'not_found')
           OR text_extracted IS NOT TRUE
           OR full_text IS NULL
           OR full_text = ''
        ORDER BY extracted_at DESC NULLS LAST, id
        LIMIT :limit
    """).bindparams(limit=limit))
    return {"corpus": corpus, "results": [dict(row) for row in rows]}


@router.post("/api/extraction/retry")
async def retry_extraction(data: dict):
    corpus = data.get("corpus", "balca")
    status_filter = data.get("status", "repairable")
    limit = min(int(data.get("limit", 25)), 200)
    ids = data.get("ids")
    ids = [int(i) for i in ids] if isinstance(ids, list) else None
    targets = await _extraction_targets(corpus, status_filter, limit, ids)
    results = []
    for row in targets:
        decision_id = row["id"]
        pdf_ref = row["pdf_ref"]
        path = _balca_pdf_path(pdf_ref) if corpus == "balca" else pdf_ref
        gcs_object = _balca_gcs_object(pdf_ref) if corpus == "balca" else _aao_gcs_object(pdf_ref)
        try:
            extracted = _extract_pdf_text_source(path, gcs_object)
            await _update_extracted_text(corpus, decision_id, extracted)
            results.append({
                "id": decision_id,
                "status": "extracted" if extracted["full_text"].strip() else "empty",
                "char_count": extracted["char_count"],
                "page_count": extracted["page_count"],
                "quality": extracted["quality"],
            })
        except FileNotFoundError as exc:
            error = str(exc)
            await _mark_extraction_failure(corpus, decision_id, error)
            results.append({"id": decision_id, "status": "not_found", "error": error})
        except Exception as exc:
            await _mark_extraction_failure(corpus, decision_id, str(exc))
            results.append({"id": decision_id, "status": "failed", "error": str(exc)})
    return {"corpus": corpus, "processed": len(results), "results": results}


@router.post("/api/extraction/mark")
async def mark_extraction_status(data: dict):
    corpus = data.get("corpus", "balca")
    decision_id = int(data["id"])
    status = data.get("status")
    note = data.get("note")
    if status not in {"needs_manual_review", "ignored", "not_found", "failed", "extracted"}:
        raise HTTPException(status_code=400, detail="Unsupported extraction status")
    table = "decisions" if corpus == "balca" else "aao_decisions" if corpus == "aao" else None
    if not table:
        raise HTTPException(status_code=400, detail="corpus must be 'balca' or 'aao'")
    await database.execute(
        text(f"""
            UPDATE {table}
            SET extraction_status = :status,
                extraction_error = :note,
                extracted_at = NOW()
            WHERE id = :id
        """).bindparams(id=decision_id, status=status, note=note)
    )
    return {"ok": True}


@router.post("/api/quality/refresh")
async def refresh_quality_signals(corpus: str = Query(default="balca")):
    if corpus == "balca":
        await database.execute(text("""
            UPDATE decisions d
            SET citation_quality_status = CASE
                    WHEN d.text_extracted IS NOT TRUE OR COALESCE(d.full_text, '') = '' THEN 'not_ready'
                    WHEN EXISTS (
                        SELECT 1 FROM citations c
                        WHERE c.citing_id = d.id AND c.cited_id IS NULL
                    ) THEN 'needs_review'
                    WHEN EXISTS (SELECT 1 FROM citations c WHERE c.citing_id = d.id) THEN 'ok'
                    ELSE 'no_citations'
                END,
                regulation_quality_status = CASE
                    WHEN d.text_extracted IS NOT TRUE OR COALESCE(d.full_text, '') = '' THEN 'not_ready'
                    WHEN EXISTS (
                        SELECT 1 FROM decision_regulations dr WHERE dr.decision_id = d.id
                    ) THEN 'ok'
                    ELSE 'no_regulations'
                END,
                search_quality_notes = CONCAT_WS('; ',
                    CASE
                        WHEN d.text_extracted IS NOT TRUE OR COALESCE(d.full_text, '') = ''
                        THEN 'missing extracted text'
                    END,
                    CASE
                        WHEN EXISTS (
                            SELECT 1 FROM citations c
                            WHERE c.citing_id = d.id AND c.cited_id IS NULL
                        )
                        THEN 'has unresolved citations'
                    END,
                    CASE
                        WHEN NOT EXISTS (
                            SELECT 1 FROM decision_regulations dr WHERE dr.decision_id = d.id
                        )
                        THEN 'no linked regulations'
                    END
                )
        """))
        return await quality_summary(corpus=corpus)
    if corpus == "aao":
        await database.execute(text("""
            UPDATE aao_decisions d
            SET citation_quality_status = CASE
                    WHEN d.text_extracted IS NOT TRUE OR COALESCE(d.full_text, '') = '' THEN 'not_ready'
                    ELSE 'not_applicable'
                END,
                regulation_quality_status = CASE
                    WHEN d.text_extracted IS NOT TRUE OR COALESCE(d.full_text, '') = '' THEN 'not_ready'
                    WHEN COALESCE(d.regulation, '') != '' THEN 'ok'
                    ELSE 'no_regulation'
                END,
                search_quality_notes = CONCAT_WS('; ',
                    CASE
                        WHEN d.text_extracted IS NOT TRUE OR COALESCE(d.full_text, '') = ''
                        THEN 'missing extracted text'
                    END,
                    CASE WHEN COALESCE(d.regulation, '') = '' THEN 'no regulation label' END
                )
        """))
        return await quality_summary(corpus=corpus)
    raise HTTPException(status_code=400, detail="corpus must be 'balca' or 'aao'")


@router.get("/api/quality/summary")
async def quality_summary(corpus: str = Query(default="balca")):
    if corpus == "balca":
        table = "decisions"
    elif corpus == "aao":
        table = "aao_decisions"
    else:
        raise HTTPException(status_code=400, detail="corpus must be 'balca' or 'aao'")
    citation_rows = await database.fetch_all(text(f"""
        SELECT COALESCE(citation_quality_status, 'unknown') AS status, COUNT(*) AS count
        FROM {table}
        GROUP BY COALESCE(citation_quality_status, 'unknown')
        ORDER BY count DESC
    """))
    regulation_rows = await database.fetch_all(text(f"""
        SELECT COALESCE(regulation_quality_status, 'unknown') AS status, COUNT(*) AS count
        FROM {table}
        GROUP BY COALESCE(regulation_quality_status, 'unknown')
        ORDER BY count DESC
    """))
    extraction_rows = await database.fetch_all(text(f"""
        SELECT COALESCE(extraction_status, 'unknown') AS status, COUNT(*) AS count
        FROM {table}
        GROUP BY COALESCE(extraction_status, 'unknown')
        ORDER BY count DESC
    """))
    return {
        "corpus": corpus,
        "citation_quality": [dict(row) for row in citation_rows],
        "regulation_quality": [dict(row) for row in regulation_rows],
        "extraction_quality": [dict(row) for row in extraction_rows],
    }


@router.get("/api/quality/issues")
async def quality_issues(
    corpus: str = Query(default="balca"),
    limit: int = Query(default=50, ge=1, le=500),
):
    if corpus == "balca":
        table = "decisions"
        label = "case_number"
    elif corpus == "aao":
        table = "aao_decisions"
        label = "COALESCE(title, filename)"
    else:
        raise HTTPException(status_code=400, detail="corpus must be 'balca' or 'aao'")
    rows = await database.fetch_all(text(f"""
        SELECT id, {label} AS label, extraction_status, citation_quality_status,
               regulation_quality_status, search_quality_notes
        FROM {table}
        WHERE COALESCE(extraction_status, 'unknown') NOT IN ('extracted', 'ignored')
           OR COALESCE(citation_quality_status, 'unknown') IN ('unknown', 'not_ready', 'needs_review')
           OR COALESCE(regulation_quality_status, 'unknown') IN ('unknown', 'not_ready')
        ORDER BY id
        LIMIT :limit
    """).bindparams(limit=limit))
    return {"corpus": corpus, "results": [dict(row) for row in rows]}


# ── Experience verification letter extraction (no AI) ────────────────────────

@router.post("/api/extract-experience-letter")
async def extract_experience_letter_endpoint(file: UploadFile = File(...)):
    """Parse an experience verification letter PDF using pdfplumber + regex."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="File must be a PDF")
    pdf_bytes = await file.read()
    try:
        result = extract_letter_from_bytes(pdf_bytes)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Extraction failed: {e}")
    return result


# ── INA — Immigration and Nationality Act ────────────────────────────────────

