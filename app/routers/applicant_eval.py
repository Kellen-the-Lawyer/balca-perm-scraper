"""
Applicant Evaluation Spreadsheet endpoints.

POST /api/applicant-eval/from-pwd  — upload a PWD (ETA-9141) PDF; returns an
    editable spreadsheet config (questions pre-filled from the parsed PWD).
POST /api/applicant-eval/generate  — config JSON in; .xlsx download out.

Stateless by design: nothing is written to the database.
"""
from __future__ import annotations

import os
import tempfile
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response

from applicant_eval import (config_from_pwd, default_threshold,
                            suggested_filename, workbook_bytes, MAX_SKILLS)
from perm_verify.evl_compare import extract_pwd_requirements

router = APIRouter()


@router.post("/api/applicant-eval/from-pwd")
async def applicant_eval_from_pwd(file: UploadFile = File(...)):
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Upload a PWD PDF (ETA-9141).")
    data = await file.read()
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    try:
        tmp.write(data)
        tmp.close()
        pwd, _atomic = extract_pwd_requirements(tmp.name)
        config = config_from_pwd(pwd)
        return {"config": config,
                "extraction_notes": (pwd.get("requirements") or {}).get(
                    "extraction_notes") or []}
    except HTTPException:
        raise
    except Exception as exc:  # parser failures surface as a clean 422
        raise HTTPException(status_code=422,
                            detail=f"Could not parse PWD: {exc}") from exc
    finally:
        os.unlink(tmp.name)


def _validate(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise HTTPException(status_code=400, detail="config must be an object")
    primary = config.get("primary") or {}
    if not (primary.get("education_question") or "").strip() or \
       not (primary.get("experience_question") or "").strip():
        raise HTTPException(status_code=400,
                            detail="Primary education and experience questions "
                                   "are required.")
    skills = [str(s).strip() for s in (config.get("special_skills") or [])
              if str(s).strip()]
    if len(skills) > MAX_SKILLS:
        raise HTTPException(status_code=400,
                            detail=f"At most {MAX_SKILLS} special skills.")
    config["special_skills"] = skills
    rule = config.get("highlight_rule") or {}
    if rule.get("enabled"):
        try:
            thr = int(rule.get("threshold", default_threshold(len(skills))))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="threshold must be an integer")
        if skills and not (1 <= thr <= len(skills)):
            raise HTTPException(status_code=400,
                                detail=f"threshold must be between 1 and {len(skills)}.")
        rule["threshold"] = thr
    config["highlight_rule"] = rule
    return config


@router.post("/api/applicant-eval/generate")
async def applicant_eval_generate(payload: dict):
    config = _validate(payload.get("config") or payload)
    rows = payload.get("rows") or 1000
    data = workbook_bytes(config, rows=rows)
    filename = suggested_filename(config)
    return Response(
        content=data,
        media_type=("application/vnd.openxmlformats-officedocument"
                    ".spreadsheetml.sheet"),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
