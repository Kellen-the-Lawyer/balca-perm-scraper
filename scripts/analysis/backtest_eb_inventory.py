#!/usr/bin/env python3
"""
EB Inventory Priority Date Advancement Backtester
===================================================
Tests whether queue depletion rates from eb_inventory snapshots could have
predicted actual visa bulletin priority date cutoff movements.

Method:
  For each eb_inventory snapshot T and each (country, category, priority_year):
    1. Compute the depletion rate using the previous N snapshots
    2. Project when that priority_year's queue clears (-> becomes current)
    3. Compare against the actual visa bulletin where cutoff first reached
       that priority year

Output:
  data/analysis/eb_inventory_backtest.csv
  data/analysis/eb_inventory_depletion_rates.csv

Usage:
    env $(cat /tmp/uscis.env) venv/bin/python3 scripts/analysis/backtest_eb_inventory.py
    env $(cat /tmp/uscis.env) venv/bin/python3 scripts/analysis/backtest_eb_inventory.py \
        --country India --category EB2
"""

import argparse
import logging
import os
import sys
from pathlib import Path

try:
    import pandas as pd
    import numpy as np
    import psycopg2
    import psycopg2.extras
    from dotenv import load_dotenv
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet",
                           "pandas", "numpy", "psycopg2-binary", "python-dotenv"])
    import pandas as pd
    import numpy as np
    import psycopg2
    import psycopg2.extras
    from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_URL    = os.environ.get("DATABASE_URL",
                           "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

MONTH_TO_INT = {m: i+1 for i, m in enumerate([
    "January","February","March","April","May","June",
    "July","August","September","October","November","December"])}

VB_COUNTRY_MAP = {
    "India":             ["INDIA"],
    "China":             ["CHINA"],
    "Mexico":            ["MEXICO"],
    "Philippines":       ["PHILIPPINES"],
    "Rest of the World": ["ALL CHARGEABILITY AREAS EXCEPT THOSE LISTED",
                          "ALL CHARGEABILITY"],
}

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_eb_inventory(conn, country=None, category=None) -> pd.DataFrame:
    sql = """
        SELECT report_date, country, preference_category,
               visa_status, priority_month, priority_year,
               pending_count, is_suppressed
        FROM eb_inventory
        WHERE priority_year IS NOT NULL
          AND priority_month NOT IN ('Prior Years','nan')
          AND visa_status = 'Available'
          AND (%(country)s IS NULL OR country = %(country)s)
          AND (%(category)s IS NULL OR preference_category = %(category)s)
        ORDER BY country, preference_category, report_date, priority_year, priority_month
    """
    df = pd.read_sql(sql, conn, params={"country": country, "category": category},
                     parse_dates=["report_date"])
    df["priority_month_num"] = df["priority_month"].map(MONTH_TO_INT)
    df = df.dropna(subset=["priority_month_num"])
    df["priority_month_num"] = df["priority_month_num"].astype(int)
    df["priority_year"]      = df["priority_year"].astype(int)
    # Suppressed "D" values: impute 5 (midpoint of <10)
    df["pending_imputed"]    = df["pending_count"].fillna(5)
    return df


def load_visa_bulletins(conn) -> pd.DataFrame:
    sql = """
        SELECT bulletin_date, preference, chargeability,
               priority_date, is_current, is_unavailable
        FROM visa_bulletin
        WHERE date_type = 'final_action'
          AND category_type = 'employment'
          AND NOT is_unavailable
        ORDER BY bulletin_date
    """
    return pd.read_sql(sql, conn, parse_dates=["bulletin_date", "priority_date"])


# ---------------------------------------------------------------------------
# Depletion rate computation
# ---------------------------------------------------------------------------
def compute_depletion_rates(inv: pd.DataFrame) -> pd.DataFrame:
    """
    For each (country, category, priority_year, report_date), sum pending
    across all months in that year. Then compute month-over-month delta.
    """
    agg = (inv.groupby(["country", "preference_category", "priority_year", "report_date"])
             ["pending_imputed"].sum()
             .reset_index()
             .rename(columns={"pending_imputed": "total_pending"})
             .sort_values(["country", "preference_category", "priority_year", "report_date"]))

    grp_cols = ["country", "preference_category", "priority_year"]
    agg["prev_pending"] = agg.groupby(grp_cols)["total_pending"].shift(1)
    agg["prev_date"]    = agg.groupby(grp_cols)["report_date"].shift(1)
    agg["delta"]        = agg["total_pending"] - agg["prev_pending"]
    agg["days_elapsed"] = (agg["report_date"] - agg["prev_date"]).dt.days
    agg["depletion_per_day"] = agg["delta"] / agg["days_elapsed"]
    return agg.dropna(subset=["prev_pending"])


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------
def project_clearance(inv: pd.DataFrame,
                      snapshot_date: pd.Timestamp,
                      country: str, category: str,
                      lookback: int = 3) -> pd.DataFrame:
    """
    At snapshot_date, use the previous `lookback` snapshots to estimate
    depletion rate for each priority_year and project when it clears.
    """
    mask = ((inv["country"] == country) &
            (inv["preference_category"] == category) &
            (inv["report_date"] <= snapshot_date))
    past = inv[mask]

    snap_dates = sorted(past["report_date"].unique())
    if len(snap_dates) < 2:
        return pd.DataFrame()

    lookback_dates = snap_dates[-lookback:]
    recent = past[past["report_date"].isin(lookback_dates)]

    rows = []
    for py, grp in recent.groupby("priority_year"):
        grp = grp.sort_values("report_date")
        total_by_snap = grp.groupby("report_date")["pending_imputed"].sum()
        if len(total_by_snap) < 2:
            continue

        latest_date    = total_by_snap.index.max()
        earliest_date  = total_by_snap.index.min()
        pending_latest = total_by_snap[latest_date]
        pending_oldest = total_by_snap[earliest_date]
        days_span      = (latest_date - earliest_date).days

        if days_span == 0:
            continue

        net_change         = pending_latest - pending_oldest
        depletion_per_day  = net_change / days_span   # negative = shrinking

        if depletion_per_day >= 0 or pending_latest <= 0:
            projected_clear = None
            months_to_clear = None
        else:
            days_to_clear   = pending_latest / abs(depletion_per_day)
            months_to_clear = days_to_clear / 30.44
            projected_clear = snapshot_date + pd.Timedelta(days=days_to_clear)

        rows.append({
            "country":              country,
            "preference_category":  category,
            "snapshot_date":        snapshot_date,
            "priority_year":        int(py),
            "pending_at_snapshot":  pending_latest,
            "depletion_per_day":    depletion_per_day,
            "months_to_clear":      months_to_clear,
            "projected_clear_date": projected_clear,
        })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------
def backtest(inv: pd.DataFrame, vb: pd.DataFrame,
             country: str, category: str, lookback: int = 3) -> pd.DataFrame:

    vb_chars = VB_COUNTRY_MAP.get(country, [country.upper()])
    vb_sub = vb[(vb["preference"] == category) &
                (vb["chargeability"].isin(vb_chars)) &
                (vb["priority_date"].notna())].copy()
    vb_sub = vb_sub.sort_values("bulletin_date")

    snap_dates = sorted(inv[(inv["country"] == country) &
                            (inv["preference_category"] == category)]
                        ["report_date"].unique())

    all_proj = []
    for snap in snap_dates:
        p = project_clearance(inv, snap, country, category, lookback)
        if not p.empty:
            all_proj.append(p)

    if not all_proj:
        return pd.DataFrame()

    projections = pd.concat(all_proj, ignore_index=True)

    results = []
    for _, row in projections.iterrows():
        py   = int(row["priority_year"])
        snap = pd.Timestamp(row["snapshot_date"])
        proj = row["projected_clear_date"]

        # Actual: first bulletin AFTER this snapshot where cutoff >= Jan 1 of priority_year
        year_start = pd.Timestamp(f"{py}-01-01")
        future_vb  = vb_sub[(vb_sub["bulletin_date"] > snap) &
                            (vb_sub["priority_date"] >= year_start)]

        actual_clear = future_vb["bulletin_date"].min() if not future_vb.empty else None

        if proj is not None and actual_clear is not None:
            error_months = (proj - actual_clear).days / 30.44
        else:
            error_months = None

        results.append({
            "country":              country,
            "preference_category":  category,
            "snapshot_date":        snap.date(),
            "priority_year":        py,
            "pending_at_snapshot":  row["pending_at_snapshot"],
            "depletion_per_day":    round(row["depletion_per_day"], 2),
            "months_to_clear":      round(row["months_to_clear"], 1) if row["months_to_clear"] else None,
            "projected_clear_date": proj.date() if proj is not None else None,
            "actual_clear_date":    actual_clear.date() if actual_clear is not None else None,
            "error_months":         round(error_months, 1) if error_months is not None else None,
            "abs_error_months":     round(abs(error_months), 1) if error_months is not None else None,
        })

    return pd.DataFrame(results)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--country",  default=None)
    ap.add_argument("--category", default=None)
    ap.add_argument("--lookback", type=int, default=3)
    args = ap.parse_args()

    out_dir = REPO_ROOT / "data" / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = psycopg2.connect(DB_URL)

    log.info("Loading eb_inventory...")
    inv = load_eb_inventory(conn, args.country, args.category)
    log.info(f"  {len(inv):,} rows")

    log.info("Loading visa bulletins...")
    vb = load_visa_bulletins(conn)
    log.info(f"  {len(vb):,} bulletin rows")

    # Save depletion rates
    depletion = compute_depletion_rates(inv)
    dep_path  = out_dir / "eb_inventory_depletion_rates.csv"
    depletion.to_csv(dep_path, index=False)
    log.info(f"Depletion rates -> {dep_path}")

    # Run backtest for every country x category
    combos = inv.groupby(["country", "preference_category"]).size().reset_index()
    all_results = []
    for _, combo in combos.iterrows():
        c, cat = combo["country"], combo["preference_category"]
        log.info(f"  Backtesting {c} {cat}...")
        r = backtest(inv, vb, c, cat, args.lookback)
        if not r.empty:
            all_results.append(r)

    if not all_results:
        log.warning("No results produced.")
        conn.close()
        return

    results = pd.concat(all_results, ignore_index=True)
    results_path = out_dir / "eb_inventory_backtest.csv"
    results.to_csv(results_path, index=False)
    log.info(f"Full results -> {results_path}")

    # ---------------------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------------------
    scored = results.dropna(subset=["error_months", "projected_clear_date",
                                    "actual_clear_date"])

    log.info("\n" + "=" * 65)
    log.info("BACKTEST SUMMARY")
    log.info("=" * 65)

    if scored.empty:
        log.info("No completed projections yet — all projected dates may be future.")
    else:
        mae      = scored["abs_error_months"].mean()
        bias     = scored["error_months"].mean()
        median   = scored["abs_error_months"].median()
        w3       = (scored["abs_error_months"] <= 3).mean()  * 100
        w6       = (scored["abs_error_months"] <= 6).mean()  * 100
        w12      = (scored["abs_error_months"] <= 12).mean() * 100

        log.info(f"  Scored predictions  : {len(scored)}")
        log.info(f"  Mean absolute error : {mae:.1f} months")
        log.info(f"  Median abs error    : {median:.1f} months")
        log.info(f"  Bias (mean error)   : {bias:+.1f} months "
                 f"({'over' if bias > 0 else 'under'}estimates)")
        log.info(f"  Within  3 months    : {w3:.0f}%")
        log.info(f"  Within  6 months    : {w6:.0f}%")
        log.info(f"  Within 12 months    : {w12:.0f}%")

        log.info("\n  By country x category:")
        grp = (scored.groupby(["country","preference_category"])
               .agg(n=("abs_error_months","count"),
                    mae=("abs_error_months","mean"),
                    bias=("error_months","mean"),
                    w6=("abs_error_months", lambda x: (x<=6).mean()*100))
               .reset_index().sort_values("mae"))
        for _, r in grp.iterrows():
            log.info(f"    {r['country']:22s} {r['preference_category']:5s}  "
                     f"n={int(r['n']):3d}  MAE={r['mae']:5.1f}mo  "
                     f"bias={r['bias']:+5.1f}mo  within6mo={r['w6']:.0f}%")

    # India EB2 detail
    log.info("\n" + "-" * 65)
    log.info("INDIA EB2 detail (priority years 2011-2015)")
    log.info("-" * 65)
    detail = results[(results["country"] == "India") &
                     (results["preference_category"] == "EB2") &
                     (results["priority_year"].between(2011, 2015))].copy()
    detail = detail.sort_values(["priority_year", "snapshot_date"])
    if detail.empty:
        log.info("  (No India EB2 data — run without country/category filter)")
    else:
        cols = ["snapshot_date","priority_year","pending_at_snapshot",
                "months_to_clear","projected_clear_date",
                "actual_clear_date","error_months"]
        print("\n" + detail[cols].to_string(index=False))

    conn.close()


if __name__ == "__main__":
    main()
