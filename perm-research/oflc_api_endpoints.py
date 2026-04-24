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
            "pwd_unit","pw_wage_level","wage_source","bls_area",
            "worksite_city","worksite_state","worksite_postal_code",
        },
        "numeric_cols": {"pwd_wage_rate"},
        "date_cols":    {"received_date","determination_date","pwd_wage_expiration_date","ingested_at"},
    },
}

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

@app.get("/api/oflc/query")
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
            rows = await database.fetch_all(text(q), params)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
        count_q = f"SELECT COUNT(*) as cnt FROM {table} {where}"
        total_row = await database.fetch_one(text(count_q), {k: v for k, v in params.items() if k != "limit"})
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

    group_cols  = safe_rows + ([safe_col] if safe_col else [])
    group_by    = ", ".join(group_cols)
    select_cols = ", ".join(group_cols)

    if col_field:
        col_vals_q   = f"SELECT DISTINCT {safe_col} FROM {table} {where} ORDER BY {safe_col} LIMIT 50"
        col_val_rows = await database.fetch_all(text(col_vals_q), params)
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
                    expr = f"COUNT(DISTINCT {_safe_col(table, vm['field'])}) FILTER (WHERE {cv_filter})"
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
            rows = await database.fetch_all(text(q), params)
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
        gt_row = await database.fetch_one(text(f"SELECT {', '.join(gt_selects)} FROM {table} {where}"), no_limit_params)
        cnt_row = await database.fetch_one(
            text(f"SELECT COUNT(*) as cnt FROM (SELECT {group_by} FROM {table} {where} GROUP BY {group_by}) sub"),
            no_limit_params,
        )
        total_rows = cnt_row["cnt"] if cnt_row else 0

        return {"mode": "pivot", "rows": [dict(r) for r in rows], "grand_total": dict(gt_row) if gt_row else None,
                "col_values": col_values, "total_rows": total_rows, "limited": total_rows > limit}

    else:
        # No column pivot — simple group by
        agg_select = ", ".join(f"{ae} AS \"{vm['label']}\"" for ae, vm in zip(agg_exprs, value_metrics))
        q = f"SELECT {select_cols}, {agg_select} FROM {table} {where} GROUP BY {group_by} ORDER BY {safe_rows[0]} LIMIT :limit"
        params["limit"] = limit
        try:
            rows = await database.fetch_all(text(q), params)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

        no_limit_params = {k: v for k, v in params.items() if k != "limit"}
        gt_agg  = ", ".join(f"{_build_agg_expr(vm['agg'], vm['field'], table)} AS \"{vm['label']}\"" for vm in value_metrics)
        gt_row  = await database.fetch_one(text(f"SELECT {gt_agg} FROM {table} {where}"), no_limit_params)
        cnt_row = await database.fetch_one(text(f"SELECT COUNT(*) as cnt FROM (SELECT {group_by} FROM {table} {where} GROUP BY {group_by}) sub"), no_limit_params)

        return {"mode": "pivot", "rows": [dict(r) for r in rows], "grand_total": dict(gt_row) if gt_row else None,
                "col_values": [], "total_rows": cnt_row["cnt"] if cnt_row else 0, "limited": (cnt_row["cnt"] if cnt_row else 0) > limit}


@app.get("/api/oflc/{table}/values")
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
    rows = await database.fetch_all(text(sql), {"q": f"%{q}%", "limit": min(limit, 50)})
    return {"values": [r["val"] for r in rows]}
