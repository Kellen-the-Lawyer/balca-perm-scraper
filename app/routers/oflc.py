"""OFLC disclosure data: PERM, LCA, PW, employers, and the query builder."""
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

def _oflc_where(clauses, params, col, val, op="="):
    """Append a filter clause and bind its param."""
    if val is None:
        return
    key = col.replace(".", "_").replace(" ", "_")
    if op == "ilike":
        clauses.append(f"{col} ILIKE :{key}")
        params[key] = f"%{val}%"
    else:
        clauses.append(f"{col} {op} :{key}")
        params[key] = val


# ── PERM ──────────────────────────────────────────────────────────────────────

@router.get("/api/oflc/perm")
async def oflc_perm(
    case_number:    Optional[str]   = Query(None),
    case_status:    Optional[str]   = Query(None, description="Certified, Denied, Withdrawn…"),
    employer_name:  Optional[str]   = Query(None, description="Partial match"),
    employer_fein:  Optional[str]   = Query(None),
    employer_state: Optional[str]   = Query(None, description="2-letter state code"),
    atty_law_firm:  Optional[str]   = Query(None, description="Partial match"),
    soc_code:       Optional[str]   = Query(None, description="e.g. 15-1252"),
    naics:          Optional[str]   = Query(None, description="NAICS prefix"),
    fiscal_year:    Optional[str]   = Query(None, description="e.g. FY2024"),
    decision_from:  Optional[str]   = Query(None, description="YYYY-MM-DD"),
    decision_to:    Optional[str]   = Query(None, description="YYYY-MM-DD"),
    wage_min:       Optional[float] = Query(None),
    limit:          int = Query(50, le=500),
    offset:         int = Query(0),
):
    clauses, params = [], {}
    _oflc_where(clauses, params, "case_number",    case_number)
    _oflc_where(clauses, params, "case_status",    case_status)
    _oflc_where(clauses, params, "employer_name",  employer_name,  "ilike")
    _oflc_where(clauses, params, "employer_fein",  employer_fein)
    _oflc_where(clauses, params, "employer_state", employer_state)
    _oflc_where(clauses, params, "atty_law_firm",  atty_law_firm,  "ilike")
    _oflc_where(clauses, params, "soc_code",       soc_code)
    _oflc_where(clauses, params, "fiscal_year",    fiscal_year)
    if naics:
        clauses.append("employer_naics LIKE :naics")
        params["naics"] = f"{naics}%"
    if decision_from:
        clauses.append("decision_date >= :decision_from")
        params["decision_from"] = decision_from
    if decision_to:
        clauses.append("decision_date <= :decision_to")
        params["decision_to"] = decision_to
    if wage_min is not None:
        clauses.append("wage_from >= :wage_min")
        params["wage_min"] = wage_min
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.update({"limit": limit, "offset": offset})
    sql = f"""
        SELECT case_number, case_status, fiscal_year,
               received_date, decision_date, occupation_type,
               employer_name, employer_state, employer_city, employer_fein,
               employer_naics, atty_law_firm,
               job_title, soc_code, soc_title,
               wage_from, wage_to, wage_per,
               worksite_city, worksite_state
        FROM oflc_perm {where}
        ORDER BY decision_date DESC NULLS LAST
        LIMIT :limit OFFSET :offset
    """
    rows = await database.fetch_all(text(sql).bindparams(**params))
    return [dict(r) for r in rows]

@router.get("/api/oflc/perm/{case_number}")
async def oflc_perm_detail(case_number: str):
    rows = await database.fetch_all(
        text("SELECT * FROM oflc_perm WHERE case_number = :cn ORDER BY fiscal_year DESC").bindparams(cn=case_number)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Case not found")
    return [dict(r) for r in rows]


@router.get("/api/oflc/perm/stats/summary")
async def oflc_perm_stats(
    fiscal_year:    Optional[str] = Query(None),
    employer_state: Optional[str] = Query(None),
    soc_code:       Optional[str] = Query(None),
):
    clauses, params = [], {}
    _oflc_where(clauses, params, "fiscal_year",    fiscal_year)
    _oflc_where(clauses, params, "employer_state", employer_state)
    _oflc_where(clauses, params, "soc_code",       soc_code)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
        SELECT fiscal_year, case_status,
               COUNT(*)                                              AS total,
               AVG(wage_from)                                        AS avg_wage_from,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY wage_from) AS median_wage,
               COUNT(DISTINCT employer_fein)                         AS unique_employers,
               COUNT(DISTINCT atty_law_firm)                         AS unique_firms,
               COUNT(DISTINCT soc_code)                              AS unique_soc_codes
        FROM oflc_perm {where}
        GROUP BY fiscal_year, case_status
        ORDER BY fiscal_year DESC, total DESC
    """
    rows = await database.fetch_all(text(sql).bindparams(**params))
    return [dict(r) for r in rows]


# ── LCA ───────────────────────────────────────────────────────────────────────

@router.get("/api/oflc/lca")
async def oflc_lca(
    case_number:    Optional[str]   = Query(None),
    case_status:    Optional[str]   = Query(None),
    visa_class:     Optional[str]   = Query(None, description="H-1B, H-1B1, E-3"),
    employer_name:  Optional[str]   = Query(None, description="Partial match"),
    employer_fein:  Optional[str]   = Query(None),
    employer_state: Optional[str]   = Query(None),
    law_firm_name:  Optional[str]   = Query(None, description="Partial match"),
    soc_code:       Optional[str]   = Query(None),
    naics:          Optional[str]   = Query(None),
    fiscal_year:    Optional[str]   = Query(None),
    pw_wage_level:  Optional[str]   = Query(None, description="I, II, III, IV"),
    h1b_dependent:  Optional[str]   = Query(None, description="Y or N"),
    decision_from:  Optional[str]   = Query(None),
    decision_to:    Optional[str]   = Query(None),
    wage_min:       Optional[float] = Query(None),
    limit:          int = Query(50, le=500),
    offset:         int = Query(0),
):
    clauses, params = [], {}
    _oflc_where(clauses, params, "case_number",    case_number)
    _oflc_where(clauses, params, "case_status",    case_status)
    _oflc_where(clauses, params, "visa_class",     visa_class)
    _oflc_where(clauses, params, "employer_name",  employer_name,  "ilike")
    _oflc_where(clauses, params, "employer_fein",  employer_fein)
    _oflc_where(clauses, params, "employer_state", employer_state)
    _oflc_where(clauses, params, "law_firm_name",  law_firm_name,  "ilike")
    _oflc_where(clauses, params, "soc_code",       soc_code)
    _oflc_where(clauses, params, "fiscal_year",    fiscal_year)
    _oflc_where(clauses, params, "pw_wage_level",  pw_wage_level)
    _oflc_where(clauses, params, "h1b_dependent",  h1b_dependent)
    if naics:
        clauses.append("naics_code LIKE :naics")
        params["naics"] = f"{naics}%"
    if decision_from:
        clauses.append("decision_date >= :decision_from")
        params["decision_from"] = decision_from
    if decision_to:
        clauses.append("decision_date <= :decision_to")
        params["decision_to"] = decision_to
    if wage_min is not None:
        clauses.append("wage_from >= :wage_min")
        params["wage_min"] = wage_min
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.update({"limit": limit, "offset": offset})
    sql = f"""
        SELECT case_number, case_status, visa_class, fiscal_year,
               received_date, decision_date, begin_date, end_date,
               employer_name, employer_state, employer_city, employer_fein,
               naics_code, law_firm_name,
               job_title, soc_code, soc_title,
               wage_from, wage_to, wage_unit,
               prevailing_wage, pw_unit, pw_wage_level,
               worksite_city, worksite_state,
               h1b_dependent, willful_violator, total_worker_positions
        FROM oflc_lca {where}
        ORDER BY decision_date DESC NULLS LAST
        LIMIT :limit OFFSET :offset
    """
    rows = await database.fetch_all(text(sql).bindparams(**params))
    return [dict(r) for r in rows]

@router.get("/api/oflc/lca/{case_number}")
async def oflc_lca_detail(case_number: str):
    rows = await database.fetch_all(
        text("SELECT * FROM oflc_lca WHERE case_number = :cn ORDER BY fiscal_year DESC").bindparams(cn=case_number)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Case not found")
    return [dict(r) for r in rows]


@router.get("/api/oflc/lca/stats/summary")
async def oflc_lca_stats(
    fiscal_year:    Optional[str] = Query(None),
    visa_class:     Optional[str] = Query(None),
    employer_state: Optional[str] = Query(None),
    pw_wage_level:  Optional[str] = Query(None),
):
    clauses, params = [], {}
    _oflc_where(clauses, params, "fiscal_year",    fiscal_year)
    _oflc_where(clauses, params, "visa_class",     visa_class)
    _oflc_where(clauses, params, "employer_state", employer_state)
    _oflc_where(clauses, params, "pw_wage_level",  pw_wage_level)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
        SELECT fiscal_year, visa_class, case_status, pw_wage_level,
               COUNT(*)                                              AS total,
               SUM(total_worker_positions)                           AS total_positions,
               AVG(wage_from)                                        AS avg_wage,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY wage_from) AS median_wage,
               AVG(prevailing_wage)                                  AS avg_prevailing_wage,
               COUNT(DISTINCT employer_fein)                         AS unique_employers,
               COUNT(DISTINCT soc_code)                              AS unique_soc_codes
        FROM oflc_lca {where}
        GROUP BY fiscal_year, visa_class, case_status, pw_wage_level
        ORDER BY fiscal_year DESC, total DESC
    """
    rows = await database.fetch_all(text(sql).bindparams(**params))
    return [dict(r) for r in rows]


# ── PW ────────────────────────────────────────────────────────────────────────

@router.get("/api/oflc/pw")
async def oflc_pw(
    case_number:       Optional[str]   = Query(None),
    case_status:       Optional[str]   = Query(None),
    visa_class:        Optional[str]   = Query(None),
    employer_name:     Optional[str]   = Query(None, description="Partial match"),
    employer_fein:     Optional[str]   = Query(None),
    employer_state:    Optional[str]   = Query(None),
    law_firm_name:     Optional[str]   = Query(None, description="Partial match"),
    soc_code:          Optional[str]   = Query(None),
    naics:             Optional[str]   = Query(None),
    fiscal_year:       Optional[str]   = Query(None),
    pw_wage_level:     Optional[str]   = Query(None),
    bls_area:          Optional[str]   = Query(None, description="Partial match"),
    wage_source:       Optional[str]   = Query(None),
    determination_from: Optional[str]  = Query(None),
    determination_to:   Optional[str]  = Query(None),
    limit:             int = Query(50, le=500),
    offset:            int = Query(0),
):
    clauses, params = [], {}
    _oflc_where(clauses, params, "case_number",    case_number)
    _oflc_where(clauses, params, "case_status",    case_status)
    _oflc_where(clauses, params, "visa_class",     visa_class)
    _oflc_where(clauses, params, "employer_name",  employer_name,  "ilike")
    _oflc_where(clauses, params, "employer_fein",  employer_fein)
    _oflc_where(clauses, params, "employer_state", employer_state)
    _oflc_where(clauses, params, "law_firm_name",  law_firm_name,  "ilike")
    _oflc_where(clauses, params, "soc_code",       soc_code)
    _oflc_where(clauses, params, "fiscal_year",    fiscal_year)
    _oflc_where(clauses, params, "pw_wage_level",  pw_wage_level)
    _oflc_where(clauses, params, "bls_area",       bls_area,       "ilike")
    _oflc_where(clauses, params, "wage_source",    wage_source)
    if naics:
        clauses.append("naics_code LIKE :naics")
        params["naics"] = f"{naics}%"
    if determination_from:
        clauses.append("determination_date >= :determination_from")
        params["determination_from"] = determination_from
    if determination_to:
        clauses.append("determination_date <= :determination_to")
        params["determination_to"] = determination_to
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.update({"limit": limit, "offset": offset})
    sql = f"""
        SELECT case_number, case_status, visa_class, fiscal_year,
               received_date, determination_date,
               employer_name, employer_state, employer_city, employer_fein,
               naics_code, law_firm_name,
               job_title, soc_code, soc_title,
               pwd_wage_rate, pwd_unit, pw_wage_level,
               wage_source, bls_area, pwd_wage_expiration_date,
               worksite_city, worksite_state
        FROM oflc_pw {where}
        ORDER BY determination_date DESC NULLS LAST
        LIMIT :limit OFFSET :offset
    """
    rows = await database.fetch_all(text(sql).bindparams(**params))
    return [dict(r) for r in rows]

@router.get("/api/oflc/pw/{case_number}")
async def oflc_pw_detail(case_number: str):
    rows = await database.fetch_all(
        text("SELECT * FROM oflc_pw WHERE case_number = :cn ORDER BY fiscal_year DESC").bindparams(cn=case_number)
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Case not found")
    return [dict(r) for r in rows]


@router.get("/api/oflc/pw/stats/summary")
async def oflc_pw_stats(
    fiscal_year:    Optional[str] = Query(None),
    visa_class:     Optional[str] = Query(None),
    employer_state: Optional[str] = Query(None),
    pw_wage_level:  Optional[str] = Query(None),
):
    clauses, params = [], {}
    _oflc_where(clauses, params, "fiscal_year",    fiscal_year)
    _oflc_where(clauses, params, "visa_class",     visa_class)
    _oflc_where(clauses, params, "employer_state", employer_state)
    _oflc_where(clauses, params, "pw_wage_level",  pw_wage_level)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"""
        SELECT fiscal_year, visa_class, case_status, pw_wage_level, wage_source,
               COUNT(*)                                                   AS total,
               AVG(pwd_wage_rate)                                         AS avg_pwd_wage,
               PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY pwd_wage_rate) AS median_pwd_wage,
               COUNT(DISTINCT employer_fein)                              AS unique_employers,
               COUNT(DISTINCT soc_code)                                   AS unique_soc_codes,
               COUNT(DISTINCT bls_area)                                   AS unique_bls_areas
        FROM oflc_pw {where}
        GROUP BY fiscal_year, visa_class, case_status, pw_wage_level, wage_source
        ORDER BY fiscal_year DESC, total DESC
    """
    rows = await database.fetch_all(text(sql).bindparams(**params))
    return [dict(r) for r in rows]


# ── Cross-program employer lookup ─────────────────────────────────────────────

@router.get("/api/oflc/employer/{fein}")
async def oflc_employer(fein: str):
    """Cross-program lookup by FEIN — PERM, LCA, and PW activity."""
    p = {"fein": fein}
    perm_rows = await database.fetch_all(text("""
        SELECT 'perm' AS program, case_number, case_status, fiscal_year,
               decision_date AS date, job_title, soc_code,
               wage_from AS wage, wage_per AS wage_unit,
               worksite_state, atty_law_firm AS firm
        FROM oflc_perm WHERE employer_fein = :fein
        ORDER BY decision_date DESC NULLS LAST LIMIT 100
    """).bindparams(**p))
    lca_rows = await database.fetch_all(text("""
        SELECT 'lca' AS program, case_number, case_status, fiscal_year,
               decision_date AS date, job_title, soc_code,
               wage_from AS wage, wage_unit,
               worksite_state, law_firm_name AS firm
        FROM oflc_lca WHERE employer_fein = :fein
        ORDER BY decision_date DESC NULLS LAST LIMIT 100
    """).bindparams(**p))
    pw_rows = await database.fetch_all(text("""
        SELECT 'pw' AS program, case_number, case_status, fiscal_year,
               determination_date AS date, job_title, soc_code,
               pwd_wage_rate AS wage, pwd_unit AS wage_unit,
               worksite_state, law_firm_name AS firm
        FROM oflc_pw WHERE employer_fein = :fein
        ORDER BY determination_date DESC NULLS LAST LIMIT 100
    """).bindparams(**p))
    if not perm_rows and not lca_rows and not pw_rows:
        raise HTTPException(status_code=404, detail="No records found for FEIN")
    name_row = await database.fetch_one(text("""
        SELECT employer_name FROM (
            SELECT employer_name FROM oflc_perm WHERE employer_fein = :fein AND employer_name IS NOT NULL
            UNION ALL
            SELECT employer_name FROM oflc_lca  WHERE employer_fein = :fein AND employer_name IS NOT NULL
            UNION ALL
            SELECT employer_name FROM oflc_pw   WHERE employer_fein = :fein AND employer_name IS NOT NULL
        ) t LIMIT 1
    """).bindparams(**p))
    return {
        "fein":          fein,
        "employer_name": name_row["employer_name"] if name_row else None,
        "summary":       {"perm_total": len(perm_rows), "lca_total": len(lca_rows), "pw_total": len(pw_rows)},
        "perm":          [dict(r) for r in perm_rows],
        "lca":           [dict(r) for r in lca_rows],
        "pw":            [dict(r) for r in pw_rows],
    }


# ── Cross-program firm lookup ─────────────────────────────────────────────────

@router.get("/api/oflc/firm")
async def oflc_firm(
    name:        str           = Query(..., description="Law firm name — partial match"),
    fiscal_year: Optional[str] = Query(None),
    program:     Optional[str] = Query(None, description="perm, lca, or pw"),
):
    params = {"name": f"%{name}%"}
    fy_clause = "AND fiscal_year = :fy" if fiscal_year else ""
    if fiscal_year:
        params["fy"] = fiscal_year
    results = {}
    if program in (None, "perm"):
        results["perm"] = [dict(r) for r in await database.fetch_all(text(f"""
            SELECT fiscal_year, case_status, COUNT(*) AS total, AVG(wage_from) AS avg_wage
            FROM oflc_perm WHERE atty_law_firm ILIKE :name {fy_clause}
            GROUP BY fiscal_year, case_status ORDER BY fiscal_year DESC
        """).bindparams(**params))]
    if program in (None, "lca"):
        results["lca"] = [dict(r) for r in await database.fetch_all(text(f"""
            SELECT fiscal_year, visa_class, case_status,
                   COUNT(*) AS total, SUM(total_worker_positions) AS total_positions,
                   AVG(wage_from) AS avg_wage
            FROM oflc_lca WHERE law_firm_name ILIKE :name {fy_clause}
            GROUP BY fiscal_year, visa_class, case_status ORDER BY fiscal_year DESC
        """).bindparams(**params))]
    if program in (None, "pw"):
        results["pw"] = [dict(r) for r in await database.fetch_all(text(f"""
            SELECT fiscal_year, visa_class, case_status,
                   COUNT(*) AS total, AVG(pwd_wage_rate) AS avg_pwd_wage
            FROM oflc_pw WHERE law_firm_name ILIKE :name {fy_clause}
            GROUP BY fiscal_year, visa_class, case_status ORDER BY fiscal_year DESC
        """).bindparams(**params))]
    return results


# ── Overall OFLC stats ────────────────────────────────────────────────────────

@router.get("/api/oflc/stats")
async def oflc_stats():
    """Row counts and coverage for all three OFLC tables."""
    rows = await database.fetch_all(text("""
        SELECT 'perm' AS program, COUNT(*) AS total_rows,
               COUNT(DISTINCT employer_fein) AS unique_employers,
               MIN(fiscal_year) AS earliest_fy, MAX(fiscal_year) AS latest_fy,
               COUNT(DISTINCT atty_law_firm) AS unique_firms
        FROM oflc_perm
        UNION ALL
        SELECT 'lca', COUNT(*), COUNT(DISTINCT employer_fein),
               MIN(fiscal_year), MAX(fiscal_year), COUNT(DISTINCT law_firm_name)
        FROM oflc_lca
        UNION ALL
        SELECT 'pw', COUNT(*), COUNT(DISTINCT employer_fein),
               MIN(fiscal_year), MAX(fiscal_year), COUNT(DISTINCT law_firm_name)
        FROM oflc_pw
    """))
    return [dict(r) for r in rows]


# ══════════════════════════════════════════════════════════════════════════════
# Visa Bulletin Endpoints
# ══════════════════════════════════════════════════════════════════════════════



def _safe_col(table: str, col: str) -> str:
    if table not in OFLC_TABLES:
        raise ValueError(f"Unknown table: {table}")
    cfg = OFLC_TABLES[table]
    all_cols = cfg["text_cols"] | cfg["numeric_cols"] | cfg["date_cols"] | {"id"}
    if col not in all_cols:
        raise ValueError(f"Unknown column '{col}' for table '{table}'")
    return f'"{col}"'


def _build_agg_expr(agg: str, field: str | None, table: str) -> str:
    if agg == "count":
        return "COUNT(*)"
    if agg == "pct_of_total":
        return "ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2)"
    if not field:
        if agg == "count_distinct":
            return "COUNT(*)"  # fallback: no field selected yet
        raise ValueError(f"Aggregation '{agg}' requires a field")
    col = _safe_col(table, field)
    if agg == "count_distinct": return f"COUNT(DISTINCT {col})"
    if agg == "sum":            return f"SUM({col})"
    if agg == "avg":            return f"ROUND(AVG({col})::numeric, 2)"
    if agg == "min":            return f"MIN({col})"
    if agg == "max":            return f"MAX({col})"
    raise ValueError(f"Unknown aggregation: {agg}")


def _build_where(table: str, filter_params: list) -> tuple:
    clauses, params = [], {}
    for i, f in enumerate(filter_params):
        field, op, val = f.get("field"), f.get("op"), f.get("val", "")
        if not field: continue
        col = _safe_col(table, field)
        key = f"fv_{i}"
        if op == "IS NULL":      clauses.append(f"{col} IS NULL")
        elif op == "IS NOT NULL": clauses.append(f"{col} IS NOT NULL")
        elif op == "ILIKE":      clauses.append(f"{col} ILIKE :{key}"); params[key] = f"%{val}%"
        elif op == "NOT ILIKE":  clauses.append(f"{col} NOT ILIKE :{key}"); params[key] = f"%{val}%"
        elif op in ("=","!=",">",">=","<","<="):
            clauses.append(f"{col} {op} :{key}"); params[key] = val
        else:
            raise ValueError(f"Unknown operator: {op}")
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params

@router.get("/api/oflc/query")
async def oflc_query(request: Request):
    from urllib.parse import parse_qs
    p = request.query_params
    raw_qs = str(request.url).split("?", 1)[1] if "?" in str(request.url) else ""
    parsed_qs = parse_qs(raw_qs)

    table  = p.get("table", "oflc_perm")
    mode   = p.get("mode", "pivot")
    limit  = min(int(p.get("limit", 500)), 5000)

    if table not in OFLC_TABLES:
        raise HTTPException(status_code=400, detail=f"Unknown table: {table}")

    # Parse filters
    filter_list, i = [], 0
    while f"f_field_{i}" in p:
        filter_list.append({"field": p[f"f_field_{i}"], "op": p[f"f_op_{i}"], "val": p.get(f"f_val_{i}", "")})
        i += 1

    try:
        where, params = _build_where(table, filter_list)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # ── Raw mode ──────────────────────────────────────────────────────────────
    if mode == "raw":
        q = f"SELECT * FROM {table} {where} ORDER BY id LIMIT :limit"
        params["limit"] = limit
        try:
            rows = await database.fetch_all(text(q).bindparams(**params))
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
        count_q = f"SELECT COUNT(*) as cnt FROM {table} {where}"
        nlp = {k: v for k, v in params.items() if k != "limit"}
        total_row = await database.fetch_one(text(count_q).bindparams(**nlp) if nlp else text(count_q))
        columns = list(rows[0].keys()) if rows else []
        return {"mode": "raw", "columns": columns, "rows": [dict(r) for r in rows],
                "total_rows": total_row["cnt"] if total_row else 0, "limited": (total_row["cnt"] if total_row else 0) > limit}

    # ── Pivot mode ────────────────────────────────────────────────────────────
    row_fields = parsed_qs.get("rows", [])
    col_field  = parsed_qs.get("cols", [None])[0]
    if not row_fields:
        raise HTTPException(status_code=400, detail="At least one row field required for pivot mode")

    # Parse value metrics
    value_metrics, j = [], 0
    while f"vm_agg_{j}" in p:
        value_metrics.append({"agg": p[f"vm_agg_{j}"], "field": p.get(f"vm_field_{j}") or None, "label": p.get(f"vm_label_{j}") or f"Metric {j}"})
        j += 1
    if not value_metrics:
        value_metrics = [{"agg": "count", "field": None, "label": "Count"}]

    try:
        safe_rows = [_safe_col(table, f) for f in row_fields]
        safe_col  = _safe_col(table, col_field) if col_field else None
        agg_exprs = [_build_agg_expr(vm["agg"], vm["field"], table) for vm in value_metrics]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    group_cols  = safe_rows  # col field is pivoted via FILTER, NOT added to GROUP BY
    group_by    = ", ".join(safe_rows)
    select_cols = ", ".join(safe_rows)

    if col_field:
        col_vals_q   = f"SELECT DISTINCT {safe_col} FROM {table} {where} ORDER BY {safe_col} LIMIT 50"
        col_val_rows = await database.fetch_all(text(col_vals_q).bindparams(**params) if params else text(col_vals_q))
        col_values   = [r[0] for r in col_val_rows]

        pivot_selects = []
        for cv in col_values:
            cv_safe   = str(cv).replace("'", "''") if cv is not None else None
            cv_filter = f"{safe_col} = '{cv_safe}'" if cv is not None else f"{safe_col} IS NULL"
            for vm in value_metrics:
                agg = vm["agg"]
                if agg in ("count", "pct_of_total"):
                    expr = f"COUNT(*) FILTER (WHERE {cv_filter})"
                    if agg == "pct_of_total":
                        expr = f"ROUND(COUNT(*) FILTER (WHERE {cv_filter}) * 100.0 / NULLIF(COUNT(*), 0), 2)"
                elif agg == "count_distinct":
                    if vm["field"]:
                        expr = f"COUNT(DISTINCT {_safe_col(table, vm['field'])}) FILTER (WHERE {cv_filter})"
                    else:
                        expr = f"COUNT(*) FILTER (WHERE {cv_filter})"
                elif agg == "sum":  expr = f"SUM({_safe_col(table, vm['field'])}) FILTER (WHERE {cv_filter})"
                elif agg == "avg":  expr = f"ROUND(AVG({_safe_col(table, vm['field'])}) FILTER (WHERE {cv_filter})::numeric, 2)"
                elif agg == "min":  expr = f"MIN({_safe_col(table, vm['field'])}) FILTER (WHERE {cv_filter})"
                elif agg == "max":  expr = f"MAX({_safe_col(table, vm['field'])}) FILTER (WHERE {cv_filter})"
                else: expr = "NULL"
                pivot_selects.append(f"{expr} AS \"{cv}__{vm['label']}\"")
        for vm, ae in zip(value_metrics, agg_exprs):
            pivot_selects.append(f"{ae} AS \"__row_total__{vm['label']}\"")

        q = f"SELECT {select_cols}, {', '.join(pivot_selects)} FROM {table} {where} GROUP BY {group_by} ORDER BY {safe_rows[0]} LIMIT :limit"
        params["limit"] = limit
        try:
            rows = await database.fetch_all(text(q).bindparams(**params))
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        gt_selects = []
        no_limit_params = {k: v for k, v in params.items() if k != "limit"}
        for cv in col_values:
            cv_safe   = str(cv).replace("'", "''") if cv is not None else None
            cv_filter = f"{safe_col} = '{cv_safe}'" if cv is not None else f"{safe_col} IS NULL"
            for vm in value_metrics:
                gt_selects.append(f"COUNT(*) FILTER (WHERE {cv_filter}) AS \"{cv}__{vm['label']}\"")
        for vm, ae in zip(value_metrics, agg_exprs):
            gt_selects.append(f"{ae} AS \"__row_total__{vm['label']}\"")
        gt_sql = f"SELECT {', '.join(gt_selects)} FROM {table} {where}"
        gt_row = await database.fetch_one(text(gt_sql).bindparams(**no_limit_params) if no_limit_params else text(gt_sql))
        cnt_sql = f"SELECT COUNT(*) as cnt FROM (SELECT {group_by} FROM {table} {where} GROUP BY {group_by}) sub"
        cnt_row = await database.fetch_one(text(cnt_sql).bindparams(**no_limit_params) if no_limit_params else text(cnt_sql))
        total_rows = cnt_row["cnt"] if cnt_row else 0

        return {"mode": "pivot", "rows": [dict(r) for r in rows], "grand_total": dict(gt_row) if gt_row else None,
                "col_values": col_values, "total_rows": total_rows, "limited": total_rows > limit}

    else:
        # No column pivot — simple group by
        agg_select = ", ".join(f"{ae} AS \"{vm['label']}\"" for ae, vm in zip(agg_exprs, value_metrics))
        q = f"SELECT {select_cols}, {agg_select} FROM {table} {where} GROUP BY {group_by} ORDER BY {safe_rows[0]} LIMIT :limit"
        params["limit"] = limit
        try:
            rows = await database.fetch_all(text(q).bindparams(**params))
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        no_limit_params = {k: v for k, v in params.items() if k != "limit"}
        gt_agg  = ", ".join(f"{_build_agg_expr(vm['agg'], vm['field'], table)} AS \"{vm['label']}\"" for vm in value_metrics)
        gt_sql  = f"SELECT {gt_agg} FROM {table} {where}"
        cnt_sql = f"SELECT COUNT(*) as cnt FROM (SELECT {group_by} FROM {table} {where} GROUP BY {group_by}) sub"
        gt_row  = await database.fetch_one(text(gt_sql).bindparams(**no_limit_params) if no_limit_params else text(gt_sql))
        cnt_row = await database.fetch_one(text(cnt_sql).bindparams(**no_limit_params) if no_limit_params else text(cnt_sql))

        return {"mode": "pivot", "rows": [dict(r) for r in rows], "grand_total": dict(gt_row) if gt_row else None,
                "col_values": [], "total_rows": cnt_row["cnt"] if cnt_row else 0, "limited": (cnt_row["cnt"] if cnt_row else 0) > limit}


@router.get("/api/oflc/field-values/{table}")
async def oflc_field_values(table: str, field: str, q: str = "", limit: int = 12):
    """Typeahead: return distinct values for a field matching query string."""
    table_map  = {"perm": "oflc_perm", "lca": "oflc_lca", "pw": "oflc_pw"}
    full_table = table_map.get(table, table)
    if full_table not in OFLC_TABLES:
        raise HTTPException(status_code=400, detail=f"Unknown table: {table}")
    try:
        col = _safe_col(full_table, field)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    sql  = f"SELECT DISTINCT {col} AS val FROM {full_table} WHERE {col} IS NOT NULL AND {col} ILIKE :q ORDER BY {col} LIMIT :limit"
    rows = await database.fetch_all(text(sql).bindparams(q=f"%{q}%", limit=min(limit, 50)))
    return {"values": [r["val"] for r in rows]}


@router.get("/api/oflc/landing-stats")
async def oflc_landing_stats():
    """Quick counts and cert rate for the landing page stats bar."""
    perm = await database.fetch_one(text("""
        SELECT
            COUNT(*) AS total,
            ROUND(SUM(CASE WHEN case_status = 'Certified' THEN 1 ELSE 0 END) * 100.0 / NULLIF(COUNT(*),0), 1) AS cert_rate
        FROM oflc_perm
    """))
    lca = await database.fetch_one(text("SELECT COUNT(*) AS total FROM oflc_lca"))
    pw  = await database.fetch_one(text("SELECT COUNT(*) AS total FROM oflc_pw"))
    return {
        "perm_total":     perm["total"]     if perm else 0,
        "perm_cert_rate": perm["cert_rate"] if perm else None,
        "lca_total":      lca["total"]      if lca  else 0,
        "pw_total":       pw["total"]       if pw   else 0,
    }


