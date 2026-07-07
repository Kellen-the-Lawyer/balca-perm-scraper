"""
Wages: July 1 Wage Comparer dashboard endpoints.
Serves year-over-year OFLC prevailing-wage comparisons
(current_oews_wages 2026-27 vs prior_oews_wages 2025-26) plus
H-1B filing heat-map data from oflc_lca.

Heavy year-over-year math is precomputed in materialized views
(scripts/sql/wage_matviews.sql): mv_wage_yoy, mv_lca_soc_filings,
mv_soc_titles. Refresh those after re-ingesting OFLC data.
"""
from typing import Optional

from fastapi import APIRouter, Query
from sqlalchemy import text

from core import *  # noqa: F401,F403 -- shared db (database), config, helpers

router = APIRouter()


# ── Heat map: certified H-1B filings by state ────────────────────────────────
@router.get("/api/wages/heatmap/states")
async def wages_heatmap_states():
    rows = await database.fetch_all(text("""
        SELECT worksite_state AS state, COUNT(*) AS filings
        FROM oflc_lca
        WHERE visa_class = 'H-1B'
          AND worksite_state IS NOT NULL
          AND case_status = 'Certified'
        GROUP BY worksite_state
        ORDER BY filings DESC
    """))
    return [{"state": r["state"], "filings": r["filings"]} for r in rows]


# ── Top areas by filing volume ────────────────────────────────────────────────
@router.get("/api/wages/heatmap/areas")
async def wages_heatmap_areas():
    rows = await database.fetch_all(text("""
        SELECT worksite_city AS city, worksite_state AS state, COUNT(*) AS filings
        FROM oflc_lca
        WHERE visa_class = 'H-1B'
          AND worksite_city IS NOT NULL
          AND case_status = 'Certified'
        GROUP BY worksite_city, worksite_state
        ORDER BY filings DESC
        LIMIT 50
    """))
    return [{"city": r["city"], "state": r["state"], "filings": r["filings"]}
            for r in rows]


# ── Wage comparison for one area: top 10 H-1B SOCs, old vs new ────────────────
# top_socs is restricted to SOC codes that exist in the 2026-27 wage data so
# retired 2010-vintage codes (e.g. 15-1132) never occupy a slot.
@router.get("/api/wages/compare/area/{area_code}")
async def wages_compare_area(area_code: str,
                             collection_type: str = Query("alc")):
    rows = await database.fetch_all(text("""
        WITH top_socs AS (
            SELECT f.soc_base, f.filings
            FROM mv_lca_soc_filings f
            JOIN mv_soc_titles t ON t.soc_code = f.soc_base
            ORDER BY f.filings DESC
            LIMIT 10
        ),
        cur AS (
            SELECT DISTINCT ON (soc_code)
                   soc_code, soc_title, area_name,
                   level_i, level_ii, level_iii, level_iv
            FROM current_oews_wages
            WHERE area_code = :area_code AND collection_type = :ctype
            ORDER BY soc_code, county_name
        ),
        pri AS (
            SELECT DISTINCT ON (soc_code)
                   soc_code,
                   level_i AS p_i, level_ii AS p_ii,
                   level_iii AS p_iii, level_iv AS p_iv
            FROM prior_oews_wages
            WHERE area_code = :area_code AND collection_type = :ctype
            ORDER BY soc_code, county_name
        )
        SELECT t.soc_base, t.filings,
               c.soc_title, c.area_name,
               c.level_i, c.level_ii, c.level_iii, c.level_iv,
               p.p_i, p.p_ii, p.p_iii, p.p_iv
        FROM top_socs t
        JOIN cur c ON c.soc_code = t.soc_base
        LEFT JOIN pri p ON p.soc_code = t.soc_base
        ORDER BY t.filings DESC
    """).bindparams(area_code=area_code, ctype=collection_type))

    def pct_chg(new, old):
        if new is not None and old not in (None, 0):
            return round((float(new) - float(old)) / float(old) * 100, 1)
        return None

    def f(v):
        return float(v) if v is not None else None

    result = []
    for r in rows:
        result.append({
            "soc_code":    r["soc_base"],
            "soc_title":   r["soc_title"],
            "area_name":   r["area_name"],
            "h1b_filings": r["filings"],
            "cur":   {"I": f(r["level_i"]),  "II": f(r["level_ii"]),
                      "III": f(r["level_iii"]), "IV": f(r["level_iv"])},
            "prior": {"I": f(r["p_i"]),      "II": f(r["p_ii"]),
                      "III": f(r["p_iii"]),    "IV": f(r["p_iv"])},
            "change_pct": {
                "I":   pct_chg(r["level_i"],   r["p_i"]),
                "II":  pct_chg(r["level_ii"],  r["p_ii"]),
                "III": pct_chg(r["level_iii"], r["p_iii"]),
                "IV":  pct_chg(r["level_iv"],  r["p_iv"]),
            },
        })
    return result


# ── Summary stats for header cards ────────────────────────────────────────────
@router.get("/api/wages/summary")
async def wages_summary():
    row = await database.fetch_one(text("""
        SELECT
            COUNT(*) FILTER (WHERE chg < 0)              AS decreased,
            COUNT(*) FILTER (WHERE chg > 5)              AS big_increase,
            COUNT(*) FILTER (WHERE chg BETWEEN 0 AND 5)  AS modest_increase,
            ROUND(AVG(chg)::numeric, 2)                  AS avg_change,
            ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY chg)::numeric, 2) AS median_change
        FROM mv_wage_yoy
    """))
    return {
        "decreased":       row["decreased"],
        "big_increase":    row["big_increase"],
        "modest_increase": row["modest_increase"],
        "avg_change":      float(row["avg_change"])    if row["avg_change"]    is not None else None,
        "median_change":   float(row["median_change"]) if row["median_change"] is not None else None,
    }


# ── Biggest movers: SOCs with largest avg Level I change ──────────────────────
@router.get("/api/wages/movers")
async def wages_movers(direction: str = Query("up"),
                       limit: int = Query(10)):
    sign = "DESC" if direction == "up" else "ASC"
    rows = await database.fetch_all(text(f"""
        SELECT soc_code, soc_title,
               ROUND(AVG(chg)::numeric, 1) AS avg_chg,
               COUNT(DISTINCT area_code) AS areas
        FROM mv_wage_yoy
        GROUP BY soc_code, soc_title
        HAVING COUNT(DISTINCT area_code) >= 20
        ORDER BY AVG(chg) {sign}
        LIMIT :lim
    """).bindparams(lim=limit))
    return [{"soc_code": r["soc_code"], "soc_title": r["soc_title"],
             "avg_change_pct": float(r["avg_chg"]), "areas": r["areas"]}
            for r in rows]


# ── Employer exposure: Level I concentration for top filers ───────────────────
@router.get("/api/wages/employer-exposure")
async def wages_employer_exposure(limit: int = Query(15)):
    rows = await database.fetch_all(text("""
        SELECT employer_name,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE pw_wage_level = 'I')  AS level_i_count,
               COUNT(*) FILTER (WHERE pw_wage_level = 'II') AS level_ii_count,
               COUNT(*) FILTER (WHERE pw_wage_level IN ('III','IV')) AS level_iii_iv_count,
               ROUND(AVG(CASE WHEN wage_unit='Year' THEN wage_from
                              WHEN wage_unit='Hour' THEN wage_from * 2080
                              ELSE NULL END)::numeric / 1000, 0) AS avg_wage_k
        FROM oflc_lca
        WHERE visa_class = 'H-1B'
          AND case_status = 'Certified'
          AND employer_name IS NOT NULL
        GROUP BY employer_name
        ORDER BY total DESC
        LIMIT :lim
    """).bindparams(lim=limit))
    return [{
        "employer":     r["employer_name"],
        "total":        r["total"],
        "level_i":      r["level_i_count"],
        "level_ii":     r["level_ii_count"],
        "level_iii_iv": r["level_iii_iv_count"],
        "avg_wage_k":   float(r["avg_wage_k"]) if r["avg_wage_k"] is not None else None,
        "pct_level_i":  round(r["level_i_count"] / r["total"] * 100, 1) if r["total"] else 0,
    } for r in rows]


# ── Area lookup: city names → area codes for a state ──────────────────────────
@router.get("/api/wages/areas")
async def wages_areas(state: Optional[str] = Query(None)):
    where = "WHERE collection_type='alc' AND area_name NOT ILIKE '%nonmetropolitan%'"
    params = {}
    if state:
        where += " AND state_ab = :state"
        params["state"] = state.upper()
    rows = await database.fetch_all(text(f"""
        SELECT DISTINCT area_code, area_name, state_ab
        FROM current_oews_wages
        {where}
        ORDER BY state_ab, area_name
    """).bindparams(**params))
    return [{"code": r["area_code"], "name": r["area_name"], "state": r["state_ab"]}
            for r in rows]


# ── SOC search: autocomplete for the SOC Explorer ─────────────────────────────
@router.get("/api/wages/soc-search")
async def wages_soc_search(q: str = Query(..., min_length=2)):
    rows = await database.fetch_all(text("""
        SELECT soc_code, soc_title
        FROM mv_soc_titles
        WHERE soc_code ILIKE :pat OR soc_title ILIKE :pat
        ORDER BY soc_code
        LIMIT 12
    """).bindparams(pat=f"%{q}%"))
    return [{"soc_code": r["soc_code"], "soc_title": r["soc_title"]} for r in rows]


# ── Per-SOC area movers: top gains and top reductions for one occupation ─────
# Returns up to `limit` largest increases and `limit` largest decreases,
# each tagged with direction; gains first (desc), then reductions (asc).
@router.get("/api/wages/soc/{soc_code}/areas")
async def wages_soc_areas(soc_code: str, limit: int = Query(20)):
    rows = await database.fetch_all(text("""
        WITH base AS (
            SELECT area_code, area_name, state_ab, soc_title,
                   cur_i, prior_i, ROUND(chg::numeric, 1) AS chg
            FROM mv_wage_yoy
            WHERE soc_code = :soc
              AND area_name NOT ILIKE '%nonmetropolitan%'
        ),
        gains AS (
            SELECT *, 'gain' AS direction FROM base
            WHERE chg > 0 ORDER BY chg DESC LIMIT :lim
        ),
        cuts AS (
            SELECT *, 'reduction' AS direction FROM base
            WHERE chg < 0 ORDER BY chg ASC LIMIT :lim
        )
        SELECT * FROM (
            SELECT * FROM gains
            UNION ALL
            SELECT * FROM cuts
        ) u
        ORDER BY direction, ABS(chg) DESC
    """).bindparams(soc=soc_code, lim=limit))
    return [{
        "area_code": r["area_code"], "area_name": r["area_name"],
        "state": r["state_ab"], "soc_title": r["soc_title"],
        "direction": r["direction"],
        "cur_annual":   round(float(r["cur_i"]) * 2080),
        "prior_annual": round(float(r["prior_i"]) * 2080),
        "change_pct":   float(r["chg"]),
    } for r in rows]


# ── SOC × Metro matrix: top occupations × top metros, Level I change ──────────
# Only SOC codes present in 2026-27 wage data are eligible for the matrix.
@router.get("/api/wages/matrix")
async def wages_matrix(n_socs: int = Query(14), n_areas: int = Query(12)):
    rows = await database.fetch_all(text("""
        WITH top_socs AS (
            SELECT f.soc_base, f.filings, t.soc_title
            FROM mv_lca_soc_filings f
            JOIN mv_soc_titles t ON t.soc_code = f.soc_base
            ORDER BY f.filings DESC
            LIMIT :n_socs
        ),
        top_cities AS (
            SELECT worksite_city AS city, worksite_state AS st, COUNT(*) AS f
            FROM oflc_lca
            WHERE visa_class = 'H-1B' AND case_status = 'Certified'
              AND worksite_city IS NOT NULL
            GROUP BY city, st
            ORDER BY f DESC
            LIMIT 40
        ),
        metro_areas AS MATERIALIZED (
            SELECT DISTINCT ON (area_code) area_code, area_name, state_ab
            FROM mv_wage_yoy
            WHERE area_name NOT ILIKE '%nonmetropolitan%'
            ORDER BY area_code
        ),
        city_area AS (
            SELECT DISTINCT ON (a.area_code) a.area_code, a.area_name, SUM(tc.f) AS filings
            FROM top_cities tc
            CROSS JOIN LATERAL (
                SELECT area_code, area_name
                FROM metro_areas
                WHERE state_ab = tc.st
                  AND area_name ILIKE tc.city || '%'
                LIMIT 1
            ) a
            GROUP BY a.area_code, a.area_name
        ),
        top_areas AS (
            SELECT area_code, area_name
            FROM city_area
            ORDER BY filings DESC
            LIMIT :n_areas
        )
        SELECT ts.soc_base AS soc_code, ts.soc_title, ts.filings,
               ta.area_code, ta.area_name,
               m.cur_i, m.prior_i,
               ROUND(m.chg::numeric, 1) AS chg
        FROM top_socs ts
        CROSS JOIN top_areas ta
        LEFT JOIN mv_wage_yoy m
               ON m.soc_code = ts.soc_base AND m.area_code = ta.area_code
        ORDER BY ts.filings DESC, ta.area_name
    """).bindparams(n_socs=n_socs, n_areas=n_areas))

    # Pivot into rows=SOCs, cols=areas
    socs, areas, cells = {}, {}, {}
    for r in rows:
        sc = r["soc_code"]
        if sc not in socs:
            socs[sc] = {"soc_code": sc, "soc_title": r["soc_title"], "filings": r["filings"]}
        ac = r["area_code"]
        if ac not in areas:
            areas[ac] = {"area_code": ac, "area_name": r["area_name"]}
        chg = r["chg"]
        cells[f"{sc}|{ac}"] = {
            "change_pct": float(chg) if chg is not None else None,
            "cur_annual":   round(float(r["cur_i"]) * 2080)   if r["cur_i"]   is not None else None,
            "prior_annual": round(float(r["prior_i"]) * 2080) if r["prior_i"] is not None else None,
        }
    return {"socs": list(socs.values()), "areas": list(areas.values()), "cells": cells}


# ── Treemap drilldown: major group → detailed SOC → metro ────────────────────
SOC_MAJOR_GROUPS = {
    "11": "Management",
    "13": "Business & Financial Ops",
    "15": "Computer & Mathematical",
    "17": "Architecture & Engineering",
    "19": "Life, Physical & Social Science",
    "21": "Community & Social Service",
    "23": "Legal",
    "25": "Education & Library",
    "27": "Arts, Design & Media",
    "29": "Healthcare Practitioners",
    "31": "Healthcare Support",
    "33": "Protective Service",
    "35": "Food Prep & Serving",
    "37": "Building & Grounds Maintenance",
    "39": "Personal Care & Service",
    "41": "Sales & Related",
    "43": "Office & Admin Support",
    "45": "Farming, Fishing & Forestry",
    "47": "Construction & Extraction",
    "49": "Installation & Repair",
    "51": "Production",
    "53": "Transportation & Material Moving",
}


@router.get("/api/wages/treemap")
async def wages_treemap(group: Optional[str] = Query(None),
                        soc: Optional[str] = Query(None)):
    """Hierarchy drilldown. No params: 22 major groups.
    group=NN: detailed SOCs in that major group.
    soc=NN-NNNN: metros for that occupation.
    Tiles sized by certified H-1B filings (metros: current annual wage),
    colored client-side by median Level I change."""
    if soc:
        rows = await database.fetch_all(text("""
            SELECT area_code, area_name, state_ab,
                   ROUND(chg::numeric, 1) AS chg,
                   cur_i, prior_i
            FROM mv_wage_yoy
            WHERE soc_code = :soc
              AND area_name NOT ILIKE '%nonmetropolitan%'
            ORDER BY cur_i DESC
        """).bindparams(soc=soc))
        return {"level": "metro", "tiles": [{
            "id":     r["area_code"],
            "label":  r["area_name"].split(",")[0] + " · " + r["state_ab"],
            "full":   r["area_name"],
            "chg":    float(r["chg"]),
            "weight": float(r["cur_i"]) * 2080,
            "cur_annual":   round(float(r["cur_i"]) * 2080),
            "prior_annual": round(float(r["prior_i"]) * 2080),
        } for r in rows]}

    if group:
        rows = await database.fetch_all(text("""
            SELECT m.soc_code, MIN(m.soc_title) AS soc_title,
                   ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY m.chg)::numeric, 1) AS med_chg,
                   COUNT(*) AS metros,
                   COALESCE(MIN(f.filings), 0) AS filings
            FROM mv_wage_yoy m
            LEFT JOIN mv_lca_soc_filings f ON f.soc_base = m.soc_code
            WHERE m.soc_code LIKE :pat
            GROUP BY m.soc_code
            ORDER BY filings DESC
        """).bindparams(pat=f"{group}-%"))
        return {"level": "soc",
                "group_title": SOC_MAJOR_GROUPS.get(group, group),
                "tiles": [{
                    "id":      r["soc_code"],
                    "label":   r["soc_title"],
                    "full":    f'{r["soc_code"]} — {r["soc_title"]}',
                    "chg":     float(r["med_chg"]),
                    "weight":  int(r["filings"]) + 25,
                    "filings": int(r["filings"]),
                    "metros":  r["metros"],
                } for r in rows]}

    rows = await database.fetch_all(text("""
        WITH grp AS (
            SELECT LEFT(soc_code, 2) AS g,
                   ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY chg)::numeric, 1) AS med_chg,
                   COUNT(DISTINCT soc_code) AS socs,
                   COUNT(*) AS combos
            FROM mv_wage_yoy
            GROUP BY 1
        ),
        fil AS (
            SELECT LEFT(soc_base, 2) AS g, SUM(filings) AS filings
            FROM mv_lca_soc_filings
            GROUP BY 1
        )
        SELECT grp.g, grp.med_chg, grp.socs, grp.combos,
               COALESCE(fil.filings, 0) AS filings
        FROM grp LEFT JOIN fil ON fil.g = grp.g
        ORDER BY filings DESC
    """))
    return {"level": "major", "tiles": [{
        "id":      r["g"],
        "label":   SOC_MAJOR_GROUPS.get(r["g"], f'{r["g"]}-0000'),
        "full":    f'{r["g"]}-0000 — {SOC_MAJOR_GROUPS.get(r["g"], "Other")}',
        "chg":     float(r["med_chg"]),
        "weight":  int(r["filings"]) + 400,
        "filings": int(r["filings"]),
        "socs":    r["socs"],
    } for r in rows]}


# ── State impact: filings volume vs median wage change per state ──────────────
@router.get("/api/wages/state-impact")
async def wages_state_impact():
    rows = await database.fetch_all(text("""
        WITH filings AS (
            SELECT worksite_state AS state, COUNT(*) AS filings
            FROM oflc_lca
            WHERE visa_class = 'H-1B' AND case_status = 'Certified'
              AND worksite_state IS NOT NULL
            GROUP BY worksite_state
        ),
        agg AS (
            SELECT state_ab,
                   ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY chg)::numeric, 2) AS median_chg,
                   ROUND((COUNT(*) FILTER (WHERE chg < 0))::numeric / COUNT(*) * 100, 1) AS pct_decreased,
                   COUNT(*) AS combos
            FROM mv_wage_yoy
            GROUP BY state_ab
        )
        SELECT a.state_ab AS state, f.filings, a.median_chg, a.pct_decreased, a.combos
        FROM agg a
        JOIN filings f ON f.state = a.state_ab
        WHERE f.filings >= 100
        ORDER BY f.filings DESC
    """))
    return [{
        "state":         r["state"],
        "filings":       r["filings"],
        "median_change": float(r["median_chg"]),
        "pct_decreased": float(r["pct_decreased"]),
        "combos":        r["combos"],
    } for r in rows]
