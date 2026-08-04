"""Worksite geography for Tier 3: county/state -> OES area code sets.

Loaded once, lazily, into memory from current_oews_wages (collection_type
'alc'); ~3.3K rows.  Split counties (partly inside an MSA, partly
balance-of-state) legitimately map to TWO area codes, so lookups return a
set and "same area" means the two sets intersect.

The rule engine stays runnable without a database: if the load fails the
map is empty and callers fall back to title comparison alone.
"""
from __future__ import annotations
import os
import re
from functools import lru_cache

_DB_URL = "postgresql://perm@127.0.0.1:5433/perm_decisions"

_COUNTY_SUFFIX = re.compile(
    r"\s+(county|parish|borough|census area|city and borough|municipio|"
    r"municipality|city)$")

STATE_AB = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT",
    "delaware": "DE", "district of columbia": "DC", "florida": "FL",
    "georgia": "GA", "guam": "GU", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH",
    "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH",
    "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA",
    "puerto rico": "PR", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virgin islands": "VI", "virginia": "VA",
    "washington": "WA", "west virginia": "WV", "wisconsin": "WI",
    "wyoming": "WY",
}


def norm_state(s):
    s = (s or "").strip()
    if len(s) == 2:
        return s.upper()
    return STATE_AB.get(s.lower(), s.upper())


def norm_county(c):
    return _COUNTY_SUFFIX.sub("", (c or "").strip().lower()).strip()


def norm_area_title(t):
    """Normalize an auto-filled MSA/BLS area title for comparison."""
    t = (t or "").strip().lower()
    t = re.sub(r"metropolitan statistical area|nonmetropolitan area|"
               r"metropolitan division|\bmsa\b|\bdiv\b", "", t)
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


@lru_cache(maxsize=1)
def _county_map():
    """{(state_ab, normalized_county): {area_code, ...}} or {} on failure."""
    out = {}
    try:
        import psycopg2
        url = os.environ.get("DATABASE_URL", _DB_URL)
        with psycopg2.connect(url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT state_ab, county_name, area_code "
                "FROM current_oews_wages WHERE collection_type = 'alc' "
                "AND county_name IS NOT NULL")
            for st, cty, area in cur.fetchall():
                out.setdefault(
                    (norm_state(st), norm_county(cty)), set()).add(area)
    except Exception:
        return {}
    return out


def area_codes(county, state):
    """OES area code set for a county/state, empty set if unknown."""
    if not (county and state):
        return set()
    return _county_map().get((norm_state(state), norm_county(county)), set())
