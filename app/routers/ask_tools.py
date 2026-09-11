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
            "name": "search_decisions",
            "description": (
                "Look up a decision by case name, party/employer name, or docket number, and find "
                "every passage in the BALCA/AAO/older-precedent corpora that discusses it. Use "
                "whenever a question names a specific case ('Solar Turbines', 'Matter of Dhanasar', "
                "'2016-PER-00025', 'the Kellogg decision') and the retrieved sources don't contain it. "
                "Returns matching decisions plus passages from later decisions that cite the case — "
                "use those to say what the case held even when the original is not in the corpus."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Case/party name or docket number, e.g. 'Solar Turbines'"},
                    "corpus": {"type": "string", "enum": ["all", "balca", "aao", "ina_cases"]},
                    "limit": {"type": "integer", "description": "Max passages (default 8, max 20)"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "search_regulations",
            "description": (
                "Full-text search of the primary authorities: 8/20/22 CFR (current), the INA, the "
                "USCIS Policy Manual, the FAM, DOL FAQs, Federal Register final rules, and form "
                "instructions. Use for any question about a visa classification, form, period of "
                "stay or validity, filing procedure, eligibility rule, or what a regulation says, "
                "whenever the retrieved sources don't already contain the answer. Regulations name "
                "classifications by letter ('E classification', 'treaty alien', 'specialty "
                "occupation'), so phrase the query the way the rule text would, and set cfr to pin "
                "a section (e.g. '214.2(e)', '656.17')."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Web-search style terms, e.g. 'treaty alien period of admission extension 2 years'"},
                    "cfr": {"type": "string", "description": "Optional section filter, e.g. '214.2(e)'"},
                    "corpus": {"type": "string", "enum": ["all", "regulation", "policy", "ina", "govinfo", "dol_faqs", "final_rules", "form_instructions"]},
                    "limit": {"type": "integer", "description": "Max passages (default 8, max 20)"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "get_employer_representation",
            "description": (
                "Who represents an employer: the law firm(s) and attorney(s) of record on the "
                "employer's PERM, LCA/H-1B, and Prevailing Wage filings, with filing counts, "
                "certified/denied counts, and first/last filing dates for each firm+attorney "
                "combination, ordered most-recent first. ALWAYS use this (not query_oflc_data) "
                "for 'who represents X', 'who is X's immigration counsel', 'which firm files "
                "X's H-1Bs/PERMs', or 'did X change law firms'. Handles fuzzy employer-name "
                "matching across the many spellings in disclosure data. If the result lists "
                "many matched_employers with no rows, re-run with a more specific name."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "employer": {"type": "string", "description": "Employer name as the user gave it"},
                    "program": {"type": "string", "enum": ["all", "PERM", "LCA", "PWD"],
                                "description": "Default all"},
                    "limit": {"type": "integer", "description": "Max firm/attorney rows (default 25)"},
                },
                "required": ["employer"],
            },
        },
        {
            "name": "get_firm_clients",
            "description": (
                "Which employers a law firm or attorney represents, by filing volume, across "
                "PERM/LCA/PWD, with certified/denied counts and date range. Use for 'who are "
                "firm Y's clients', 'how many employers does attorney Z represent', 'what does "
                "Y file'. Matches on firm name OR attorney name (substring, case-insensitive)."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Law firm or attorney name"},
                    "program": {"type": "string", "enum": ["all", "PERM", "LCA", "PWD"]},
                    "limit": {"type": "integer", "description": "Max client rows (default 30)"},
                },
                "required": ["name"],
            },
        },
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
                "use ILIKE. The oflc_perm used_* columns (used_radio_ad, used_job_fair, "
                "used_emp_website, used_job_search_site, used_on_campus_recruiting, "
                "used_trade_org, used_private_firm, used_emp_referral, "
                "used_campus_placement, used_local_newspaper) are the additional "
                "professional recruitment steps from the new-form ETA-9089: 'Y'/'N' "
                "for new-form filings (most of FY2024 onward), NULL for legacy-form "
                "rows (FY2023 and earlier). When computing recruitment-step "
                "percentages, restrict the denominator to rows where the column IS "
                "NOT NULL (filter on it = 'Y' vs = 'N'), and never treat NULL as "
                "'did not use' — legacy filings simply don't report these steps. "
                "Dates are real date columns. oflc_lca and oflc_pw span "
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


# ── Representation (mv_employer_representation) ───────────────────────────────

import re as _re


def _norm_employer(name: str) -> str:
    s = _re.sub(r"[^\w\s]", " ", name or "")
    s = _re.sub(r"\b(inc|llc|corp|corporation|co|ltd|lp|llp|plc|the)\b", " ", s, flags=_re.I)
    return _re.sub(r"\s+", " ", s).strip().lower()


_REP_SELECT = """
    SELECT program, firm, attorney,
           SUM(filings)::int AS filings, SUM(certified)::int AS certified, SUM(denied)::int AS denied,
           MIN(first_date) AS first_date, MAX(last_date) AS last_date,
           COUNT(DISTINCT employer_name)::int AS employer_name_variants
    FROM mv_employer_representation
    WHERE {where}
    GROUP BY 1,2,3
    ORDER BY MAX(last_date) DESC NULLS LAST, SUM(filings) DESC
    LIMIT :lim
"""


async def _run_employer_representation(inp: dict) -> dict:
    employer = (inp.get("employer") or "").strip()
    if not employer:
        raise ValueError("employer is required")
    q = _norm_employer(employer)
    if len(q) < 3:
        raise ValueError("employer name too short")
    program = (inp.get("program") or "all").upper()
    limit = min(int(inp.get("limit", 25)), 60)
    prog_clause = "" if program == "ALL" else " AND program = :prog"
    params = {"q": f"%{q}%", "lim": limit}
    if program != "ALL":
        params["prog"] = program

    # 1. Which employer names match? (substring on normalized name; fuzzy fallback)
    match_sql = f"""
        SELECT employer_name, SUM(filings)::int AS filings, MAX(last_date) AS last_date
        FROM mv_employer_representation
        WHERE employer_norm ILIKE :q{prog_clause}
        GROUP BY 1 ORDER BY 2 DESC LIMIT 40"""
    matches = await database.fetch_all(text(match_sql).bindparams(**{k: v for k, v in params.items() if k != "lim"}))
    mode = "substring"
    if not matches:
        fz = {"qn": q, **({"prog": program} if program != "ALL" else {})}
        matches = await database.fetch_all(text(f"""
            SELECT employer_name, SUM(filings)::int AS filings, MAX(last_date) AS last_date
            FROM mv_employer_representation
            WHERE similarity(:qn, employer_norm) > 0.5{prog_clause}
            GROUP BY 1 ORDER BY 2 DESC LIMIT 40""").bindparams(**fz))
        mode = "fuzzy"
    if not matches:
        return {"employer_query": employer, "matched_employers": [], "rows": [],
                "note": "No employer in OFLC disclosure data matched. Try a shorter or alternate name."}

    names = [m["employer_name"] for m in matches]
    # 2. Too many distinct employers → ask the model to narrow rather than blending them.
    if len(names) > 15 and mode == "substring":
        return {"employer_query": employer, "match_mode": mode,
                "matched_employers": [dict(m) for m in matches[:20]], "rows": [],
                "note": "Query matched many distinct employers. Re-run with a more specific employer name, or pick one from matched_employers."}

    where = "employer_name = ANY(:names)" + prog_clause
    rp = {"names": names, "lim": limit, **({"prog": program} if program != "ALL" else {})}
    rows = await database.fetch_all(text(_REP_SELECT.format(where=where)).bindparams(**rp))
    return {
        "employer_query": employer, "match_mode": mode,
        "matched_employers": [dict(m) for m in matches],
        "rows": [dict(r) for r in rows],
        "source": "OFLC disclosure data: PERM FY2015-FY2026, LCA FY2020-FY2026, PWD FY2021-FY2026 (attorney fields absent before those years)",
        "note": "Null firm/attorney = employer filed without counsel. Ordered by most recent activity; the top rows are current counsel.",
    }


async def _run_firm_clients(inp: dict) -> dict:
    name = (inp.get("name") or "").strip()
    if len(name) < 3:
        raise ValueError("name is required")
    program = (inp.get("program") or "all").upper()
    limit = min(int(inp.get("limit", 30)), 100)
    prog_clause = "" if program == "ALL" else " AND program = :prog"
    params = {"q": f"%{name.lower()}%", "lim": limit, **({"prog": program} if program != "ALL" else {})}
    rows = await database.fetch_all(text(f"""
        SELECT employer_name, program,
               SUM(filings)::int AS filings, SUM(certified)::int AS certified, SUM(denied)::int AS denied,
               MIN(first_date) AS first_date, MAX(last_date) AS last_date,
               array_agg(DISTINCT attorney) FILTER (WHERE attorney IS NOT NULL) AS attorneys
        FROM mv_employer_representation
        WHERE (lower(firm) LIKE :q OR lower(attorney) LIKE :q){prog_clause}
        GROUP BY 1,2 ORDER BY SUM(filings) DESC LIMIT :lim""").bindparams(**params))
    tot = await database.fetch_one(text(f"""
        SELECT COUNT(DISTINCT employer_name)::int AS employers, SUM(filings)::int AS filings,
               array_agg(DISTINCT firm) FILTER (WHERE firm IS NOT NULL) AS firm_variants
        FROM mv_employer_representation
        WHERE (lower(firm) LIKE :q OR lower(attorney) LIKE :q){prog_clause}""").bindparams(
        **{k: v for k, v in params.items() if k != "lim"}))
    return {"name_query": name, "summary": dict(tot) if tot else {},
            "rows": [dict(r) for r in rows],
            "source": "OFLC disclosure data (PERM/LCA/PWD), matched on firm or attorney name",
            "note": "Rows are top clients by filing volume; summary gives totals across all matches."}


# ── Decision lookup by name / number (lexical) ────────────────────────────────

async def _run_search_decisions(inp: dict) -> dict:
    q = (inp.get("query") or "").strip()
    if len(q) < 3:
        raise ValueError("query is required")
    corpus = (inp.get("corpus") or "all").lower()
    limit = min(int(inp.get("limit", 8)), 20)
    corpora = ["balca", "aao", "ina_cases"] if corpus == "all" else [corpus]

    # 1. BALCA decisions table: employer name or docket number
    dec_rows = await database.fetch_all(text("""
        SELECT id, case_number, decision_date, outcome, employer_name, source_url
        FROM decisions
        WHERE lower(employer_name) LIKE :q OR case_number ILIKE :q
        ORDER BY decision_date DESC NULLS LAST LIMIT :lim
    """).bindparams(q=f"%{q.lower()}%", lim=limit))
    own_ids = [str(r["id"]) for r in dec_rows[:3]]
    own_passages = []
    if own_ids and corpus in ("all", "balca"):
        own_passages = [dict(r) for r in await database.fetch_all(text("""
            SELECT source_id, source_label, source_date, source_outcome, chunk_index,
                   left(chunk_text, 900) AS passage
            FROM rag_chunks
            WHERE corpus = 'balca' AND source_id = ANY(:ids)
            ORDER BY source_id,
                     ts_rank_cd(to_tsvector('english', chunk_text),
                                to_tsquery('english', 'hold | held | holding | conclude | reverse | reversed | affirm | affirmed | order | ordered')) DESC
            LIMIT 6
        """).bindparams(ids=own_ids))]

    # 2. Passages anywhere in the decision corpora that use the phrase
    # corpus filtered in Python: a corpus predicate alongside the FTS index is ~3 s (BitmapAnd)
    raw = await database.fetch_all(text("""
        SELECT id, corpus, source_id, source_label, source_date, source_outcome,
               ts_headline('english', chunk_text, phraseto_tsquery('english', :ph),
                           'MaxWords=70, MinWords=40, StartSel=<<, StopSel=>>') AS snippet,
               (lower(source_label) LIKE :lbl) AS is_the_decision
        FROM rag_chunks
        WHERE to_tsvector('english', chunk_text) @@ phraseto_tsquery('english', :ph)
        ORDER BY is_the_decision DESC, source_date DESC NULLS LAST
        LIMIT :lim
    """).bindparams(ph=q, lbl=f"%{q.lower()}%", lim=limit * 5))
    chunk_rows = [r for r in raw if r["corpus"] in corpora][:limit]
    total = await database.fetch_one(text("""
        SELECT COUNT(*)::int AS n FROM (
          SELECT 1 FROM rag_chunks
          WHERE to_tsvector('english', chunk_text) @@ phraseto_tsquery('english', :ph) LIMIT 5000) x
    """).bindparams(ph=q))

    return {
        "query": q,
        "decisions_matching_name_or_number": [{k: v for k, v in dict(r).items() if k != "id"} for r in dec_rows],
        "passages_from_those_decisions": own_passages,
        "passages_mentioning": [dict(r) for r in chunk_rows],
        "total_passages_mentioning": (f"{total['n']}+" if total and total["n"] >= 5000 else (total["n"] if total else 0)),
        "coverage": "BALCA decisions 2006-present; AAO non-precedent decisions; ina_cases = older BIA/INA precedents. "
                    "Pre-2006 BALCA precedents are not source documents here — rely on how later decisions describe them.",
        "note": "passages_from_those_decisions are the matched decision's own text (use these for what it "
                "held); passages_mentioning are later decisions citing or discussing it. Cite by source_label. "
                "If decisions_matching_name_or_number is non-empty, the decision IS in the corpus.",
    }


# ── Authority text search (regs, policy manual, FAM, INA, FAQs, forms) ────────

_AUTHORITY = ("regulation", "policy", "ina", "govinfo", "dol_faqs", "final_rules",
              "form_instructions", "form_instructions_dol", "uscis_checklists", "cbp_ifm")


async def _run_search_regulations(inp: dict) -> dict:
    query = (inp.get("query") or "").strip()
    if len(query) < 3:
        raise ValueError("query is required")
    cfr = (inp.get("cfr") or "").strip()
    corpus = (inp.get("corpus") or "all").lower()
    limit = min(int(inp.get("limit", 8)), 20)
    corpora = list(_AUTHORITY) if corpus == "all" else [corpus]
    cin = ", ".join(f":c{i}" for i in range(len(corpora)))
    bind = {"q": query, "lim": limit, **{f"c{i}": c for i, c in enumerate(corpora)}}
    cfr_clause = ""
    if cfr:
        # chunks are labeled at section level ('20 CFR 656.10'); match the section, not the subsection
        import re as _re2
        m = _re2.search(r"(\d{3}\.\d+)", cfr)
        sec = m.group(1) if m else cfr
        cfr_clause = " AND cfr_citation LIKE :cfr"
        bind["cfr"] = f"% CFR {sec}"
    rows = await database.fetch_all(text(f"""
        SELECT corpus, source_label, cfr_citation, source_date, chunk_index,
               ts_headline('english', chunk_text, websearch_to_tsquery('english', :q),
                           'MaxWords=90, MinWords=50, StartSel=<<, StopSel=>>') AS snippet,
               ts_rank_cd(to_tsvector('english', chunk_text), websearch_to_tsquery('english', :q)) AS rank
        FROM rag_chunks
        WHERE corpus IN ({cin})
          AND to_tsvector('english', chunk_text) @@ websearch_to_tsquery('english', :q){cfr_clause}
        ORDER BY rank DESC LIMIT :lim
    """).bindparams(**bind))
    return {
        "query": query, "cfr_filter": cfr or None,
        "passages": [dict(r) for r in rows],
        "coverage": "8 CFR / 20 CFR / 22 CFR (current editions), INA, USCIS Policy Manual, FAM, DOL FAQs, "
                    "Federal Register final rules, USCIS/DOL form instructions.",
        "note": "Plain-word search (AND of terms; use OR / quotes / -term like a web search). Regulations refer "
                "to classifications by letter ('E classification', 'treaty alien', 'H-1B'), so search the "
                "regulatory phrasing, and use cfr to pin a section, e.g. cfr='214.2(e)'. Cite passages by "
                "source_label / cfr_citation.",
    }


_EXECUTORS = {
    "search_decisions": _run_search_decisions,
    "search_regulations": _run_search_regulations,
    "get_employer_representation": _run_employer_representation,
    "get_firm_clients": _run_firm_clients,
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
