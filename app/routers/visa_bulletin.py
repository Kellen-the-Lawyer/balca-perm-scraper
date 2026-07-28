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

# ── Effective-bulletin gating ────────────────────────────────────────────────
# DOS publishes each bulletin roughly two weeks before the month it governs, so
# the newest row in visa_bulletin is routinely NOT the bulletin currently in
# force. Anything that means "right now" must gate on the first of the current
# month. A future-dated bulletin then activates on its own the day its month
# begins — no code change, no redeploy, no manual flip.
IN_EFFECT_ON = "date_trunc('month', CURRENT_DATE)"
EFFECTIVE_BULLETIN = (
    f"(SELECT MAX(bulletin_date) FROM visa_bulletin "
    f"WHERE bulletin_date <= {IN_EFFECT_ON})"
)


@router.get("/api/visa-bulletin/latest")
async def visa_bulletin_latest(
    category_type: Optional[str] = Query(None, description="employment or family"),
    date_type:     Optional[str] = Query(None, description="final_action or dates_for_filing"),
):
    """Priority dates from the bulletin currently in force (not merely the
    most recently published one — see EFFECTIVE_BULLETIN)."""
    clauses, params = [f"bulletin_date = {EFFECTIVE_BULLETIN}"], {}
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


def _theil_sen_slope(pairs):
    """Median of pairwise slopes for (bulletin_date, priority_date) pairs.

    Returns PD-days advanced per calendar day. Robust to ~29% anomalous
    bulletins (retrogressions, data errors), so a single bulletin cannot
    materially move the estimate. O(n^2) pairs; n <= 61 -> <= 1,830 slopes.
    """
    slopes = []
    n = len(pairs)
    for i in range(n):
        for j in range(i + 1, n):
            dx = (pairs[j][0] - pairs[i][0]).days
            if dx == 0:
                continue
            slopes.append((pairs[j][1] - pairs[i][1]).days / dx)
    if not slopes:
        return None
    slopes.sort()
    m = len(slopes)
    return slopes[m // 2] if m % 2 else (slopes[m // 2 - 1] + slopes[m // 2]) / 2


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

    # Cut-off currently in force. Must exclude bulletins published for a future
    # month, or the backlog would be measured against a cut-off that has not
    # taken effect yet.
    current = await database.fetch_one(text(f"""
        SELECT bulletin_date, priority_date, is_current, is_unavailable, raw_value
        FROM visa_bulletin
        WHERE preference = :preference
          AND chargeability = :chargeability
          AND date_type = :date_type
          AND bulletin_date <= {IN_EFFECT_ON}
        ORDER BY bulletin_date DESC LIMIT 1
    """).bindparams(**params))

    if not current:
        raise HTTPException(status_code=404, detail="No data found")

    # Up to 61 months of history for robust (Theil-Sen) slope estimation.
    # Excludes Current and Unavailable rows (priority_date IS NULL for both).
    history = await database.fetch_all(text(f"""
        SELECT bulletin_date, priority_date
        FROM visa_bulletin
        WHERE preference = :preference
          AND chargeability = :chargeability
          AND date_type = :date_type
          AND priority_date IS NOT NULL
          AND is_current = FALSE
          AND bulletin_date <= {IN_EFFECT_ON}
        ORDER BY bulletin_date DESC LIMIT 61
    """).bindparams(**params))
    hist = [(r["bulletin_date"], r["priority_date"]) for r in reversed(history)]

    # Cut-off fallback: if the latest bulletin is Current/Unavailable, measure
    # backlog from the most recent bulletin that published a cut-off date.
    effective_cut_off = current["priority_date"]
    cut_off_as_of     = current["bulletin_date"]
    if effective_cut_off is None and hist:
        cut_off_as_of, effective_cut_off = hist[-1]

    backlog_days = None
    if effective_cut_off is not None and not current["is_current"]:
        backlog_days = (_date.today() - effective_cut_off).days

    # Naive 12-month pace (legacy, calendar-day aware): net movement over the
    # actual calendar span of the trailing 13 published bulletins.
    avg_monthly_days = None
    w = hist[-13:]
    if len(w) >= 2:
        span_days = (w[-1][0] - w[0][0]).days
        if span_days > 0:
            avg_monthly_days = (w[-1][1] - w[0][1]).days / span_days * 30.44

    methods = {}
    est_values = []
    for label, months in (("theil_sen_36mo", 36), ("theil_sen_60mo", 60)):
        window = hist[-(months + 1):]
        slope = _theil_sen_slope(window)          # PD-days per calendar-day
        est = None
        retrogressing = slope is not None and slope <= 0
        if slope and slope > 0 and backlog_days is not None:
            est = round(backlog_days / slope / 365.25, 1)
            est_values.append(est)
        methods[label] = {
            "slope_days_per_month": round(slope * 30.44, 1) if slope is not None else None,
            "est_years":            est,
            "retrogressing":        retrogressing,
            "bulletins_in_window":  len(window),
        }

    headline = methods["theil_sen_36mo"]["est_years"]

    return {
        "preference":         preference.upper(),
        "chargeability":      chargeability.upper(),
        "date_type":          date_type,
        "latest_bulletin":    current["bulletin_date"],
        "current_cut_off":    effective_cut_off,
        "cut_off_as_of":      cut_off_as_of,
        "latest_is_stale":    current["priority_date"] is None and effective_cut_off is not None,
        "is_current":         current["is_current"],
        "is_unavailable":     current["is_unavailable"],
        "raw_value":          current["raw_value"],
        "backlog_days":       backlog_days,
        "backlog_years":      round(backlog_days / 365.25, 1) if backlog_days is not None else None,
        "avg_monthly_advance_days": round(avg_monthly_days, 1) if avg_monthly_days is not None else None,
        "methods":            methods,
        "est_years_to_current": headline,
        "est_years_low":      min(est_values) if est_values else None,
        "est_years_high":     max(est_values) if est_values else None,
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
            text(f"SELECT {EFFECTIVE_BULLETIN} AS d"))
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
    rows = await database.fetch_all(text(f"""
        SELECT bulletin_date, bulletin_title,
               COUNT(*) AS total_rows,
               COUNT(DISTINCT preference) AS preferences,
               COUNT(DISTINCT date_type) AS date_types,
               (bulletin_date <= {IN_EFFECT_ON})        AS in_effect,
               (bulletin_date = {EFFECTIVE_BULLETIN})   AS is_current_bulletin
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
