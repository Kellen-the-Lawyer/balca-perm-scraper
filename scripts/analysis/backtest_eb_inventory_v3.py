#!/usr/bin/env python3
"""
EB Inventory Backtest v3 — All countries, all categories
=========================================================
Extends v2 to cover all 5 eb_inventory countries x all categories.

Key changes from v2:
  - Country->chargeability map covers all countries in eb_inventory
  - Spread computed per-country (each country has its own EB2/EB3 spread)
  - Categories other than EB2/EB3 don't have a downgrade/upgrade dynamic,
    so no spread adjustment for EB1, EB4, EB5, EW3, CRW
  - Results broken out by country x category

Usage:
    cd /Users/Dad/Documents/GitHub/Casebase
    env $(cat /tmp/uscis.env) venv/bin/python3 scripts/analysis/backtest_eb_inventory_v3.py
    env $(cat /tmp/uscis.env) venv/bin/python3 scripts/analysis/backtest_eb_inventory_v3.py --verbose
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

# eb_inventory country -> visa_bulletin chargeability
COUNTRY_TO_VB = {
    "India":             "INDIA",
    "China":             "CHINA",
    "Mexico":            "MEXICO",
    "Philippines":       "PHILIPPINES",
    "Rest of the World": "ALL",
}

# Only EB2+EB3 have the downgrade/upgrade dynamic
SPREAD_CATEGORIES = {"EB2", "EB3"}

# visa_bulletin preference -> eb_inventory preference_category
VB_PREF_TO_CAT = {
    "EB1": "EB1", "EB2": "EB2", "EB3": "EB3",
    "EW":  "EW3", "EB4": "EB4", "EB5": "EB5",
}

EB_MONTHLY_SUPPLY = 2803 / 12  # India floor; other countries have higher effective supply

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_inventory(conn) -> pd.DataFrame:
    sql = """
        SELECT report_date, country, preference_category,
               priority_month, priority_year,
               CASE WHEN NOT is_suppressed THEN pending_count ELSE 5 END AS pending_imputed,
               is_suppressed
        FROM eb_inventory
        WHERE visa_status = 'Available'
          AND priority_year IS NOT NULL
          AND priority_month NOT IN ('Prior Years','nan')
        ORDER BY country, preference_category, report_date, priority_year
    """
    df = pd.read_sql(sql, conn, parse_dates=["report_date"])
    df["priority_year"] = df["priority_year"].astype(int)
    return df


def load_bulletins(conn) -> pd.DataFrame:
    sql = """
        SELECT bulletin_date, preference, chargeability,
               priority_date, is_current, is_unavailable
        FROM visa_bulletin
        WHERE date_type = 'final_action'
          AND category_type = 'employment'
          AND preference IN ('EB1','EB2','EB3','EB4','EB5')
        ORDER BY bulletin_date
    """
    return pd.read_sql(sql, conn, parse_dates=["bulletin_date","priority_date"])


# ---------------------------------------------------------------------------
# Per-country EB2/EB3 spread series
# ---------------------------------------------------------------------------
def build_spreads(vb: pd.DataFrame) -> dict[str, pd.Series]:
    """Returns {country: Series(spread_days, index=bulletin_date)}"""
    spreads = {}
    for country, chg in COUNTRY_TO_VB.items():
        eb2 = vb[(vb["preference"] == "EB2") & (vb["chargeability"] == chg) &
                 (~vb["is_unavailable"]) & vb["priority_date"].notna()]
        eb3 = vb[(vb["preference"] == "EB3") & (vb["chargeability"] == chg) &
                 (~vb["is_unavailable"]) & vb["priority_date"].notna()]
        m = eb2.merge(eb3, on="bulletin_date", suffixes=("_eb2","_eb3"))
        m["spread_days"] = (m["priority_date_eb2"] - m["priority_date_eb3"]).dt.days
        s = m.set_index("bulletin_date")["spread_days"].sort_index()
        spreads[country] = s
    return spreads


# ---------------------------------------------------------------------------
# Feature table
# ---------------------------------------------------------------------------
def build_features(inv: pd.DataFrame, spreads: dict) -> pd.DataFrame:
    """Aggregate to (country, category, priority_year, report_date) and add spread + rate."""
    agg = (inv.groupby(["country","preference_category","priority_year","report_date"])
             ["pending_imputed"].sum()
             .reset_index()
             .rename(columns={"pending_imputed": "combined_pending"})
             .sort_values(["country","preference_category","priority_year","report_date"]))

    # Attach spread per country snapshot
    def get_spread(country, dt):
        s = spreads.get(country, pd.Series(dtype=float))
        prior = s[s.index <= dt]
        return float(prior.iloc[-1]) if not prior.empty else np.nan

    snap_spread_cache = {}
    def cached_spread(country, dt):
        key = (country, dt)
        if key not in snap_spread_cache:
            snap_spread_cache[key] = get_spread(country, dt)
        return snap_spread_cache[key]

    agg["spread_days"] = agg.apply(
        lambda r: cached_spread(r["country"], r["report_date"]), axis=1)

    # Regime: only meaningful for EB2/EB3
    agg["spread_regime"] = "n/a"
    is_spread_cat = agg["preference_category"].isin(SPREAD_CATEGORIES)
    agg.loc[is_spread_cat & (agg["spread_days"] < -60),  "spread_regime"] = "eb3_ahead"
    agg.loc[is_spread_cat & (agg["spread_days"] >  60),  "spread_regime"] = "eb2_ahead"
    agg.loc[is_spread_cat & (agg["spread_days"].between(-60, 60)), "spread_regime"] = "near_parity"

    # Trailing 3-snapshot depletion rate
    grp_cols = ["country","preference_category","priority_year"]
    agg = agg.sort_values(grp_cols + ["report_date"])
    agg["prev3_pending"] = agg.groupby(grp_cols)["combined_pending"].shift(3)
    agg["prev3_date"]    = agg.groupby(grp_cols)["report_date"].shift(3)
    agg["days_span"]     = (agg["report_date"] - agg["prev3_date"]).dt.days
    agg["net_change"]    = agg["combined_pending"] - agg["prev3_pending"]
    agg["depletion_per_day"] = np.where(
        agg["days_span"] > 0, agg["net_change"] / agg["days_span"], np.nan)

    return agg


# ---------------------------------------------------------------------------
# Projection
# ---------------------------------------------------------------------------
def project(row: pd.Series) -> tuple[float | None, pd.Timestamp | None, str]:
    """
    Given a feature row, return (months_to_clear, projected_date, note).
    """
    pending = row["combined_pending"]
    rate    = row["depletion_per_day"]
    regime  = row["spread_regime"]
    spread  = row["spread_days"]
    snap    = row["report_date"]
    cat     = row["preference_category"]

    if pd.isna(pending) or pending <= 0:
        return None, None, "zero pending"
    if pd.isna(rate):
        return None, None, "insufficient history"

    note = ""

    if cat in SPREAD_CATEGORIES:
        if regime == "eb3_ahead":
            inflation = min(0.40, abs(spread) / 900) if not pd.isna(spread) else 0.20
            pending   = pending * (1 - inflation)
            note      = f"eb3_ahead: pending deflated by {inflation:.0%}"
        elif regime == "eb2_ahead":
            month = snap.month
            fy_weight  = 1.2 if month in (10,11,12,1,2,3) else 0.8
            floor_rate = -(EB_MONTHLY_SUPPLY * fy_weight / 30.44)
            rate       = min(rate, floor_rate)   # more negative = faster
            note       = f"eb2_ahead: supply-floor rate applied"

    if rate >= 0:
        return None, None, "queue not shrinking"

    days = pending / abs(rate)
    mo   = days / 30.44
    proj = snap + pd.Timedelta(days=days)

    # Supply-side sanity: can't clear faster than monthly_supply allows
    min_mo = pending / (EB_MONTHLY_SUPPLY * 1.5)
    if mo < min_mo:
        mo   = min_mo
        proj = snap + pd.Timedelta(days=mo * 30.44)
        note += " | supply-floor applied"

    return round(mo, 1), proj, note.strip()


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------
def run_backtest(features: pd.DataFrame, vb: pd.DataFrame) -> pd.DataFrame:
    results = []

    for (country, cat), grp in features.groupby(["country","preference_category"]):
        chg = COUNTRY_TO_VB.get(country, country.upper())
        # Map category to vb preference (EB1/EB2/EB3/EB4/EB5)
        vb_pref = cat if cat in ("EB1","EB2","EB3","EB4","EB5") else None
        if not vb_pref:
            # EW3, CRW map to EB3/EB4 for vb lookup — use EB3 as proxy
            vb_pref = "EB3" if cat == "EW3" else "EB4"

        vb_sub = vb[(vb["preference"] == vb_pref) &
                    (vb["chargeability"] == chg) &
                    (~vb["is_unavailable"]) &
                    (vb["priority_date"].notna())].sort_values("bulletin_date")

        if vb_sub.empty:
            # Fallback: try ALL chargeability (Rest of the World uses ALL)
            vb_sub = vb[(vb["preference"] == vb_pref) &
                        (vb["chargeability"] == "ALL") &
                        (~vb["is_unavailable"]) &
                        (vb["priority_date"].notna())].sort_values("bulletin_date")

        for _, row in grp.iterrows():
            snap = row["report_date"]
            py   = int(row["priority_year"])

            mo, proj, note = project(row)

            # Actual: first bulletin after snap where cutoff >= Jan 1 of priority_year
            year_start = pd.Timestamp(f"{py}-01-01")
            future = vb_sub[(vb_sub["bulletin_date"] > snap) &
                            (vb_sub["priority_date"] >= year_start)]
            actual = future["bulletin_date"].min() if not future.empty else pd.NaT

            error = None
            if proj is not None and pd.notna(actual):
                error = round((proj - actual).days / 30.44, 1)

            results.append({
                "country":              country,
                "preference_category":  cat,
                "snapshot_date":        snap.date(),
                "priority_year":        py,
                "pending":              round(row["combined_pending"]),
                "spread_days":          round(row["spread_days"]) if not pd.isna(row["spread_days"]) else None,
                "regime":               row["spread_regime"],
                "depletion_per_day":    round(row["depletion_per_day"], 2) if not pd.isna(row["depletion_per_day"]) else None,
                "months_to_clear":      mo,
                "projected_clear_date": proj.date() if proj is not None else None,
                "actual_clear_date":    actual.date() if pd.notna(actual) else None,
                "error_months":         error,
                "abs_error_months":     abs(error) if error is not None else None,
                "note":                 note,
            })

    return pd.DataFrame(results)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
def summarize(results: pd.DataFrame, verbose: bool = False):
    scored = results[
        results["error_months"].notna() &
        results["projected_clear_date"].notna() &
        results["actual_clear_date"].notna() &
        (results["pending"] > 20)
    ].copy()

    log.info("\n" + "=" * 70)
    log.info("BACKTEST v3 — ALL COUNTRIES / ALL CATEGORIES")
    log.info("=" * 70)
    log.info(f"  Total predictions       : {len(results):,}")
    log.info(f"  Scored (both dates known): {len(scored):,}")

    if scored.empty:
        log.info("  No scored predictions.")
        return

    mae    = scored["abs_error_months"].mean()
    bias   = scored["error_months"].mean()
    median = scored["abs_error_months"].median()
    w3     = (scored["abs_error_months"] <= 3).mean()  * 100
    w6     = (scored["abs_error_months"] <= 6).mean()  * 100
    w12    = (scored["abs_error_months"] <= 12).mean() * 100

    log.info(f"\n  OVERALL")
    log.info(f"  Mean absolute error     : {mae:.1f} months")
    log.info(f"  Median absolute error   : {median:.1f} months")
    log.info(f"  Bias                    : {bias:+.1f} months")
    log.info(f"  Within  3 months        : {w3:.0f}%")
    log.info(f"  Within  6 months        : {w6:.0f}%")
    log.info(f"  Within 12 months        : {w12:.0f}%")

    log.info(f"\n  BY COUNTRY x CATEGORY (sorted by MAE)")
    summary_df = (scored.groupby(["country","preference_category"])
           .agg(n=("abs_error_months","count"),
                mae=("abs_error_months","mean"),
                median=("abs_error_months","median"),
                bias=("error_months","mean"),
                w3=("abs_error_months", lambda x: (x<=3).mean()*100),
                w6=("abs_error_months", lambda x: (x<=6).mean()*100),
                w12=("abs_error_months",lambda x: (x<=12).mean()*100))
           .reset_index()
           .sort_values("mae"))
    for _, r in summary_df.iterrows():
        log.info(f"  {r['country']:22s} {r['preference_category']:5s}  "
                 f"n={int(r['n']):3d}  "
                 f"MAE={r['mae']:5.1f}mo  "
                 f"median={r['median']:5.1f}mo  "
                 f"bias={r['bias']:+5.1f}mo  "
                 f"w3={r['w3']:.0f}%  w6={r['w6']:.0f}%  w12={r['w12']:.0f}%")

    log.info(f"\n  BY REGIME")
    for regime, grp in scored.groupby("regime"):
        log.info(f"  {regime:15s}  n={len(grp):3d}  "
                 f"MAE={grp['abs_error_months'].mean():.1f}mo  "
                 f"bias={grp['error_months'].mean():+.1f}mo  "
                 f"w6={(grp['abs_error_months']<=6).mean()*100:.0f}%")

    if verbose:
        log.info(f"\n  BY PRIORITY YEAR (all countries combined)")
        for py, grp in scored.groupby("priority_year"):
            log.info(f"  PY{py}  n={len(grp):3d}  "
                     f"MAE={grp['abs_error_months'].mean():.1f}mo  "
                     f"bias={grp['error_months'].mean():+.1f}mo")

    # Highlight the best-performing country x category combos
    log.info(f"\n  BEST PERFORMERS (MAE <= 6 months, n >= 5)")
    best = summary_df[summary_df["mae"] <= 6].copy() if not summary_df.empty else pd.DataFrame()
    if best.empty:
        log.info("  None meeting criteria.")
    else:
        for _, r in best.iterrows():
            if r["n"] >= 5:
                log.info(f"  *** {r['country']} {r['preference_category']}  "
                         f"MAE={r['mae']:.1f}mo  within6mo={r['w6']:.0f}%")


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

    log.info("Loading eb_inventory (all countries)...")
    inv = load_inventory(conn)
    log.info(f"  {len(inv):,} rows, {inv['country'].nunique()} countries, "
             f"{inv['preference_category'].nunique()} categories")

    log.info("Loading visa bulletins...")
    vb = load_bulletins(conn)
    log.info(f"  {len(vb):,} rows")

    log.info("Building per-country EB2/EB3 spreads...")
    spreads = build_spreads(vb)
    for country, s in spreads.items():
        log.info(f"  {country:22s}: {len(s)} months, "
                 f"range {s.min():.0f} to {s.max():.0f} days")

    log.info("Building feature table...")
    features = build_features(inv, spreads)
    log.info(f"  {len(features):,} feature rows")

    log.info("Running backtest...")
    results = run_backtest(features, vb)

    path = out_dir / "eb_inventory_backtest_v3.csv"
    results.to_csv(path, index=False)
    log.info(f"Results -> {path}")

    summarize(results, args.verbose)
    conn.close()


if __name__ == "__main__":
    main()
