"""Visa Bulletin: latest, history, backlog, comparisons."""
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

router = APIRouter()

@router.get("/api/visa-bulletin/latest")
async def visa_bulletin_latest(
    category_type: Optional[str] = Query(None, description="employment or family"),
    date_type:     Optional[str] = Query(None, description="final_action or dates_for_filing"),
):
    """Most recent bulletin's priority dates."""
    clauses, params = ["bulletin_date = (SELECT MAX(bulletin_date) FROM visa_bulletin)"], {}
    if category_type:
        clauses.append("category_type = :category_type")
        params["category_type"] = category_type
    if date_type:
        clauses.append("date_type = :date_type")
        params["date_type"] = date_type
    where = "WHERE " + " AND ".join(clauses)
    rows = await database.fetch_all(text(f"""
        SELECT bulletin_date, bulletin_title, category_type, date_type,
               preference, chargeability, priority_date, is_current, is_unavailable, raw_value
        FROM visa_bulletin {where}
        ORDER BY category_type, date_type, preference, chargeability
    """).bindparams(**params))
    return [dict(r) for r in rows]


@router.get("/api/visa-bulletin/{year}/{month}")
async def visa_bulletin_month(
    year:          int,
    month:         int,
    category_type: Optional[str] = Query(None),
    date_type:     Optional[str] = Query(None),
):
    """Priority dates for a specific bulletin month."""
    try:
        bdate = _date(year, month, 1)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid year/month")
    clauses = ["bulletin_date = :bdate"]
    params: dict = {"bdate": bdate}
    if category_type:
        clauses.append("category_type = :category_type")
        params["category_type"] = category_type
    if date_type:
        clauses.append("date_type = :date_type")
        params["date_type"] = date_type
    where = "WHERE " + " AND ".join(clauses)
    rows = await database.fetch_all(text(f"""
        SELECT bulletin_date, bulletin_title, category_type, date_type,
               preference, chargeability, priority_date, is_current, is_unavailable, raw_value
        FROM visa_bulletin {where}
        ORDER BY category_type, date_type, preference, chargeability
    """).bindparams(**params))
    if not rows:
        raise HTTPException(status_code=404, detail=f"No bulletin found for {year}-{month:02d}")
    return [dict(r) for r in rows]


@router.get("/api/visa-bulletin/history")
async def visa_bulletin_history(
    preference:    str            = Query(..., description="e.g. EB2, EB3, F1"),
    chargeability: str            = Query(..., description="ALL, CHINA, INDIA, MEXICO, PHILIPPINES"),
    date_type:     Optional[str]  = Query("final_action", description="final_action or dates_for_filing"),
    category_type: Optional[str]  = Query(None),
    from_year:     Optional[int]  = Query(None),
    to_year:       Optional[int]  = Query(None),
):
    """
    Priority date history for a preference/chargeability combination over time.
    Useful for charting movement trends.
    """
    clauses = ["preference = :preference", "chargeability = :chargeability"]
    params: dict = {"preference": preference.upper(), "chargeability": chargeability.upper()}
    if date_type:
        clauses.append("date_type = :date_type")
        params["date_type"] = date_type
    if category_type:
        clauses.append("category_type = :category_type")
        params["category_type"] = category_type
    if from_year:
        clauses.append("bulletin_date >= :from_date")
        params["from_date"] = date(from_year, 1, 1)
    if to_year:
        clauses.append("bulletin_date <= :to_date")
        params["to_date"] = date(to_year, 12, 31)
    where = "WHERE " + " AND ".join(clauses)
    rows = await database.fetch_all(text(f"""
        SELECT bulletin_date, bulletin_title, preference, chargeability,
               date_type, category_type,
               priority_date, is_current, is_unavailable, raw_value
        FROM visa_bulletin {where}
        ORDER BY bulletin_date ASC
    """).bindparams(**params))
    if not rows:
        raise HTTPException(status_code=404, detail="No history found for given parameters")

    # Compute month-over-month movement in days
    result = []
    prev_pd = None
    for r in rows:
        d = dict(r)
        movement_days = None
        if d["priority_date"] and prev_pd:
            movement_days = (d["priority_date"] - prev_pd).days
        d["movement_days"] = movement_days
        prev_pd = d["priority_date"] if not d["is_current"] else prev_pd
        result.append(d)
    return result


@router.get("/api/visa-bulletin/backlog")
async def visa_bulletin_backlog(
    preference:    str           = Query(..., description="e.g. EB2, EB3"),
    chargeability: str           = Query(..., description="INDIA, CHINA, ALL etc."),
    date_type:     Optional[str] = Query("final_action"),
):
    """
    Current backlog estimate: how far back the current priority date is
    from today, and average monthly advancement over the past 12 months.
    """
    params = {
        "preference":    preference.upper(),
        "chargeability": chargeability.upper(),
        "date_type":     date_type or "final_action",
    }

    # Latest entry
    current = await database.fetch_one(text("""
        SELECT bulletin_date, priority_date, is_current, is_unavailable, raw_value
        FROM visa_bulletin
        WHERE preference = :preference
          AND chargeability = :chargeability
          AND date_type = :date_type
        ORDER BY bulletin_date DESC LIMIT 1
    """).bindparams(**params))

    if not current:
        raise HTTPException(status_code=404, detail="No data found")

    # Last 13 months for advancement calc
    history = await database.fetch_all(text("""
        SELECT bulletin_date, priority_date, is_current, is_unavailable
        FROM visa_bulletin
        WHERE preference = :preference
          AND chargeability = :chargeability
          AND date_type = :date_type
          AND priority_date IS NOT NULL
          AND is_current = FALSE
        ORDER BY bulletin_date DESC LIMIT 13
    """).bindparams(**params))

    avg_monthly_days = None
    if len(history) >= 2:
        movements = []
        for i in range(len(history) - 1):
            delta = (history[i]["priority_date"] - history[i+1]["priority_date"]).days
            movements.append(delta)
        avg_monthly_days = sum(movements) / len(movements) if movements else None

    backlog_days = None
    years_to_wait = None
    if current["priority_date"]:
        backlog_days = (_date.today() - current["priority_date"]).days
        if avg_monthly_days and avg_monthly_days > 0:
            months_to_wait = backlog_days / avg_monthly_days
            years_to_wait  = round(months_to_wait / 12, 1)

    return {
        "preference":         preference.upper(),
        "chargeability":      chargeability.upper(),
        "date_type":          date_type,
        "latest_bulletin":    current["bulletin_date"],
        "current_cut_off":    current["priority_date"],
        "is_current":         current["is_current"],
        "is_unavailable":     current["is_unavailable"],
        "raw_value":          current["raw_value"],
        "backlog_days":       backlog_days,
        "backlog_years":      round(backlog_days / 365.25, 1) if backlog_days else None,
        "avg_monthly_advance_days": round(avg_monthly_days, 1) if avg_monthly_days else None,
        "est_years_to_current":     years_to_wait,
    }


@router.get("/api/visa-bulletin/compare")
async def visa_bulletin_compare(
    preference:    str            = Query(..., description="e.g. EB3"),
    date_type:     Optional[str]  = Query("final_action"),
    bulletin_date: Optional[str]  = Query(None, description="YYYY-MM-DD, defaults to latest"),
):
    """
    Compare all chargeability countries for a given preference in one bulletin.
    """
    if bulletin_date:
        bdate = bulletin_date
    else:
        row = await database.fetch_one(
            text("SELECT MAX(bulletin_date) AS d FROM visa_bulletin"))
        bdate = row["d"]

    rows = await database.fetch_all(text("""
        SELECT bulletin_date, bulletin_title, preference, chargeability,
               date_type, category_type,
               priority_date, is_current, is_unavailable, raw_value
        FROM visa_bulletin
        WHERE preference    = :preference
          AND date_type     = :date_type
          AND bulletin_date = :bdate
        ORDER BY chargeability
    """), {
        "preference": preference.upper(),
        "date_type":  date_type or "final_action",
        "bdate":      bdate,
    })
    if not rows:
        raise HTTPException(status_code=404, detail="No data found")
    return [dict(r) for r in rows]


@router.get("/api/visa-bulletin/index")
async def visa_bulletin_index():
    """List all available bulletin months in the DB."""
    rows = await database.fetch_all(text("""
        SELECT bulletin_date, bulletin_title,
               COUNT(*) AS total_rows,
               COUNT(DISTINCT preference) AS preferences,
               COUNT(DISTINCT date_type) AS date_types
        FROM visa_bulletin
        GROUP BY bulletin_date, bulletin_title
        ORDER BY bulletin_date DESC
    """))
    return [dict(r) for r in rows]


@router.get("/api/visa-bulletin/stats")
async def visa_bulletin_stats():
    """Coverage summary for the visa bulletin table."""
    rows = await database.fetch_all(text("""
        SELECT category_type, date_type,
               COUNT(DISTINCT bulletin_date) AS bulletins,
               COUNT(DISTINCT preference)    AS preferences,
               MIN(bulletin_date)            AS earliest,
               MAX(bulletin_date)            AS latest,
               COUNT(*)                      AS total_rows
        FROM visa_bulletin
        GROUP BY category_type, date_type
        ORDER BY category_type, date_type
    """))
    return [dict(r) for r in rows]
# ══════════════════════════════════════════════════════════════════════════════
# OFLC Query Engine — append to api.py
# Supports pivot table mode and raw record mode with dynamic filters
# ══════════════════════════════════════════════════════════════════════════════

OFLC_TABLES = {
    "oflc_perm": {
        "text_cols": {
            "case_number","case_status","fiscal_year","source_file","occupation_type",
            "employer_name","employer_state","employer_city","employer_postal_code",
            "employer_fein","employer_naics","atty_law_firm","atty_last_name",
            "atty_first_name","atty_state","job_title","soc_code","soc_title",
            "wage_per","worksite_city","worksite_state","worksite_postal_code",
            "worksite_bls_area","pwd_number","fw_currently_employed",
            "is_multiple_locations","employer_layoff",
        },
        "numeric_cols": {"wage_from","wage_to","employer_num_payroll","employer_year_commenced"},
        "date_cols":    {"received_date","decision_date","ingested_at"},
    },
    "oflc_lca": {
        "text_cols": {
            "case_number","case_status","fiscal_year","visa_class","source_file",
            "employer_name","employer_state","employer_city","employer_postal_code",
            "employer_fein","naics_code","law_firm_name","agent_last_name",
            "agent_first_name","agent_state","job_title","soc_code","soc_title",
            "full_time_position","wage_unit","pw_unit","pw_wage_level","pw_oes_year",
            "worksite_city","worksite_state","worksite_postal_code",
            "h1b_dependent","willful_violator",
        },
        "numeric_cols": {"wage_from","wage_to","prevailing_wage","total_worker_positions"},
        "date_cols":    {"received_date","decision_date","begin_date","end_date","ingested_at"},
    },
    "oflc_pw": {
        "text_cols": {
            "case_number","case_status","fiscal_year","visa_class","source_file",
            "employer_name","employer_state","employer_city","employer_postal_code",
            "employer_fein","naics_code","law_firm_name","agent_last_name",
            "agent_first_name","job_title","soc_code","soc_title",
            "suggested_soc_code","suggested_soc_title",
            "pwd_soc_code","pwd_soc_title",
            "emp_soc_codes","emp_soc_titles",
            "o_net_code","o_net_title",
            "pwd_unit","pw_wage_level","wage_source","wage_source_requested",
            "survey_name","bls_area",
            "alt_pwd_unit","alt_pwd_wage_level","alt_pwd_wage_source",
            "worksite_city","worksite_state","worksite_postal_code",
        },
        "numeric_cols": {"pwd_wage_rate", "alt_pwd_wage_rate"},
        "date_cols":    {"received_date","determination_date","pwd_wage_expiration_date","ingested_at"},
    },
}

