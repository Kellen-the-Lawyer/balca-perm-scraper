"""
EB Inventory API Router
========================
Three tiers of analysis based on backtest accuracy:

Tier 1 — Forecaster (Philippines + Mexico EB2/EB3: MAE ~1-2 months)
  GET /api/eb-inventory/forecast?country=Mexico&category=EB2

Tier 2 — Regime alert (all countries: MAE 2.4mo when eb2_ahead)
  GET /api/eb-inventory/regime?country=India&category=EB2

Tier 3 — Queue position (India/China + all non-EB2/3: no clearance date)
  GET /api/eb-inventory/queue-position?country=India&category=EB2&priority_year=2013

Supporting endpoints:
  GET /api/eb-inventory/snapshots           — all report_dates in DB
  GET /api/eb-inventory/inventory           — raw inventory for charting
  GET /api/eb-inventory/spread-history      — EB2 vs EB3 spread over time
"""
from datetime import date as _date
from typing import Optional
import math

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from core import *  # noqa

router = APIRouter()

# ---------------------------------------------------------------------------
# Country -> visa_bulletin chargeability mapping
# ---------------------------------------------------------------------------
COUNTRY_TO_VB = {
    "India":             "INDIA",
    "China":             "CHINA",
    "Mexico":            "MEXICO",
    "Philippines":       "PHILIPPINES",
    "Rest of the World": "ALL",
}

# Tier 1: high-accuracy forecaster countries x categories
TIER1_COMBOS = {
    ("Philippines", "EB3"), ("Philippines", "EB2"),
    ("Mexico",      "EB2"), ("Mexico",      "EB3"),
    ("Rest of the World", "EB3"),
}

EB_INDIA_MONTHLY_SUPPLY = 2803 / 12   # ~234/month
EB_OTHER_MONTHLY_SUPPLY = 2803 / 12   # conservative; others get more via spillover


# ---------------------------------------------------------------------------
# Helper: get current EB2/EB3 spread for a country
# ---------------------------------------------------------------------------
async def _get_spread(country: str) -> dict:
    chg = COUNTRY_TO_VB.get(country, country.upper())
    row = await database.fetch_one(text("""
        SELECT eb2.bulletin_date,
               eb2.priority_date AS eb2_cutoff,
               eb3.priority_date AS eb3_cutoff,
               (eb2.priority_date - eb3.priority_date) AS spread_days
        FROM visa_bulletin eb2
        JOIN visa_bulletin eb3
          ON eb3.bulletin_date  = eb2.bulletin_date
          AND eb3.preference    = 'EB3'
          AND eb3.chargeability = :chg
          AND eb3.date_type     = 'final_action'
          AND NOT eb3.is_unavailable
          AND eb3.priority_date IS NOT NULL
        WHERE eb2.preference    = 'EB2'
          AND eb2.chargeability = :chg
          AND eb2.date_type     = 'final_action'
          AND NOT eb2.is_unavailable
          AND eb2.priority_date IS NOT NULL
        ORDER BY eb2.bulletin_date DESC LIMIT 1
    """).bindparams(chg=chg))
    if not row:
        return {"spread_days": None, "regime": "unknown", "eb2_cutoff": None, "eb3_cutoff": None}
    sd = int(row["spread_days"]) if row["spread_days"] is not None else None
    regime = "near_parity"
    if sd is not None:
        if sd < -60:  regime = "eb3_ahead"
        elif sd > 60: regime = "eb2_ahead"
    return {
        "bulletin_date": row["bulletin_date"],
        "eb2_cutoff":    row["eb2_cutoff"],
        "eb3_cutoff":    row["eb3_cutoff"],
        "spread_days":   sd,
        "regime":        regime,
    }


# ---------------------------------------------------------------------------
# Helper: get latest inventory snapshot for a country x category
# ---------------------------------------------------------------------------
async def _get_latest_inventory(country: str, category: str) -> list[dict]:
    latest_date = await database.fetch_one(text("""
        SELECT MAX(report_date) AS rd FROM eb_inventory
        WHERE country = :country AND preference_category = :cat
    """).bindparams(country=country, cat=category))
    if not latest_date or not latest_date["rd"]:
        return []
    rows = await database.fetch_all(text("""
        SELECT priority_year, priority_month, pending_count, is_suppressed
        FROM eb_inventory
        WHERE country = :country AND preference_category = :cat
          AND report_date = :rd
          AND visa_status = 'Available'
          AND priority_year IS NOT NULL
        ORDER BY priority_year, priority_month
    """).bindparams(country=country, cat=category, rd=latest_date["rd"]))
    return [dict(r) for r in rows], latest_date["rd"]


# ---------------------------------------------------------------------------
# Helper: trailing 3-snapshot depletion rate for a priority_year
# ---------------------------------------------------------------------------
async def _get_depletion_rate(country: str, category: str,
                               priority_year: int) -> dict:
    rows = await database.fetch_all(text("""
        SELECT report_date,
               SUM(CASE WHEN NOT is_suppressed THEN pending_count ELSE 5 END) AS combined
        FROM eb_inventory
        WHERE country = :country AND preference_category = :cat
          AND priority_year = :py AND visa_status = 'Available'
          AND priority_month NOT IN ('Prior Years','nan')
        GROUP BY report_date ORDER BY report_date DESC LIMIT 4
    """).bindparams(country=country, cat=category, py=priority_year))
    if len(rows) < 2:
        return {"depletion_per_day": None, "pending_latest": None, "snapshots_used": 0}
    latest  = rows[0]
    oldest  = rows[-1]
    days    = (latest["report_date"] - oldest["report_date"]).days
    if days == 0:
        return {"depletion_per_day": None, "pending_latest": float(latest["combined"] or 0), "snapshots_used": len(rows)}
    rate = (float(latest["combined"] or 0) - float(oldest["combined"] or 0)) / days
    return {
        "depletion_per_day": round(rate, 3),
        "pending_latest":    round(float(latest["combined"] or 0)),
        "pending_oldest":    round(float(oldest["combined"] or 0)),
        "latest_snapshot":   latest["report_date"],
        "oldest_snapshot":   oldest["report_date"],
        "days_span":         days,
        "snapshots_used":    len(rows),
    }


# ---------------------------------------------------------------------------
# /api/eb-inventory/snapshots
# ---------------------------------------------------------------------------
@router.get("/api/eb-inventory/snapshots")
async def eb_inventory_snapshots():
    """All report dates in the eb_inventory table."""
    rows = await database.fetch_all(text("""
        SELECT report_date, COUNT(DISTINCT country) AS countries,
               COUNT(DISTINCT preference_category) AS categories,
               SUM(CASE WHEN NOT is_suppressed THEN pending_count ELSE 5 END) AS total_pending
        FROM eb_inventory
        GROUP BY report_date ORDER BY report_date DESC
    """))
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# /api/eb-inventory/inventory
# ---------------------------------------------------------------------------
@router.get("/api/eb-inventory/inventory")
async def eb_inventory_raw(
    country:  str           = Query(..., description="India, China, Mexico, Philippines, Rest of the World"),
    category: str           = Query(..., description="EB1, EB2, EB3, EB4, EB5, EW3, CRW"),
    from_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    to_date:   Optional[str] = Query(None, description="YYYY-MM-DD"),
):
    """
    Raw combined EB2+EB3 (or single category) pending counts over all snapshots.
    Useful for charting queue depth over time by priority year.
    """
    # For EB2/EB3 combine them; for others return single category
    if category in ("EB2", "EB3"):
        cats = ("EB2", "EB3")
    else:
        cats = (category,)

    clauses = ["country = :country", "preference_category = ANY(:cats)",
               "visa_status = 'Available'",
               "priority_year IS NOT NULL",
               "priority_month NOT IN ('Prior Years','nan')"]
    params: dict = {"country": country, "cats": list(cats)}

    if from_date:
        clauses.append("report_date >= :from_date"); params["from_date"] = from_date
    if to_date:
        clauses.append("report_date <= :to_date");   params["to_date"]   = to_date

    rows = await database.fetch_all(text(f"""
        SELECT report_date, priority_year,
               SUM(CASE WHEN NOT is_suppressed THEN pending_count ELSE 5 END) AS combined_pending,
               SUM(CASE WHEN is_suppressed THEN 1 ELSE 0 END) AS suppressed_cells,
               COUNT(*) AS total_cells
        FROM eb_inventory
        WHERE {" AND ".join(clauses)}
        GROUP BY report_date, priority_year
        ORDER BY priority_year, report_date
    """).bindparams(**params))

    return {
        "country":  country,
        "category": category,
        "combined": category in ("EB2", "EB3"),
        "rows":     [dict(r) for r in rows],
    }


# ---------------------------------------------------------------------------
# /api/eb-inventory/spread-history
# ---------------------------------------------------------------------------
@router.get("/api/eb-inventory/spread-history")
async def eb_spread_history(
    country: str = Query(..., description="India, China, Mexico, Philippines, Rest of the World"),
):
    """Monthly EB2 vs EB3 final_action cutoff spread for a country."""
    chg = COUNTRY_TO_VB.get(country, country.upper())
    rows = await database.fetch_all(text("""
        SELECT eb2.bulletin_date,
               eb2.priority_date  AS eb2_cutoff,
               eb3.priority_date  AS eb3_cutoff,
               (eb2.priority_date - eb3.priority_date) AS spread_interval
        FROM visa_bulletin eb2
        JOIN visa_bulletin eb3
          ON eb3.bulletin_date  = eb2.bulletin_date
         AND eb3.preference    = 'EB3'
         AND eb3.chargeability = :chg
         AND eb3.date_type     = 'final_action'
         AND NOT eb3.is_unavailable
         AND eb3.priority_date IS NOT NULL
        WHERE eb2.preference    = 'EB2'
          AND eb2.chargeability = :chg
          AND eb2.date_type     = 'final_action'
          AND NOT eb2.is_unavailable
          AND eb2.priority_date IS NOT NULL
        ORDER BY eb2.bulletin_date
    """).bindparams(chg=chg))
    result = []
    for r in rows:
        d = dict(r)
        d["spread_days"] = int(r["spread_interval"]) if r["spread_interval"] is not None else None
        del d["spread_interval"]
        result.append(d)
    return {"country": country, "chargeability": chg, "history": result}


# ---------------------------------------------------------------------------
# /api/eb-inventory/regime  (Tier 2)
# ---------------------------------------------------------------------------
@router.get("/api/eb-inventory/regime")
async def eb_regime(
    country:  str = Query(...),
    category: str = Query(...),
):
    """
    Tier 2: Current EB2/EB3 spread regime for any country x category.
    Reliable prediction when regime = 'eb2_ahead' (MAE ~2.4 months overall).
    """
    if category not in ("EB2", "EB3"):
        return {
            "country": country, "category": category,
            "regime": "n/a",
            "note": "Spread regime only applies to EB2/EB3 categories",
            "spread_days": None,
        }
    spread = await _get_spread(country)
    tier1 = (country, category) in TIER1_COMBOS
    return {
        "country":      country,
        "category":     category,
        "regime":       spread["regime"],
        "spread_days":  spread.get("spread_days"),
        "eb2_cutoff":   spread.get("eb2_cutoff"),
        "eb3_cutoff":   spread.get("eb3_cutoff"),
        "bulletin_date": spread.get("bulletin_date"),
        "tier1_forecaster_available": tier1,
        "regime_accuracy": {
            "eb2_ahead":   {"mae_months": 2.4, "within_6mo_pct": 91},
            "eb3_ahead":   {"mae_months": 19.7, "within_6mo_pct": 26},
            "near_parity": {"mae_months": 27.5, "within_6mo_pct": 18},
        }.get(spread["regime"]),
        "interpretation": {
            "eb2_ahead":   "EB2 cutoff is ahead of EB3 — downgrades reversing. Clearance predictions are reliable now.",
            "eb3_ahead":   "EB3 cutoff is ahead of EB2 — downgrade incentive active, inflating queue. Predictions unreliable.",
            "near_parity": "EB2 and EB3 cutoffs are close — transitional, monitor weekly.",
            "unknown":     "Spread data unavailable.",
        }.get(spread["regime"], ""),
    }


# ---------------------------------------------------------------------------
# /api/eb-inventory/forecast  (Tier 1)
# ---------------------------------------------------------------------------
@router.get("/api/eb-inventory/forecast")
async def eb_forecast(
    country:  str = Query(...),
    category: str = Query(...),
):
    """
    Tier 1: Priority date advancement forecast.
    Reliable only for: Philippines EB2/EB3, Mexico EB2/EB3, Rest of World EB3.
    Returns projected clearance dates for each active priority year.
    """
    if (country, category) not in TIER1_COMBOS:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "tier1_not_available",
                "message": f"{country} {category} is not a Tier 1 forecaster combination.",
                "tier1_combos": [f"{c} {cat}" for c, cat in sorted(TIER1_COMBOS)],
                "suggestion": "Use /api/eb-inventory/queue-position or /api/eb-inventory/regime instead.",
            }
        )

    spread = await _get_spread(country)
    regime = spread["regime"]
    monthly_supply = EB_OTHER_MONTHLY_SUPPLY

    # Get all active priority years in the latest snapshot
    latest_row = await database.fetch_one(text("""
        SELECT MAX(report_date) AS rd FROM eb_inventory
        WHERE country = :country AND preference_category = ANY(:cats)
    """).bindparams(country=country, cats=["EB2","EB3"] if category in ("EB2","EB3") else [category]))
    if not latest_row or not latest_row["rd"]:
        raise HTTPException(status_code=404, detail="No inventory data found")
    latest_date = latest_row["rd"]

    priority_years = await database.fetch_all(text("""
        SELECT DISTINCT priority_year FROM eb_inventory
        WHERE country = :country AND preference_category = ANY(:cats)
          AND report_date = :rd AND visa_status = 'Available'
          AND priority_year IS NOT NULL
          AND priority_month NOT IN ('Prior Years','nan')
        ORDER BY priority_year
    """).bindparams(country=country,
                    cats=["EB2","EB3"] if category in ("EB2","EB3") else [category],
                    rd=latest_date))

    forecasts = []
    for py_row in priority_years:
        py = py_row["priority_year"]
        dep = await _get_depletion_rate(country, category, py)
        pending  = dep.get("pending_latest") or 0
        rate     = dep.get("depletion_per_day")

        if pending <= 0:
            forecasts.append({"priority_year": py, "pending": 0,
                               "months_to_clear": None, "projected_clear_date": None,
                               "confidence": "cleared", "note": "Queue appears empty"})
            continue

        if rate is None:
            forecasts.append({"priority_year": py, "pending": pending,
                               "months_to_clear": None, "projected_clear_date": None,
                               "confidence": "insufficient_data", "note": "Need more snapshots"})
            continue

        # Regime adjustments (same logic as backtest v3)
        note = ""
        adj_pending = pending
        adj_rate    = rate
        if category in ("EB2","EB3"):
            if regime == "eb3_ahead":
                sd = spread.get("spread_days") or 0
                inf = min(0.40, abs(sd) / 900)
                adj_pending = pending * (1 - inf)
                note = f"Queue adjusted for EB3-ahead inflation ({inf:.0%} deflation)"
            elif regime == "eb2_ahead":
                month = latest_date.month
                fw = 1.2 if month in (10,11,12,1,2,3) else 0.8
                floor = -(monthly_supply * fw / 30.44)
                adj_rate = min(rate, floor)
                note = "Supply-floor rate applied (EB2-ahead regime)"

        if adj_rate >= 0:
            forecasts.append({"priority_year": py, "pending": pending,
                               "months_to_clear": None, "projected_clear_date": None,
                               "confidence": "queue_growing", "note": "Queue currently growing"})
            continue

        days   = adj_pending / abs(adj_rate)
        months = days / 30.44

        # Supply-side sanity
        min_mo = adj_pending / (monthly_supply * 1.5)
        if months < min_mo:
            months = min_mo
            days   = months * 30.44
            note  += " | supply-floor applied"

        from datetime import timedelta
        proj_date = latest_date + timedelta(days=days)

        # Confidence based on regime and pending
        if regime == "eb2_ahead" and pending < 500:
            confidence = "high"
        elif regime == "eb2_ahead":
            confidence = "medium"
        elif pending < 300 and rate < 0:
            confidence = "medium"
        else:
            confidence = "low"

        forecasts.append({
            "priority_year":        py,
            "pending":              round(pending),
            "adjusted_pending":     round(adj_pending),
            "depletion_per_day":    round(adj_rate, 2),
            "months_to_clear":      round(months, 1),
            "projected_clear_date": proj_date.isoformat(),
            "confidence":           confidence,
            "note":                 note.strip(" |"),
        })

    return {
        "country":          country,
        "category":         category,
        "snapshot_date":    latest_date.isoformat(),
        "regime":           regime,
        "spread_days":      spread.get("spread_days"),
        "eb2_cutoff":       spread.get("eb2_cutoff"),
        "eb3_cutoff":       spread.get("eb3_cutoff"),
        "backtest_accuracy": {"mae_months": {"Philippines EB3": 0.8, "Mexico EB2": 1.3,
                                              "Mexico EB3": 1.7, "Philippines EB2": 2.1,
                                              "Rest of the World EB3": 3.3}
                              .get(f"{country} {category}", "~2-4")},
        "forecasts":        forecasts,
    }


# ---------------------------------------------------------------------------
# /api/eb-inventory/queue-position  (Tier 3)
# ---------------------------------------------------------------------------
@router.get("/api/eb-inventory/queue-position")
async def eb_queue_position(
    country:       str = Query(...),
    category:      str = Query(...),
    priority_year: int = Query(...),
    priority_month: Optional[str] = Query(None, description="January, February... (optional, narrows to specific month)"),
):
    """
    Tier 3: Queue position — how many cases are ahead of a given priority date.
    Does NOT predict clearance date. Returns:
      - cases ahead of this priority_year (cumulative queue)
      - historical monthly advancement rate from visa bulletin
      - I-140 backlog for context (where available)
    """
    chg = COUNTRY_TO_VB.get(country, country.upper())

    # Latest snapshot date
    latest_row = await database.fetch_one(text("""
        SELECT MAX(report_date) AS rd FROM eb_inventory
        WHERE country = :country AND preference_category = :cat
    """).bindparams(country=country, cat=category))
    if not latest_row or not latest_row["rd"]:
        raise HTTPException(status_code=404, detail="No inventory data found")
    latest_date = latest_row["rd"]

    # Cases ahead = sum of all pending for priority_years BEFORE this one
    # (plus fraction of this year if month specified)
    cases_ahead = await database.fetch_one(text("""
        SELECT COALESCE(SUM(CASE WHEN NOT is_suppressed THEN pending_count ELSE 5 END), 0) AS ahead
        FROM eb_inventory
        WHERE country = :country AND preference_category = :cat
          AND report_date = :rd AND visa_status = 'Available'
          AND priority_year < :py
          AND priority_month NOT IN ('Prior Years','nan')
    """).bindparams(country=country, cat=category, rd=latest_date, py=priority_year))

    # Cases in this priority_year
    cases_this_year = await database.fetch_one(text("""
        SELECT COALESCE(SUM(CASE WHEN NOT is_suppressed THEN pending_count ELSE 5 END), 0) AS total,
               COUNT(*) AS months
        FROM eb_inventory
        WHERE country = :country AND preference_category = :cat
          AND report_date = :rd AND visa_status = 'Available'
          AND priority_year = :py
          AND priority_month NOT IN ('Prior Years','nan')
    """).bindparams(country=country, cat=category, rd=latest_date, py=priority_year))

    ahead = int(cases_ahead["ahead"] or 0)
    this_year_total = int(cases_this_year["total"] or 0)

    # If month specified, estimate fraction of this year ahead
    MONTH_ORDER = ["January","February","March","April","May","June",
                   "July","August","September","October","November","December"]
    if priority_month and priority_month in MONTH_ORDER:
        month_idx = MONTH_ORDER.index(priority_month)  # 0-based
        fraction_ahead = month_idx / 12
        ahead += round(this_year_total * fraction_ahead)

    # Historical visa bulletin advancement: avg monthly advance in days (last 24 months)
    vb_pref = category if category in ("EB1","EB2","EB3","EB4","EB5") else "EB3"
    history = await database.fetch_all(text("""
        SELECT bulletin_date, priority_date
        FROM visa_bulletin
        WHERE preference = :pref AND chargeability = :chg
          AND date_type = 'final_action'
          AND NOT is_unavailable AND NOT is_current
          AND priority_date IS NOT NULL
        ORDER BY bulletin_date DESC LIMIT 25
    """).bindparams(pref=vb_pref, chg=chg))

    avg_advance_days = None
    advance_history  = []
    if len(history) >= 2:
        moves = []
        for i in range(len(history) - 1):
            delta = (history[i]["priority_date"] - history[i+1]["priority_date"]).days
            moves.append(delta)
            advance_history.append({
                "bulletin_date": history[i]["bulletin_date"],
                "priority_date": history[i]["priority_date"],
                "advance_days":  delta,
            })
        valid = [m for m in moves if m > -365]  # exclude retrogressions > 1yr
        avg_advance_days = round(sum(valid) / len(valid), 1) if valid else None

    # Rough "years in queue" estimate from bulletin history (NOT a clearance date)
    est_months_in_queue = None
    est_years_in_queue  = None
    if avg_advance_days and avg_advance_days > 0 and ahead > 0:
        # How many months at avg pace to work through `ahead` cases?
        # Rough: ahead / (annual_supply / 12) gives months of supply consumption
        monthly_supply = EB_INDIA_MONTHLY_SUPPLY  # conservative floor
        est_months_in_queue = round(ahead / monthly_supply, 0)
        est_years_in_queue  = round(est_months_in_queue / 12, 1)

    # Current cutoff for context
    current_cutoff = await database.fetch_one(text("""
        SELECT bulletin_date, priority_date, is_unavailable
        FROM visa_bulletin
        WHERE preference = :pref AND chargeability = :chg
          AND date_type = 'final_action'
        ORDER BY bulletin_date DESC LIMIT 1
    """).bindparams(pref=vb_pref, chg=chg))

    return {
        "country":            country,
        "category":           category,
        "priority_year":      priority_year,
        "priority_month":     priority_month,
        "snapshot_date":      latest_date.isoformat(),

        # Queue position
        "cases_ahead":               ahead,
        "cases_in_priority_year":    this_year_total,
        "queue_position_note":       (
            "Approximate pending I-485 applications ahead of this priority date "
            "in USCIS inventory. Does not include I-140 holders who haven't yet filed I-485."
        ),

        # Current cutoff context
        "current_cutoff":     current_cutoff["priority_date"] if current_cutoff else None,
        "cutoff_unavailable": current_cutoff["is_unavailable"] if current_cutoff else None,
        "latest_bulletin":    current_cutoff["bulletin_date"] if current_cutoff else None,

        # Historical advancement
        "avg_monthly_advance_days":  avg_advance_days,
        "advance_history":           advance_history[:12],

        # Rough estimate (NOT a clearance date — labeled clearly)
        "est_months_processing_queue": est_months_in_queue,
        "est_years_processing_queue":  est_years_in_queue,
        "clearance_date_available":    False,
        "clearance_date_note": (
            "No reliable clearance date available for this combination. "
            "Priority date advancement for this category is controlled by DOS visa "
            "number management, not USCIS inventory levels."
            if (country, category) not in TIER1_COMBOS else None
        ),
    }
