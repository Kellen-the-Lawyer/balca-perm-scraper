"""Equal Pay Transparency (EPT) jurisdiction data for PERM verification.

Source: AILA Practice Pointer, Guide to Equal Pay Transparency Laws
(Updated October 2025), AILA Doc. No. 25110603.

Mirrors EPT_DATA in frontend/src/PermComparer.jsx (the comparer's EPT
card). Keep the two in sync when the AILA guide updates; longer-term the
comparer should fetch this from the backend so there is one source.

threshold_count / threshold_scope semantics:
  - threshold_count: minimum employee count for the law to apply
    (0 = applies to employers of any size).
  - threshold_scope: what the count is measured against —
      "total" = employees anywhere;
      "state" = employees in (or primarily working in) the state;
      "mixed" = total count plus at least one in-state employee.
The 9089 gives A.14 (employees in the AREA of intended employment),
which is a lower bound for both state and total counts: A.14 >= the
threshold proves the law's employee-count condition is met under any
scope; A.14 below the threshold proves nothing (the employer may have
more employees elsewhere).
"""
from __future__ import annotations
from datetime import date

EPT_DATA = {
    "CA": {
        "state": "California", "effective": date(2023, 1, 1),
        "citation": "SB 1162; Cal. Labor Code \u00a7 432.3",
        "threshold_count": 15, "threshold_scope": "total",
        "benefits_req": False, "long_arm": True,
        "note": "15+ employees even if only 1 is in CA; may reach "
                "nationwide remote postings.",
    },
    "CO": {
        "state": "Colorado", "effective": date(2021, 1, 1),
        "citation": "Equal Pay for Equal Work Act; 7 CCR 1103-18",
        "threshold_count": 1, "threshold_scope": "state",
        "benefits_req": True, "long_arm": False,
        "note": "Requires general description of bonuses/benefits, not "
                "just a range.",
    },
    "HI": {
        "state": "Hawaii", "effective": date(2024, 1, 1),
        "citation": "Act 203 (SB1057), Hawaii Equal Pay Act",
        "threshold_count": 50, "threshold_scope": "total",
        "benefits_req": False, "long_arm": False,
        "note": "Excludes internal transfers/promotions.",
    },
    "IL": {
        "state": "Illinois", "effective": date(2025, 1, 1),
        "citation": "820 ILCS 112/ \u2014 Equal Pay Act of 2003",
        "threshold_count": 15, "threshold_scope": "total",
        "benefits_req": True, "long_arm": False,
        "note": "Hyperlink to pay/benefits info acceptable.",
    },
    "MD": {
        "state": "Maryland", "effective": date(2024, 10, 1),
        "citation": "HB 649 / SB 525",
        "threshold_count": 0, "threshold_scope": "total",
        "benefits_req": True, "long_arm": False,
        "note": "Employers of any size; no open-ended ranges.",
    },
    "MA": {
        "state": "Massachusetts", "effective": date(2025, 10, 29),
        "citation": "H.4890, Salary Range Transparency Act",
        "threshold_count": 25, "threshold_scope": "state",
        "benefits_req": False, "long_arm": False,
        "note": "25+ with primary place of work in MA.",
    },
    "MN": {
        "state": "Minnesota", "effective": date(2025, 1, 1),
        "citation": "S.F. No. 3852, Article 7",
        "threshold_count": 30, "threshold_scope": "state",
        "benefits_req": True, "long_arm": False,
        "note": "30+ at MN work sites; no open-ended ranges; benefits "
                "description required.",
    },
    "NJ": {
        "state": "New Jersey", "effective": date(2025, 6, 1),
        "citation": "P.L. 2024, c. 91",
        "threshold_count": 10, "threshold_scope": "total",
        "benefits_req": True, "long_arm": True,
        "note": "10+ employees over 20 weeks; reaches employers taking "
                "applications from NJ residents.",
    },
    "NY": {
        "state": "New York", "effective": date(2023, 9, 17),
        "citation": "N.Y. Lab. Law \u00a7 194-b",
        "threshold_count": 4, "threshold_scope": "total",
        "benefits_req": False, "long_arm": False,
        "note": "4+ employees, not required to be in NY.",
    },
    "VT": {
        "state": "Vermont", "effective": date(2025, 7, 1),
        "citation": "Act 155 (H.704)",
        "threshold_count": 5, "threshold_scope": "mixed",
        "benefits_req": False, "long_arm": False,
        "note": "5+ employees with at least one working in VT.",
    },
    "DC": {
        "state": "Washington, D.C.", "effective": date(2024, 6, 20),
        "citation": "D.C. Act 25-367",
        "threshold_count": 1, "threshold_scope": "state",
        "benefits_req": False, "long_arm": False,
        "note": "Any posting soliciting DC employees, any size employer.",
    },
    "WA": {
        "state": "Washington State", "effective": date(2023, 1, 1),
        "citation": "RCW 49.58.110; SSB 5408",
        "threshold_count": 15, "threshold_scope": "mixed",
        "benefits_req": True, "long_arm": False,
        "note": "15+ employees with at least 1 WA-based; benefits "
                "description required.",
    },
}

STATE_ALIASES = {
    "WASHINGTON DC": "DC", "WASHINGTON D.C.": "DC", "D.C.": "DC",
    "DISTRICT OF COLUMBIA": "DC", "CALIFORNIA": "CA", "COLORADO": "CO",
    "HAWAII": "HI", "ILLINOIS": "IL", "MARYLAND": "MD",
    "MASSACHUSETTS": "MA", "MINNESOTA": "MN", "NEW JERSEY": "NJ",
    "NEW YORK": "NY", "VERMONT": "VT", "WASHINGTON": "WA",
    "WASHINGTON STATE": "WA",
}


def lookup_ept(state_val, city=None):
    """EPT record for a worksite state (2-letter code or full name)."""
    if not state_val:
        return None
    s = str(state_val).strip().upper()
    rec = EPT_DATA.get(s) or EPT_DATA.get(STATE_ALIASES.get(s, ""))
    if rec:
        return rec
    if city and __import__("re").search(
            r"washington.*d\.?c\.?|district.*columbia", str(city),
            __import__("re").I):
        return EPT_DATA["DC"]
    return None
