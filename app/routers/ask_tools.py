"""Tool definitions + executors for the Ask AI agentic loop.

Gives the Ask AI generation model structured access to DOL/OFLC performance
data (disclosure aggregates, processing times, visa bulletin) alongside the
retrieved RAG chunks. All SQL goes through the same whitelisted column /
operator helpers as the OFLC Query Builder.
"""
import json
from datetime import date

from sqlalchemy import text

from core import *  # noqa: F401,F403 -- database, OFLC_TABLES, config

MAX_TOOL_RESULT_CHARS = 6000
MAX_GROUP_LIMIT = 200

_OPS = ("=", "!=", ">", ">=", "<", "<=", "ILIKE", "NOT ILIKE", "IS NULL", "IS NOT NULL")
_AGGS = ("count", "count_distinct", "sum", "avg", "min", "max")


def _cols_doc() -> str:
    parts = []
    for t, cfg in OFLC_TABLES.items():
        cols = sorted(cfg["text_cols"] | cfg["numeric_cols"] | cfg["date_cols"])
        parts.append(f"{t}: {', '.join(cols)}")
    return "\n".join(parts)


def build_tools_schema() -> list:
    """Anthropic tool schemas. Built at call time so column docs stay in sync."""
    return [
        {
            "name": "query_oflc_data",
            "description": (
                "Run a query against OFLC disclosure data (FY2020-FY2026): "
                "PERM (oflc_perm), LCA/H-1B (oflc_lca), and Prevailing Wage (oflc_pw) filings. "
                "Use for questions about filing volumes, approval/denial rates, employers, "
                "wages, occupations, states, attorneys, etc. Two modes:\n"
                "1. AGGREGATE (default): group_by + metrics. Grouped results are ordered "
                "by the first metric descending (top-N friendly). With no group_by, "
                "returns a single aggregate row.\n"
                "2. RAW ROWS: set select_fields to list individual filings (e.g. a "
                "specific employer's cases). Returns up to 50 rows, newest received_date "
                "first. group_by/metrics are ignored when select_fields is set.\n"
                "Available columns per table:\n" + _cols_doc() + "\n"
                "Notes: case_status values include 'Certified', 'Denied', 'Withdrawn', "
                "'Certified-Expired', 'Certified - Expired'. fiscal_year is text formatted "
                "'FY2025' (available range FY2020-FY2026). Employer name matching should "
                "use ILIKE. Dates are real date columns. oflc_lca and oflc_pw span "
                "multiple visa classes — visa_class values include 'H-1B', "
                "'E-3 Australian', 'H-1B1 Chile', 'H-1B1 Singapore' — so ALWAYS filter "
                "visa_class = 'H-1B' when the question is specifically about H-1B; only "
                "omit it when the question is about LCAs generally. If an equality "
                "filter returns zero rows, re-check the value format (e.g. try ILIKE) "
                "before concluding the data shows zero."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "table": {"type": "string", "enum": list(OFLC_TABLES.keys())},
                    "filters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "field": {"type": "string"},
                                "op": {"type": "string", "enum": list(_OPS)},
                                "val": {"type": "string"},
                            },
                            "required": ["field", "op"],
                        },
                    },
                    "group_by": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Optional fields to group by (e.g. ['fiscal_year'] or ['employer_name'])",
                    },
                    "metrics": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "agg": {"type": "string", "enum": list(_AGGS)},
                                "field": {"type": "string"},
                            },
                            "required": ["agg"],
                        },
                        "description": "Defaults to [{'agg':'count'}]",
                    },
                    "select_fields": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Raw-row mode: columns to return per filing (e.g. ['case_number','job_title','case_status','wage_from','decision_date'])",
                    },
                    "limit": {"type": "integer", "description": "Max rows (default 25; max 200 grouped, 50 raw)"},
                },
                "required": ["table"],
            },
        },
        {
            "name": "get_dol_processing_times",
            "description": (
                "Get DOL processing-time statistics (calendar days from received date to "
                "final determination, monthly percentiles p25/median/p75/p90) computed from "
                "OFLC disclosure data. Programs: perm, lca (H-1B/H-1B1/E-3), pw (prevailing wage)."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "program": {"type": "string", "enum": ["perm", "lca", "pw"]},
                    "visa_class": {"type": "string", "description": "Optional, lca/pw only (e.g. 'H-1B')"},
                    "months": {"type": "integer", "description": "How many most-recent months (default 12, max 36)"},
                },
                "required": ["program"],
            },
        },
        {
            "name": "get_visa_bulletin_current",
            "description": (
                "Get priority dates from the visa bulletin currently in force. "
                "Returns preference category, chargeability area, and cutoff dates."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "category_type": {"type": "string", "enum": ["employment", "family"]},
                    "date_type": {"type": "string", "enum": ["final_action", "dates_for_filing"]},
                },
            },
        },
    ]


# ── Executors ─────────────────────────────────────────────────────────────────

def _safe_col(table: str, col: str) -> str:
    if table not in OFLC_TABLES:
        raise ValueError(f"Unknown table: {table}")
    cfg = OFLC_TABLES[table]
    all_cols = cfg["text_cols"] | cfg["numeric_cols"] | cfg["date_cols"] | {"id"}
    if col not in all_cols:
        raise ValueError(f"Unknown column '{col}' for table '{table}'")
    return f'"{col}"'


def _agg_expr(table: str, agg: str, field: str | None) -> str:
    if agg == "count":
        return "COUNT(*)"
    if not field:
        raise ValueError(f"Aggregation '{agg}' requires a field")
    col = _safe_col(table, field)
    return {
        "count_distinct": f"COUNT(DISTINCT {col})",
        "sum": f"SUM({col})",
        "avg": f"ROUND(AVG({col})::numeric, 2)",
        "min": f"MIN({col})",
        "max": f"MAX({col})",
    }[agg]


def _where(table: str, filters: list) -> tuple[str, dict]:
    clauses, params = [], {}
    for i, f in enumerate(filters or []):
        field, op, val = f.get("field"), f.get("op"), f.get("val", "")
        if not field:
            continue
        col = _safe_col(table, field)
        key = f"fv_{i}"
        if op == "IS NULL":
            clauses.append(f"{col} IS NULL")
        elif op == "IS NOT NULL":
            clauses.append(f"{col} IS NOT NULL")
        elif op == "ILIKE":
            clauses.append(f"{col} ILIKE :{key}"); params[key] = f"%{val}%"
        elif op == "NOT ILIKE":
            clauses.append(f"{col} NOT ILIKE :{key}"); params[key] = f"%{val}%"
        elif op in ("=", "!=", ">", ">=", "<", "<="):
            clauses.append(f"{col} {op} :{key}"); params[key] = val
        else:
            raise ValueError(f"Unknown operator: {op}")
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


async def _run_query_oflc(inp: dict) -> dict:
    table = inp.get("table")
    if table not in OFLC_TABLES:
        raise ValueError(f"Unknown table: {table}")
    where, params = _where(table, inp.get("filters"))

    # ── Raw-row mode ──────────────────────────────────────────────────────────
    select_fields = inp.get("select_fields")
    if select_fields:
        safe_sel = [_safe_col(table, f) for f in select_fields]
        limit = min(int(inp.get("limit", 25)), 50)
        sql = (f"SELECT {', '.join(safe_sel)} FROM {table} {where} "
               f"ORDER BY \"received_date\" DESC NULLS LAST, id DESC LIMIT :lim")
        params["lim"] = limit
        rows = await database.fetch_all(text(sql).bindparams(**params))
        cnt_sql = f"SELECT COUNT(*)::int AS cnt FROM {table} {where}"
        nl = {k: v for k, v in params.items() if k != "lim"}
        cnt = await database.fetch_one(text(cnt_sql).bindparams(**nl) if nl else text(cnt_sql))
        total = cnt["cnt"] if cnt else 0
        return {"table": table, "rows": [dict(r) for r in rows],
                "total_matching": total, "truncated": total > limit}

    # ── Aggregate mode ────────────────────────────────────────────────────────
    metrics = inp.get("metrics") or [{"agg": "count"}]
    group_by = inp.get("group_by") or []
    limit = min(int(inp.get("limit", 25)), MAX_GROUP_LIMIT)

    agg_selects = []
    for j, m in enumerate(metrics):
        expr = _agg_expr(table, m.get("agg", "count"), m.get("field"))
        label = f"{m.get('agg','count')}" + (f"_{m['field']}" if m.get("field") else "")
        agg_selects.append(f"{expr} AS \"{label}\"")

    if group_by:
        safe_groups = [_safe_col(table, g) for g in group_by]
        first_metric = _agg_expr(table, metrics[0].get("agg", "count"), metrics[0].get("field"))
        sql = (f"SELECT {', '.join(safe_groups)}, {', '.join(agg_selects)} "
               f"FROM {table} {where} GROUP BY {', '.join(safe_groups)} "
               f"ORDER BY {first_metric} DESC NULLS LAST LIMIT :lim")
        params["lim"] = limit
        rows = await database.fetch_all(text(sql).bindparams(**params))
        return {"table": table, "rows": [dict(r) for r in rows], "row_count": len(rows)}

    sql = f"SELECT {', '.join(agg_selects)} FROM {table} {where}"
    row = await database.fetch_one(text(sql).bindparams(**params) if params else text(sql))
    return {"table": table, "result": dict(row) if row else {}}


_DOL_PROGRAMS = {
    "perm": ("oflc_perm", "received_date", "decision_date", None),
    "lca":  ("oflc_lca", "received_date", "decision_date", "visa_class"),
    "pw":   ("oflc_pw", "received_date", "determination_date", "visa_class"),
}


async def _run_dol_processing_times(inp: dict) -> dict:
    program = inp.get("program")
    if program not in _DOL_PROGRAMS:
        raise ValueError("program must be perm, lca, or pw")
    table, received, decision, extra = _DOL_PROGRAMS[program]
    months = min(int(inp.get("months", 12)), 36)
    clauses = [f"{received} IS NOT NULL", f"{decision} IS NOT NULL", f"{decision} >= {received}"]
    params: dict = {}
    if inp.get("visa_class") and extra:
        clauses.append(f"{extra} = :vc")
        params["vc"] = inp["visa_class"]
    where = " AND ".join(clauses)
    sql = f"""
        SELECT to_char(date_trunc('month', {decision}), 'YYYY-MM') AS month,
               COUNT(*)::int AS case_count,
               ROUND(PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY {decision} - {received})::numeric, 1) AS p25_days,
               ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY {decision} - {received})::numeric, 1) AS median_days,
               ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY {decision} - {received})::numeric, 1) AS p75_days,
               ROUND(PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY {decision} - {received})::numeric, 1) AS p90_days
        FROM {table}
        WHERE {where}
        GROUP BY 1 ORDER BY 1 DESC LIMIT :months
    """
    params["months"] = months
    rows = await database.fetch_all(text(sql).bindparams(**params))
    return {
        "program": program, "unit": "calendar days received->determination",
        "source": "OFLC disclosure data",
        "months": [dict(r) for r in rows],
    }


async def _run_visa_bulletin_current(inp: dict) -> dict:
    from routers.visa_bulletin import EFFECTIVE_BULLETIN
    clauses, params = [f"bulletin_date = {EFFECTIVE_BULLETIN}"], {}
    if inp.get("category_type"):
        clauses.append("category_type = :ct"); params["ct"] = inp["category_type"]
    if inp.get("date_type"):
        clauses.append("date_type = :dt"); params["dt"] = inp["date_type"]
    where = "WHERE " + " AND ".join(clauses)
    rows = await database.fetch_all(text(f"""
        SELECT bulletin_date, category_type, date_type, preference,
               chargeability, priority_date, is_current, is_unavailable
        FROM visa_bulletin {where}
        ORDER BY category_type, date_type, preference, chargeability
    """).bindparams(**params) if params else text(f"""
        SELECT bulletin_date, category_type, date_type, preference,
               chargeability, priority_date, is_current, is_unavailable
        FROM visa_bulletin {where}
        ORDER BY category_type, date_type, preference, chargeability
    """))
    return {"rows": [dict(r) for r in rows]}


_EXECUTORS = {
    "query_oflc_data": _run_query_oflc,
    "get_dol_processing_times": _run_dol_processing_times,
    "get_visa_bulletin_current": _run_visa_bulletin_current,
}


async def execute_ask_tool(name: str, tool_input: dict) -> str:
    """Run a tool and return a JSON string, truncated to a safe token budget."""
    fn = _EXECUTORS.get(name)
    if fn is None:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        result = await fn(tool_input or {})
    except Exception as e:  # surface DB/validation errors to the model
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
    out = json.dumps(result, default=str)
    if len(out) > MAX_TOOL_RESULT_CHARS:
        out = out[:MAX_TOOL_RESULT_CHARS] + '... (truncated)"}'
    return out
