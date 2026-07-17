"""Historical DOL and USCIS processing-time APIs."""

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from core import database

router = APIRouter(prefix="/api/processing-times", tags=["processing-times"])

DOL_PROGRAMS = {
    "perm": {
        "table": "oflc_perm", "received": "received_date", "decision": "decision_date",
        "label": "PERM", "extra": None,
    },
    "lca": {
        "table": "oflc_lca", "received": "received_date", "decision": "decision_date",
        "label": "LCA (H-1B/H-1B1/E-3)", "extra": "visa_class",
    },
    "pw": {
        "table": "oflc_pw", "received": "received_date", "decision": "determination_date",
        "label": "Prevailing Wage", "extra": "visa_class",
    },
}


@router.get("/dol")
async def dol_processing_times(
    program: str = Query("perm", pattern="^(perm|lca|pw)$"),
    visa_class: Optional[str] = Query(None),
):
    cfg = DOL_PROGRAMS.get(program)
    if not cfg:
        raise HTTPException(status_code=400, detail="Unknown DOL program")
    table, received, decision = cfg["table"], cfg["received"], cfg["decision"]
    clauses = [f"{received} IS NOT NULL", f"{decision} IS NOT NULL", f"{decision} >= {received}"]
    params = {}
    if visa_class and cfg["extra"]:
        clauses.append("visa_class = :visa_class")
        params["visa_class"] = visa_class
    where = " AND ".join(clauses)
    sql = f"""
        SELECT date_trunc('month', {decision})::date AS period_start,
               (date_trunc('month', {decision}) + interval '1 month - 1 day')::date AS period_end,
               COUNT(*)::int AS case_count,
               ROUND(PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY {decision} - {received})::numeric, 1) AS p25,
               ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY {decision} - {received})::numeric, 1) AS median,
               ROUND(PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY {decision} - {received})::numeric, 1) AS p75,
               ROUND(PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY {decision} - {received})::numeric, 1) AS p90
        FROM {table}
        WHERE {where}
        GROUP BY 1, 2
        ORDER BY 1
    """
    rows = await database.fetch_all(text(sql).bindparams(**params) if params else text(sql))
    classes = []
    if cfg["extra"]:
        class_rows = await database.fetch_all(text(
            f"SELECT visa_class, COUNT(*)::int AS count FROM {table} "
            "WHERE visa_class IS NOT NULL GROUP BY visa_class ORDER BY count DESC"
        ))
        classes = [dict(row) for row in class_rows]
    return {
        "agency": "DOL", "program": program, "label": cfg["label"], "unit": "days",
        "methodology": "Calendar days from received date to final determination, grouped by determination month.",
        "visa_classes": classes, "points": [dict(row) for row in rows],
    }


@router.get("/uscis/options")
async def uscis_processing_options():
    rows = await database.fetch_all(text("""
        SELECT series_key, series_label, form_type, classification, statistic,
               MIN(period_start) AS first_period, MAX(period_end) AS last_period,
               COUNT(*)::int AS point_count
        FROM processing_time_observations
        WHERE agency='USCIS' AND metric_name='processing_time'
          AND period_granularity <> 'snapshot'
        GROUP BY series_key, series_label, form_type, classification, statistic
        ORDER BY form_type, series_label, statistic
    """))
    return [dict(row) for row in rows]


@router.get("/uscis/series")
async def uscis_processing_series(series_key: str = Query(..., min_length=3)):
    rows = await database.fetch_all(text("""
        SELECT series_key, series_label, form_type, classification, office,
               period_start, period_end, period_granularity, statistic,
               value::float8 AS value, unit, case_count, source_name, source_url,
               metadata
        FROM processing_time_observations
        WHERE agency='USCIS' AND metric_name='processing_time' AND series_key=:series_key
        ORDER BY period_start, period_end
    """).bindparams(series_key=series_key))
    if not rows:
        raise HTTPException(status_code=404, detail="Processing-time series not found")
    return [dict(row) for row in rows]


@router.get("/uscis/overview")
async def uscis_processing_overview():
    rows = await database.fetch_all(text("""
        SELECT series_key, series_label, form_type, period_start, period_end,
               value::float8 AS value, unit, source_name, source_url
        FROM processing_time_observations
        WHERE agency='USCIS' AND metric_name='processing_time'
          AND statistic='average' AND period_granularity='month'
          AND (
            form_type IN ('I-130', 'I-765', 'N-400')
            OR (form_type='I-485' AND series_label ILIKE '%Employment%')
          )
        ORDER BY series_label, period_start
    """))
    series = {}
    for row in rows:
        item = dict(row)
        key = item["series_key"]
        if key not in series:
            series[key] = {
                "series_key": key,
                "series_label": item["series_label"],
                "form_type": item["form_type"],
                "points": [],
            }
        series[key]["points"].append({
            "period_start": item["period_start"],
            "period_end": item["period_end"],
            "value": item["value"],
        })
    return {
        "statistic": "average",
        "unit": "months",
        "methodology": "Average months for cases completed during each month. Selected high-use forms are shown on one shared scale.",
        "series": list(series.values()),
    }


@router.get("/uscis/i129/history")
async def uscis_i129_history():
    rows = await database.fetch_all(text("""
        SELECT series_key, series_label, form_type, period_start, period_end,
               statistic, value::float8 AS value, unit, source_name, source_url
        FROM processing_time_observations
        WHERE agency='USCIS' AND form_type='I-129'
          AND metric_name='processing_time' AND period_granularity <> 'snapshot'
        ORDER BY period_start
    """))
    return [dict(row) for row in rows]


@router.get("/uscis/i140/context")
async def uscis_i140_context(classification: str = Query("EB-2 NIW")):
    rows = await database.fetch_all(text("""
        SELECT period_start, period_end, classification,
               MAX(value::float8) FILTER (WHERE metric_name='received') AS received,
               MAX(value::float8) FILTER (WHERE metric_name='approved') AS approved,
               MAX(value::float8) FILTER (WHERE metric_name='denied') AS denied,
               MAX(value::float8) FILTER (WHERE metric_name='pending') AS pending,
               MAX(value::float8) FILTER (WHERE metric_name='decision_approval_rate') AS decision_approval_rate,
               MAX(value::float8) FILTER (WHERE metric_name='decision_denial_rate') AS decision_denial_rate
        FROM processing_time_observations
        WHERE agency='USCIS' AND form_type='I-140'
          AND classification=:classification
          AND series_key LIKE 'uscis-i140-context:%'
        GROUP BY period_start, period_end, classification
        ORDER BY period_start
    """).bindparams(classification=classification))
    classes = await database.fetch_all(text("""
        SELECT classification
        FROM processing_time_observations
        WHERE agency='USCIS' AND form_type='I-140'
          AND series_key LIKE 'uscis-i140-context:%'
        GROUP BY classification
        ORDER BY CASE classification
          WHEN 'EB-1 (all)' THEN 1 WHEN 'EB-1A' THEN 2 WHEN 'EB-1B' THEN 3 WHEN 'EB-1C' THEN 4
          WHEN 'EB-2 (all)' THEN 5 WHEN 'EB-2 (non-NIW)' THEN 6 WHEN 'EB-2 NIW' THEN 7
          WHEN 'EB-3 (all)' THEN 8 WHEN 'EB-3 Skilled' THEN 9
          WHEN 'EB-3 Professional' THEN 10 WHEN 'EB-3 Other Workers' THEN 11 ELSE 99 END
    """))
    premium_days = None
    if classification in {"EB-1C", "EB-2 NIW"}:
        premium_days = 45
    elif "(all)" not in classification:
        premium_days = 15
    return {
        "classification": classification,
        "classifications": [row["classification"] for row in classes],
        "points": [dict(row) for row in rows],
        "premium_processing_business_days": premium_days,
        "methodology": (
            "Quarterly receipts, approvals and denials are actions taken during the quarter; pending is inventory at quarter end. "
            "Decision shares use approvals divided by approvals plus denials and do not follow a single filing cohort."
        ),
    }


@router.get("/uscis/i140/history")
async def uscis_i140_history():
    rows = await database.fetch_all(text("""
        SELECT series_key, series_label, form_type, period_start, period_end,
               statistic, value::float8 AS value, unit, source_name, source_url
        FROM processing_time_observations
        WHERE agency='USCIS' AND form_type='I-140'
          AND metric_name='processing_time' AND period_granularity <> 'snapshot'
        ORDER BY period_start
    """))
    return [dict(row) for row in rows]


@router.get("/uscis/i129/current")
async def uscis_i129_current():
    rows = await database.fetch_all(text("""
        SELECT series_key, series_label, classification, office, period_start AS observed_on,
               statistic, value::float8 AS value, unit, source_name, source_url, metadata
        FROM processing_time_observations
        WHERE agency='USCIS' AND form_type='I-129' AND metric_name='processing_time'
          AND period_granularity='snapshot'
        ORDER BY series_label
    """))
    return [dict(row) for row in rows]


@router.get("/uscis/i129/context")
async def uscis_i129_context(
    classification: str = Query("H-1B"),
    metric: str = Query("rfe_rate", pattern="^(received|completed|approval_rate|denial_rate|rfe_rate)$"),
):
    source_metric = "approval_rate" if metric == "denial_rate" else metric
    rows = await database.fetch_all(text("""
        SELECT period_start, period_end, classification, metric_name,
               statistic, value::float8 AS value, unit, case_count,
               source_name, source_url
        FROM processing_time_observations
        WHERE agency='USCIS' AND form_type='I-129'
          AND classification=:classification AND metric_name=:metric
          AND period_granularity='month'
        ORDER BY period_start
    """).bindparams(classification=classification, metric=source_metric))
    classes = await database.fetch_all(text("""
        SELECT DISTINCT classification
        FROM processing_time_observations
        WHERE agency='USCIS' AND form_type='I-129'
          AND series_key LIKE 'uscis-i129-context:%'
        ORDER BY classification
    """))
    points = [dict(row) for row in rows]
    if metric == "denial_rate":
        for point in points:
            point["metric_name"] = "denial_rate"
            point["value"] = max(0.0, 1.0 - point["value"])
    return {
        "classification": classification, "metric": metric,
        "methodology": (
            "Denial rate is derived as 100% minus USCIS's published approval rate."
            if metric == "denial_rate" else None
        ),
        "classifications": [row["classification"] for row in classes],
        "points": points,
    }
