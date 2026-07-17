"""
Wage Level Determination tool — implements the 5-step worksheet from the
NPWHC "Prevailing Wage Determination Policy Guidance" (rev. Nov. 2009),
Appendices A-C, against O*NET Job Zone data (onet_job_zones /
onet_job_zone_reference) and the 2026-27 OFLC wage table
(current_oews_wages).

All determinations start at Level I. Points:
  Step 2  experience above the Job Zone SVP range        (0-3)
  Step 3  education above usual (Appendix D professional
          categories, else Job Zone usual education)     (0-2)
  Step 4  special skills / foreign language              (0-2)
  Step 5  supervisory duties (customary-supervision
          occupations excepted)                          (0-1)
Level = 1 + sum, capped at 4.

The guidance (p.13) expressly states the process "should not be
implemented in an automated fashion" — output includes the per-step
worksheet so the attorney can audit and override each point.
"""
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import text

from core import *  # noqa: F401,F403 -- shared db (database), config, helpers
from wage_level_data import (
    APPENDIX_D, APPENDIX_D_CATEGORY_RANK, APPENDIX_D_CATEGORY_LABEL,
    SOC_2018_TO_APPENDIX_D, DEGREE_RANKS, DEGREE_LABELS,
    ZONE_USUAL_EDUCATION_RANK, ZONE_USUAL_EDUCATION_LABEL,
    ZONE_EXPERIENCE_BANDS, ZONE1_SVP_POINTS,
    EDUCATION_SVP_MONTHS, ZONE_SVP_CEILING_MONTHS,
)

router = APIRouter()

GUIDANCE = "NPWHC Prevailing Wage Determination Policy Guidance (rev. Nov. 2009)"

# First-line supervisor detailed groups (XX-10XX) and all of management (11-)
_SUPERVISORY_SOC = re.compile(r"^(11-|\d{2}-10\d{2})")


def normalize_soc(raw: str):
    """'15-1252', '15-1252.00', '151252', '15.1252' -> ('15-1252', '00'|ext)"""
    if not raw:
        return None, None
    s = raw.strip().replace(".", "").replace("-", "")
    ext = None
    if len(s) == 8:               # onet extension folded in, e.g. 15125200
        s, ext = s[:6], s[6:]
    if len(s) != 6 or not s.isdigit():
        return None, None
    return f"{s[:2]}-{s[2:]}", ext


async def lookup_zone(soc_base: str, onet_ext: Optional[str]):
    """Job zone for a base SOC — exact .00, then MAX across extensions."""
    if onet_ext:
        row = await database.fetch_one(text(
            "SELECT job_zone, onetsoc_code FROM onet_job_zones WHERE onetsoc_code = :c")
            .bindparams(c=f"{soc_base}.{onet_ext}"))
        if row:
            return row["job_zone"], row["onetsoc_code"]
    row = await database.fetch_one(text(
        "SELECT job_zone, onetsoc_code FROM onet_job_zones WHERE onetsoc_code = :c")
        .bindparams(c=f"{soc_base}.00"))
    if row:
        return row["job_zone"], row["onetsoc_code"]
    row = await database.fetch_one(text(
        "SELECT MAX(job_zone) AS z FROM onet_job_zones WHERE onetsoc_code LIKE :p")
        .bindparams(p=f"{soc_base}.%"))
    if row and row["z"] is not None:
        return row["z"], f"{soc_base}.* (max across O*NET extensions)"
    return None, None


def appendix_d_category(soc_base: str):
    """Appendix D education/training category, via the 2018->2000 crosswalk
    when needed. Returns (category, source_soc) or (None, None)."""
    if soc_base in APPENDIX_D:
        return APPENDIX_D[soc_base], soc_base
    mapped = SOC_2018_TO_APPENDIX_D.get(soc_base)
    if mapped and mapped in APPENDIX_D:
        return APPENDIX_D[mapped], mapped
    return None, None


# ── Worksheet steps ──────────────────────────────────────────────────────────

def step2_experience(zone: int, months: int):
    """Experience points per Step 2. Returns (points, rationale)."""
    if zone == 1:
        for cap, pts in ZONE1_SVP_POINTS:
            if months <= cap:
                return pts, (f"Job Zone 1 uses the SVP scale directly: "
                             f"{months} mo -> {pts} point(s).")
        return 3, (f"Job Zone 1 with {months} months required exceeds the "
                   f"SVP 4 ceiling (6 months) -> 3 points.")
    band = ZONE_EXPERIENCE_BANDS.get(zone)
    if not band:
        return 0, "No SVP band for this Job Zone; no experience points."
    start, low_top, high_top = band
    if months <= start:
        return 0, (f"{months} mo is at/below the Job Zone {zone} range start "
                   f"({start} mo) — at or below the SVP range, 0 points.")
    if months <= low_top:
        return 1, (f"{months} mo is in the LOW end of the Job Zone {zone} SVP "
                   f"range ({start}–{high_top} mo) -> 1 point.")
    if months <= high_top:
        return 2, (f"{months} mo is in the HIGH end of the Job Zone {zone} SVP "
                   f"range ({start}–{high_top} mo) -> 2 points.")
    return 3, (f"{months} mo EXCEEDS the Job Zone {zone} SVP range "
               f"(> {high_top} mo) -> 3 points. Also check ETA-9089 G.9 / "
               f"business necessity (656.17(h)(1)).")


def step3_education(zone: int, soc_base: Optional[str], degree_key: str):
    """Education points per Step 3. Returns (points, rationale, meta)."""
    req_rank = DEGREE_RANKS[degree_key]
    cat, cat_soc = appendix_d_category(soc_base) if soc_base else (None, None)
    if cat is not None:
        usual_rank = APPENDIX_D_CATEGORY_RANK[cat]
        usual_label = APPENDIX_D_CATEGORY_LABEL[cat]
        source = (f"Appendix D professional occupation "
                  f"(category {cat}, via {cat_soc})")
    else:
        usual_rank = ZONE_USUAL_EDUCATION_RANK.get(zone, 3)
        usual_label = ZONE_USUAL_EDUCATION_LABEL.get(zone, "bachelor's degree")
        source = f"O*NET Job Zone {zone} usual education (not on Appendix D)"
    diff = req_rank - usual_rank
    pts = 0 if diff <= 0 else (1 if diff == 1 else 2)
    if diff <= 0:
        why = (f"Required education ({DEGREE_LABELS[degree_key]}) is at/below "
               f"the usual requirement ({usual_label}) — 0 points.")
    else:
        why = (f"Required education ({DEGREE_LABELS[degree_key]}) exceeds the "
               f"usual requirement ({usual_label}) by "
               f"{'one category' if diff == 1 else 'more than one category'} "
               f"-> {pts} point(s).")
    meta = {"usual_education": usual_label, "usual_source": source,
            "appendix_d_category": cat}
    return pts, why, meta


def step5_supervisory(soc_base: Optional[str], soc_title: Optional[str],
                      supervises: bool):
    if not supervises:
        return 0, "No supervisory requirement — 0 points."
    customary = False
    if soc_base and _SUPERVISORY_SOC.match(soc_base):
        customary = True
    if soc_title and re.search(r"supervisor|manager", soc_title, re.I):
        customary = True
    if customary:
        return 0, ("Supervision is customary for this occupation "
                   "(management / first-line supervisor SOC) — exception "
                   "applies, 0 points.")
    return 1, "Supervisory duties required and not customary for the occupation -> 1 point."


# ── API models ───────────────────────────────────────────────────────────────

class DetermineRequest(BaseModel):
    soc_code: Optional[str] = None
    job_zone: Optional[int] = Field(None, ge=1, le=5)   # override / no-SOC path
    degree_required: str = "bachelors"                  # key into DEGREE_RANKS
    years_experience_required: Optional[float] = None
    months_experience_required: Optional[int] = None    # wins if both given
    special_skills_points: int = Field(0, ge=0, le=2)   # attorney judgment, Step 4
    foreign_language_required: bool = False
    supervisory_duties: bool = False
    # optional wage $ lookup
    area_code: Optional[str] = None
    state_ab: Optional[str] = None
    county_name: Optional[str] = None
    collection_type: str = "alc"


@router.get("/api/wage-level/occupation/{soc}")
async def wage_level_occupation(soc: str):
    """Prefill data for the UI: zone, zone reference, title, Appendix D info."""
    base, ext = normalize_soc(soc)
    if not base:
        raise HTTPException(400, "Could not parse SOC code")
    zone, matched = await lookup_zone(base, ext)
    zref = None
    if zone:
        zref = await database.fetch_one(text(
            "SELECT * FROM onet_job_zone_reference WHERE job_zone = :z").bindparams(z=zone))
    trow = await database.fetch_one(text(
        "SELECT soc_title FROM current_oews_wages WHERE soc_code = :s LIMIT 1")
        .bindparams(s=base))
    cat, cat_soc = appendix_d_category(base)
    return {
        "soc_code": base,
        "soc_title": trow["soc_title"] if trow else None,
        "job_zone": zone,
        "matched_onet_code": matched,
        "zone_reference": dict(zref) if zref else None,
        "appendix_d_category": cat,
        "appendix_d_category_label": APPENDIX_D_CATEGORY_LABEL.get(cat),
        "appendix_d_via": cat_soc,
        "is_professional_occupation": cat is not None,
    }


@router.get("/api/wage-level/areas/{state_ab}")
async def wage_level_areas(state_ab: str):
    rows = await database.fetch_all(text("""
        SELECT DISTINCT area_code, area_name
        FROM current_oews_wages
        WHERE state_ab = :st AND collection_type = 'alc'
        ORDER BY area_name""").bindparams(st=state_ab.upper()))
    return [dict(r) for r in rows]


@router.get("/api/wage-level/counties/{state_ab}")
async def wage_level_counties(state_ab: str):
    """Distinct counties for a state, with their OES area (UI dropdown)."""
    rows = await database.fetch_all(text("""
        SELECT DISTINCT county_name, area_name
        FROM current_oews_wages
        WHERE state_ab = :st AND collection_type = 'alc'
          AND county_name IS NOT NULL
        ORDER BY county_name""").bindparams(st=state_ab.upper()))
    return [dict(r) for r in rows]


@router.post("/api/wage-level/determine")
async def wage_level_determine(req: DetermineRequest):
    if req.degree_required not in DEGREE_RANKS:
        raise HTTPException(400, f"degree_required must be one of {list(DEGREE_RANKS)}")

    soc_base, ext, matched, soc_title = None, None, None, None
    zone = req.job_zone
    if req.soc_code:
        soc_base, ext = normalize_soc(req.soc_code)
        if not soc_base:
            raise HTTPException(400, "Could not parse SOC code")
        db_zone, matched = await lookup_zone(soc_base, ext)
        if zone is None:
            zone = db_zone
        trow = await database.fetch_one(text(
            "SELECT soc_title FROM current_oews_wages WHERE soc_code = :s LIMIT 1")
            .bindparams(s=soc_base))
        soc_title = trow["soc_title"] if trow else None
    if zone is None:
        raise HTTPException(
            422, "No Job Zone found for that SOC code — supply job_zone explicitly")

    months = req.months_experience_required
    if months is None:
        months = int(round((req.years_experience_required or 0) * 12))

    worksheet = [{"step": 1, "label": "Baseline (all determinations start at Level I)",
                  "points": 1, "rationale": f"{GUIDANCE}, §II.B.2."}]

    p2, why2 = step2_experience(zone, months)
    worksheet.append({"step": 2, "label": "Experience", "points": p2,
                      "rationale": why2})

    p3, why3, edu_meta = step3_education(zone, soc_base, req.degree_required)
    worksheet.append({"step": 3, "label": "Education", "points": p3,
                      "rationale": why3, **edu_meta})

    p4 = min(2, req.special_skills_points + (1 if req.foreign_language_required else 0))
    why4 = []
    if req.special_skills_points:
        why4.append(f"{req.special_skills_points} point(s) entered for special "
                    f"skills beyond an entry-level worker (attorney judgment).")
    if req.foreign_language_required:
        why4.append("Foreign-language requirement is generally a special skill "
                    "(+1; exceptions: foreign-language teachers, interpreters, "
                    "caption writers, and cases like specialty cooks).")
    worksheet.append({"step": 4, "label": "Special skills / other requirements",
                      "points": p4,
                      "rationale": " ".join(why4) or "None claimed — 0 points."})

    p5, why5 = step5_supervisory(soc_base, soc_title, req.supervisory_duties)
    worksheet.append({"step": 5, "label": "Supervisory duties", "points": p5,
                      "rationale": why5})

    total = 1 + p2 + p3 + p4 + p5
    level = min(4, total)

    caveats = [
        "The 2009 guidance (p.13) states the worksheet 'should not be "
        "implemented in an automated fashion' — this is an audit aid, not a "
        "substitute for NPWC judgment.",
        "The low-end / high-end split within each Job Zone SVP range is a "
        "practitioner convention (midpoint); the guidance does not define it.",
        "Do not double-count: education counted as equivalent experience in "
        "Step 2 must not also be counted in Step 3, and license-related "
        "experience/education earns a point in only ONE of Steps 2-4.",
        "Validated against 194,140 FY2025 OES determinations (PW disclosure): "
        "82% exact, 96% within one level, <2% overpredicted. When this tool "
        "and the NPWC disagree, the tool is almost always ONE LEVEL LOW — "
        "the gap is Step-4 special-skills points. Treat the result as a "
        "floor: if the job's skills are arguably beyond entry level, budget "
        "one level higher.",
    ]
    if total > 4:
        caveats.insert(0, f"Raw point total is {total}; capped at Level IV.")

    result = {
        "wage_level": level,
        "wage_level_label": {1: "Level I (entry)", 2: "Level II (qualified)",
                             3: "Level III (experienced)",
                             4: "Level IV (fully competent)"}[level],
        "total_points": total,
        "worksheet": worksheet,
        "soc_code": soc_base, "soc_title": soc_title,
        "job_zone": zone, "matched_onet_code": matched,
        "experience_months_used": months,
        "guidance": GUIDANCE,
        "caveats": caveats,
    }

    # ── Informational SVP-equivalency analysis (NOT scored) ────────────────
    edu_svp = EDUCATION_SVP_MONTHS[req.degree_required]
    combined = months + edu_svp
    ceiling = ZONE_SVP_CEILING_MONTHS.get(zone)
    exceeds = combined > ceiling if ceiling else False
    svp_notes = [
        "Education-to-SVP conversion is a contested adjudicator convention "
        "(bachelor's = 24 mo, master's = 48 mo, etc.); the 2009 wage guidance "
        "does not adopt it. Shown for ETA-9089 G.9 / 656.17(h)(1) business-"
        "necessity exposure only — it does NOT affect the wage level above.",
    ]
    if zone == 5:
        svp_notes.append(
            "Job Zone 5 is open-ended (SVP 8.0 and above); 120 mo is the SVP 8 "
            "ceiling, not a hard bound — anything over it is SVP 9 territory.")
    if exceeds and zone != 5:
        svp_notes.append(
            "Combined requirements exceed the zone SVP ceiling — if ETA-9089 "
            "G.9 is answered 'No', expect a T4-007-type problem; if 'Yes', an "
            "Appendix C business-necessity justification meeting the "
            "Information Industries standard is needed.")
    result["svp_analysis"] = {
        "experience_months": months,
        "education_svp_equivalent_months": edu_svp,
        "education_conversion": f"{DEGREE_LABELS[req.degree_required]} ≈ "
                                f"{edu_svp} mo SVP (contested convention)",
        "combined_svp_months": combined,
        "combined_svp_years": round(combined / 12, 1),
        "zone_svp_ceiling_months": ceiling,
        "exceeds_zone_svp": exceeds,
        "notes": svp_notes,
    }

    # Optional wage $ lookup
    if soc_base and (req.area_code or req.state_ab):
        where, params = ["soc_code = :soc", "collection_type = :ct"], \
                        {"soc": soc_base, "ct": req.collection_type}
        if req.area_code:
            where.append("area_code = :ac"); params["ac"] = req.area_code
        if req.state_ab:
            where.append("state_ab = :st"); params["st"] = req.state_ab.upper()
        if req.county_name:
            where.append("county_name ILIKE :cn")
            params["cn"] = f"%{req.county_name.strip()}%"
        wrow = await database.fetch_one(text(f"""
            SELECT DISTINCT ON (soc_code) area_code, area_name, county_name,
                   level_i, level_ii, level_iii, level_iv, level_mean, wage_year
            FROM current_oews_wages
            WHERE {' AND '.join(where)}
            ORDER BY soc_code, county_name""").bindparams(**params))
        if wrow:
            hourly = [wrow["level_i"], wrow["level_ii"], wrow["level_iii"],
                      wrow["level_iv"]][level - 1]
            result["wage"] = {
                "area_code": wrow["area_code"], "area_name": wrow["area_name"],
                "county_name": wrow["county_name"], "wage_year": wrow["wage_year"],
                "levels_hourly": {"i": float(wrow["level_i"] or 0),
                                  "ii": float(wrow["level_ii"] or 0),
                                  "iii": float(wrow["level_iii"] or 0),
                                  "iv": float(wrow["level_iv"] or 0)},
                "determined_hourly": float(hourly) if hourly is not None else None,
                "determined_annual": round(float(hourly) * 2080, 2)
                                     if hourly is not None else None,
            }
        else:
            result["wage"] = None
    return result
