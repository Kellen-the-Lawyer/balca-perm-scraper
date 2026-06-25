#!/usr/bin/env python3
"""
EB Inventory Backtest v2 — Combined EB2+EB3 with cutoff spread feature
========================================================================
Improvements over v1:
  1. Target variable: combined EB2+EB3 India pending per priority_year
     (eliminates the downgrade/upgrade noise that made EB2-only volatile)
  2. Cutoff spread feature: days between EB3 and EB2 final_action cutoffs
     - spread < 0 means EB3 is ahead -> expect combined queue to inflate
       as new downgrades file I-485; depletion rate is unreliable
     - spread > 0 means EB2 is ahead -> downgrades reversing, combined
       queue deflates rapidly; depletion rate understates true velocity
     - spread near 0 -> stable; depletion rate is most reliable
  3. Supply-side anchor: ~2,803 EB India visas/year (combined EB2+EB3)
     used to sanity-check projections that imply implausible clearance

Usage:
    env $(cat /tmp/uscis.env) python3 scripts/analysis/backtest_eb_inventory_v2.py
    env $(cat /tmp/uscis.env) python3 scripts/analysis/backtest_eb_inventory_v2.py --verbose
"""

import argparse
import logging
import os
from pathlib import Path

try:
    import pandas as pd
    import numpy as np
    import psycopg2
    import psycopg2.extras
    from dotenv import load_dotenv
except ImportError:
    import subprocess, sys
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

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

MONTH_TO_INT = {m: i+1 for i, m in enumerate([
    "January","February","March","April","May","June",
    "July","August","September","October","November","December"])}

# Annual EB India visa supply (EB2+EB3 combined, approximate)
# INA § 203(b): 40,040 EB visas/year, India capped at 7% = 2,803
# In practice, India gets more in high-demand years via spillover,
# but 2,803 is the floor and a reasonable anchor
EB_INDIA_ANNUAL_SUPPLY = 2803
EB_INDIA_MONTHLY_SUPPLY = EB_INDIA_ANNUAL_SUPPLY / 12  # ~234/month

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_combined_inventory(conn) -> pd.DataFrame:
    """
    Combined EB2+EB3 India pending by (report_date, priority_year).
    Suppressed cells imputed at 5 (midpoint of <10).
    """
    sql = """
        SELECT
            report_date,
            priority_year,
            SUM(CASE WHEN NOT is_suppressed THEN pending_count ELSE 5 END) AS combined_pending,
            SUM(pending_count) FILTER (WHERE NOT is_suppressed) AS known_pending,
            SUM(CASE WHEN is_suppressed THEN 1 ELSE 0 END) AS suppressed_cells,
            COUNT(*) AS total_cells
        FROM eb_inventory
        WHERE country = 'India'
          AND preference_category IN ('EB2','EB3')
          AND visa_status = 'Available'
          AND priority_year IS NOT NULL
          AND priority_month NOT IN ('Prior Years','nan')
        GROUP BY report_date, priority_year
        ORDER BY priority_year, report_date
    """
    df = pd.read_sql(sql, conn, parse_dates=["report_date"])
    df["priority_year"] = df["priority_year"].astype(int)
    return df


def load_visa_bulletins(conn) -> pd.DataFrame:
    """EB2 and EB3 India final_action dates."""
    sql = """
        SELECT bulletin_date, preference, priority_date, is_current, is_unavailable
        FROM visa_bulletin
        WHERE chargeability = 'INDIA'
          AND preference IN ('EB2','EB3')
          AND date_type = 'final_action'
        ORDER BY bulletin_date
    """
    df = pd.read_sql(sql, conn, parse_dates=["bulletin_date", "priority_date"])
    return df


def build_spread_series(vb: pd.DataFrame) -> pd.DataFrame:
    """
    For each bulletin_date where both EB2 and EB3 India have a cutoff,
    compute spread_days = eb2_cutoff - eb3_cutoff.
    Negative = EB3 is ahead (downgrade incentive exists).
    Positive = EB2 is ahead (upgrade back to EB2 incentive).
    """
    eb2 = vb[vb["preference"] == "EB2"].copy()
    eb3 = vb[vb["preference"] == "EB3"].copy()

    spread = eb2.merge(eb3, on="bulletin_date", suffixes=("_eb2","_eb3"))
    spread = spread[~spread["is_unavailable_eb2"] & ~spread["is_unavailable_eb3"]]
    spread = spread.dropna(subset=["priority_date_eb2","priority_date_eb3"])
    spread["spread_days"] = (spread["priority_date_eb2"] -
                              spread["priority_date_eb3"]).dt.days
    spread["eb2_cutoff_year"] = spread["priority_date_eb2"].dt.year
    return spread[["bulletin_date","priority_date_eb2","priority_date_eb3",
                   "spread_days","eb2_cutoff_year"]].sort_values("bulletin_date")


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------
def build_feature_table(inv: pd.DataFrame, spread: pd.DataFrame) -> pd.DataFrame:
    """
    For each (report_date, priority_year) observation, attach:
      - spread_days at the nearest prior bulletin
      - trailing 3-month depletion rate of the combined queue
      - spread_regime: 'eb3_ahead' / 'eb2_ahead' / 'near_parity'
    """
    inv = inv.copy().sort_values(["priority_year","report_date"])

    # Attach spread: for each report_date, find the most recent bulletin
    spread_s = spread.set_index("bulletin_date")["spread_days"].sort_index()

    def get_spread(dt):
        prior = spread_s[spread_s.index <= dt]
        return prior.iloc[-1] if not prior.empty else np.nan

    snap_dates = inv["report_date"].unique()
    spread_at_snap = {dt: get_spread(dt) for dt in snap_dates}
    inv["spread_days"] = inv["report_date"].map(spread_at_snap)

    inv["spread_regime"] = "near_parity"
    inv.loc[inv["spread_days"] < -60,  "spread_regime"] = "eb3_ahead"
    inv.loc[inv["spread_days"] >  60,  "spread_regime"] = "eb2_ahead"

    # Trailing depletion rate per priority_year: change over last 3 snapshots
    rows = []
    for py, grp in inv.groupby("priority_year"):
        grp = grp.sort_values("report_date").copy()
        grp["prev3_pending"] = grp["combined_pending"].shift(3)
        grp["prev3_date"]    = grp["report_date"].shift(3)
        grp["days_span"]     = (grp["report_date"] - grp["prev3_date"]).dt.days
        grp["net_change"]    = grp["combined_pending"] - grp["prev3_pending"]
        grp["depletion_per_day"] = grp["net_change"] / grp["days_span"]
        rows.append(grp)

    return pd.concat(rows, ignore_index=True)


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------
def project_clearance(features: pd.DataFrame,
                      snapshot_date: pd.Timestamp,
                      priority_year: int,
                      spread_days: float) -> dict:
    """
    At snapshot_date, project when priority_year's combined queue clears.

    Strategy:
      - If spread regime is near_parity: use trailing depletion rate directly
      - If eb3_ahead: depletion rate is artificially slow (new downgrades
        inflating queue); adjust by reducing pending by the estimated
        downgrade inflation factor
      - If eb2_ahead: depletion rate artificially fast (reversal underway);
        use supply-side floor instead
      - Supply-side sanity check: clearance can't be faster than
        pending / (monthly_supply * fiscal_year_weight)
    """
    snap = features[(features["report_date"] == snapshot_date) &
                    (features["priority_year"] == priority_year)]
    if snap.empty:
        return {}

    row = snap.iloc[0]
    pending     = row["combined_pending"]
    rate        = row["depletion_per_day"]     # cases/day, negative = shrinking
    regime      = row["spread_regime"]

    note = ""

    if pd.isna(rate) or pd.isna(pending) or pending <= 0:
        return {"priority_year": priority_year, "snapshot_date": snapshot_date,
                "pending": pending, "projected_clear_date": None,
                "months_to_clear": None, "regime": regime, "note": "insufficient data"}

    # Regime adjustment
    if regime == "eb3_ahead":
        # Queue is inflated by downgrades; true underlying queue is smaller.
        # Estimate: EB3 being ~4mo ahead historically adds ~30% inflation.
        # Use abs(spread_days)/365 as a scaling factor (rough).
        inflation = min(0.40, abs(spread_days) / 900)
        adjusted_pending = pending * (1 - inflation)
        note = f"eb3_ahead: pending adjusted {pending:.0f}->{adjusted_pending:.0f}"
        pending = adjusted_pending

    elif regime == "eb2_ahead":
        # Queue is deflating faster than the rate suggests because downgrades
        # are reversing. Use supply-side floor instead of observed rate.
        # Fiscal year weighting: Oct-Mar gets ~60% of annual supply
        month = snapshot_date.month
        fy_weight = 1.2 if month in (10,11,12,1,2,3) else 0.8
        supply_rate = (EB_INDIA_MONTHLY_SUPPLY * fy_weight) / 30.44  # per day
        rate = -max(abs(rate), supply_rate)  # use whichever is faster
        note = f"eb2_ahead: using supply-floor rate {rate:.2f}/day"

    if rate >= 0:
        return {"priority_year": priority_year, "snapshot_date": snapshot_date,
                "pending": pending, "projected_clear_date": None,
                "months_to_clear": None, "regime": regime,
                "note": "queue not shrinking"}

    days_to_clear   = pending / abs(rate)
    months_to_clear = days_to_clear / 30.44

    # Supply-side sanity check: can't clear faster than visa supply allows
    min_months = pending / (EB_INDIA_MONTHLY_SUPPLY * 1.5)  # 1.5x for spillover
    if months_to_clear < min_months:
        months_to_clear = min_months
        note += " | supply-floor applied"

    projected = snapshot_date + pd.Timedelta(days=days_to_clear)

    return {
        "priority_year":        priority_year,
        "snapshot_date":        snapshot_date,
        "pending":              round(pending),
        "depletion_per_day":    round(rate, 2),
        "spread_days":          spread_days,
        "regime":               regime,
        "months_to_clear":      round(months_to_clear, 1),
        "projected_clear_date": projected,
        "note":                 note,
    }


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------
def backtest(features: pd.DataFrame, vb: pd.DataFrame) -> pd.DataFrame:
    """
    For each snapshot x priority_year, project clearance and compare to
    the actual visa bulletin date when EB2 India final_action cutoff first
    reached that priority_year.
    """
    eb2_vb = (vb[(vb["preference"] == "EB2") & (~vb["is_unavailable"]) &
                 (vb["priority_date"].notna())]
              .sort_values("bulletin_date"))

    results = []
    snap_dates  = sorted(features["report_date"].unique())
    priority_yrs = sorted(features["priority_year"].unique())

    for snap in snap_dates:
        snap_spread = features[features["report_date"] == snap]["spread_days"].iloc[0] \
                      if not features[features["report_date"] == snap].empty else np.nan

        for py in priority_yrs:
            proj = project_clearance(features, snap, py, snap_spread)
            if not proj:
                continue

            # Actual: first bulletin AFTER snapshot where EB2 cutoff >= Jan 1 of priority_year
            year_start = pd.Timestamp(f"{py}-01-01")
            future = eb2_vb[(eb2_vb["bulletin_date"] > snap) &
                            (eb2_vb["priority_date"] >= year_start)]
            actual_clear = future["bulletin_date"].min() if not future.empty else pd.NaT

            proj_clear = proj.get("projected_clear_date")
            error_months = None
            if pd.notna(actual_clear) and proj_clear is not None and pd.notna(proj_clear):
                error_months = round((proj_clear - actual_clear).days / 30.44, 1)

            results.append({
                **proj,
                "actual_clear_date": actual_clear if pd.notna(actual_clear) else None,
                "error_months":      error_months,
                "abs_error_months":  abs(error_months) if error_months is not None else None,
            })

    return pd.DataFrame(results)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    out_dir = REPO_ROOT / "data" / "analysis"
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = psycopg2.connect(DB_URL)

    log.info("Loading combined EB2+EB3 India inventory...")
    inv = load_combined_inventory(conn)
    log.info(f"  {len(inv):,} (report_date, priority_year) observations")

    log.info("Loading visa bulletins...")
    vb = load_visa_bulletins(conn)
    log.info(f"  {len(vb):,} bulletin rows")

    log.info("Building spread series...")
    spread = build_spread_series(vb)
    log.info(f"  {len(spread)} months with EB2/EB3 spread data")
    log.info(f"  Spread range: {spread['spread_days'].min():.0f} to "
             f"{spread['spread_days'].max():.0f} days")

    log.info("Building feature table...")
    features = build_feature_table(inv, spread)

    log.info("Running backtest...")
    results = backtest(features, vb)

    results_path = out_dir / "eb_inventory_backtest_v2.csv"
    results.to_csv(results_path, index=False)
    log.info(f"Results -> {results_path}")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------
    scored = results.dropna(subset=["error_months","projected_clear_date",
                                    "actual_clear_date"])
    # Exclude priority years where queue is trivially empty
    scored = scored[scored["pending"] > 20]

    log.info("\n" + "=" * 65)
    log.info("BACKTEST v2 SUMMARY  (combined EB2+EB3, spread-adjusted)")
    log.info("=" * 65)

    if scored.empty:
        log.info("No scored predictions yet.")
    else:
        mae    = scored["abs_error_months"].mean()
        bias   = scored["error_months"].mean()
        median = scored["abs_error_months"].median()
        w3     = (scored["abs_error_months"] <= 3).mean()  * 100
        w6     = (scored["abs_error_months"] <= 6).mean()  * 100
        w12    = (scored["abs_error_months"] <= 12).mean() * 100

        log.info(f"  Scored predictions  : {len(scored)}")
        log.info(f"  Mean absolute error : {mae:.1f} months  (v1: 16.0)")
        log.info(f"  Median abs error    : {median:.1f} months  (v1:  9.1)")
        log.info(f"  Bias                : {bias:+.1f} months  (v1: +16.0)")
        log.info(f"  Within  3 months    : {w3:.0f}%  (v1:  8%)")
        log.info(f"  Within  6 months    : {w6:.0f}%  (v1: 27%)")
        log.info(f"  Within 12 months    : {w12:.0f}%  (v1: 62%)")

        log.info("\n  By regime:")
        for regime, grp in scored.groupby("regime"):
            log.info(f"    {regime:15s}  n={len(grp):3d}  "
                     f"MAE={grp['abs_error_months'].mean():.1f}mo  "
                     f"bias={grp['error_months'].mean():+.1f}mo  "
                     f"within6mo={( grp['abs_error_months']<=6).mean()*100:.0f}%")

        log.info("\n  By priority_year:")
        for py, grp in scored.groupby("priority_year"):
            log.info(f"    PY{py}  n={len(grp):3d}  "
                     f"MAE={grp['abs_error_months'].mean():.1f}mo  "
                     f"bias={grp['error_months'].mean():+.1f}mo")

    # Detail table for the key years
    log.info("\n" + "-" * 65)
    log.info("DETAIL: PY2011-2013 projections vs actuals")
    log.info("-" * 65)
    detail = results[results["priority_year"].between(2011, 2013)].copy()
    detail = detail.sort_values(["priority_year","snapshot_date"])
    cols = ["snapshot_date","priority_year","pending","regime",
            "months_to_clear","projected_clear_date","actual_clear_date","error_months"]
    if args.verbose:
        print("\n" + detail[cols].to_string(index=False))
    else:
        # Just the scored ones
        scored_detail = detail.dropna(subset=["error_months"])
        scored_detail = scored_detail[scored_detail["pending"] > 20]
        print("\n" + scored_detail[cols].to_string(index=False))

    # Show what the model says NOW about current frontier
    log.info("\n" + "-" * 65)
    log.info("CURRENT FORECAST (Apr 2026 snapshot)")
    log.info("-" * 65)
    latest = results[results["snapshot_date"] == results["snapshot_date"].max()].copy()
    latest = latest[latest["pending"] > 20].sort_values("priority_year")
    print("\n" + latest[["priority_year","pending","regime","spread_days",
                          "months_to_clear","projected_clear_date","note"]]
          .to_string(index=False))

    conn.close()


if __name__ == "__main__":
    main()
