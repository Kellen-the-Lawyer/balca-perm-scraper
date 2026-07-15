"""Static data for the OES Wage Level Determination tool.

Sources:
  - Appendix D, "Prevailing Wage Determination Policy Guidance" (NPWHC,
    revised Nov. 2009): Professional Occupations Education and Training
    Categories (O*NET-SOC 2000-vintage codes, normalized to base SOC).
  - Appendix E (SVP scale, DOT 4th Ed. App. C).
  - O*NET Job Zone svp_range (onet_job_zone_reference).

NOTE ON SOC VINTAGE: Appendix D uses 2000-era SOC codes. OFLC now keys
wage data to 2018 SOC. SOC_2018_TO_APPENDIX_D maps the highest-volume
modern codes to their Appendix D analog. Anything unmapped falls back to
the Job-Zone-derived usual education, and the response says which source
was used.
"""

# Education/training category -> usual degree rank (see DEGREE_RANKS)
#   1 First professional  2 Doctoral  3 Master's
#   4 Bachelor's + experience  5 Bachelor's
APPENDIX_D_CATEGORY_RANK = {1: 5, 2: 5, 3: 4, 4: 3, 5: 3}

APPENDIX_D_CATEGORY_LABEL = {
    1: "First professional degree",
    2: "Doctoral degree",
    3: "Master's degree",
    4: "Work experience plus a bachelor's or higher degree",
    5: "Bachelor's degree",
}

# Base SOC (2000 vintage, "XX-XXXX") -> Appendix D category
APPENDIX_D = {
    # Category 1 - first professional degree
    "21-2011": 1, "23-1011": 1, "29-1011": 1, "29-1021": 1, "29-1022": 1,
    "29-1023": 1, "29-1024": 1, "29-1041": 1, "29-1051": 1, "29-1061": 1,
    "29-1062": 1, "29-1063": 1, "29-1064": 1, "29-1065": 1, "29-1066": 1,
    "29-1067": 1, "29-1081": 1, "29-1131": 1,
    # Category 2 - doctoral degree
    "15-1011": 2, "19-1021": 2, "19-1022": 2, "19-1042": 2, "19-2011": 2,
    "19-2012": 2, "19-3031": 2, "25-1021": 2, "25-1022": 2, "25-1032": 2,
    "25-1041": 2, "25-1042": 2, "25-1043": 2, "25-1052": 2, "25-1054": 2,
    "25-1071": 2, "25-1072": 2, "25-1121": 2, "25-1191": 2,
    # Category 3 - master's degree
    "15-2021": 3, "15-2031": 3, "15-2041": 3, "19-1041": 3, "19-2041": 3,
    "19-2042": 3, "19-2043": 3, "19-3011": 3, "19-3021": 3, "19-3022": 3,
    "19-3032": 3, "19-3041": 3, "19-3051": 3, "19-3091": 3, "19-3092": 3,
    "19-3093": 3, "19-3094": 3, "21-1011": 3, "21-1012": 3, "21-1013": 3,
    "21-1014": 3, "21-1015": 3, "21-1023": 3, "21-1091": 3, "25-4011": 3,
    "25-4012": 3, "25-4021": 3, "25-9031": 3, "29-1121": 3, "29-1123": 3,
    "29-1127": 3,
    # Category 4 - bachelor's or higher plus experience
    "11-1011": 4, "11-1021": 4, "11-2011": 4, "11-2021": 4, "11-2022": 4,
    "11-2031": 4, "11-3011": 4, "11-3021": 4, "11-3031": 4, "11-3040": 4,
    "11-3041": 4, "11-3042": 4, "11-3061": 4, "11-9011": 4, "11-9031": 4,
    "11-9032": 4, "11-9033": 4, "11-9041": 4, "11-9111": 4, "11-9121": 4,
    "13-1011": 4, "13-1111": 4, "15-2011": 4, "23-1021": 4, "23-1022": 4,
    "23-1023": 4, "25-2023": 4, "25-2032": 4, "27-1011": 4, "27-2012": 4,
    "27-2041": 4, "27-3020": 4, "27-3021": 4, "27-3022": 4,
    # Category 5 - bachelor's degree
    "11-3051": 5, "11-9021": 5, "11-9141": 5, "11-9151": 5, "13-1071": 5,
    "13-1072": 5, "13-1073": 5, "13-1121": 5, "13-2011": 5, "13-2031": 5,
    "13-2041": 5, "13-2051": 5, "13-2052": 5, "13-2053": 5, "13-2061": 5,
    "13-2071": 5, "13-2072": 5, "13-2081": 5, "15-1021": 5, "15-1031": 5,
    "15-1032": 5, "15-1051": 5, "15-1061": 5, "15-1071": 5, "15-1081": 5,
    "17-1011": 5, "17-1012": 5, "17-1021": 5, "17-1022": 5, "17-2011": 5,
    "17-2021": 5, "17-2031": 5, "17-2041": 5, "17-2051": 5, "17-2061": 5,
    "17-2071": 5, "17-2072": 5, "17-2081": 5, "17-2111": 5, "17-2112": 5,
    "17-2121": 5, "17-2131": 5, "17-2141": 5, "17-2151": 5, "17-2161": 5,
    "17-2171": 5, "19-1010": 5, "19-1011": 5, "19-1012": 5, "19-1013": 5,
    "19-1020": 5, "19-1023": 5, "19-1031": 5, "19-1032": 5, "19-2021": 5,
    "19-2031": 5, "19-2032": 5, "21-1021": 5, "21-1022": 5, "21-1092": 5,
    "21-2021": 5, "23-2092": 5, "25-2012": 5, "25-2021": 5, "25-2022": 5,
    "25-2031": 5, "25-2041": 5, "25-2042": 5, "25-2043": 5, "25-3011": 5,
    "25-4013": 5, "25-9021": 5, "27-1014": 5, "27-1021": 5, "27-1022": 5,
    "27-1024": 5, "27-1025": 5, "27-1027": 5, "27-3031": 5, "27-3041": 5,
    "27-3042": 5, "27-3043": 5, "27-4032": 5, "29-1031": 5, "29-1071": 5,
    "29-1122": 5, "29-1125": 5, "29-2011": 5, "29-2091": 5, "29-9010": 5,
    "29-9091": 5, "33-3021": 5, "39-9032": 5, "41-3021": 5, "41-3031": 5,
    "41-9031": 5, "53-2011": 5,
}

# 2018 SOC -> Appendix D analog (2000 SOC) for high-volume H-1B/PERM codes
# whose numbering changed between vintages. Conservative: only unambiguous
# lineages are mapped.
SOC_2018_TO_APPENDIX_D = {
    "15-1251": "15-1021",  # Computer Programmers
    "15-1252": "15-1031",  # Software Developers
    "15-1253": "15-1031",  # Software QA Analysts and Testers
    "15-1211": "15-1051",  # Computer Systems Analysts
    "15-1212": "15-1071",  # Information Security Analysts
    "15-1242": "15-1061",  # Database Administrators
    "15-1244": "15-1071",  # Network and Computer Systems Administrators
    "15-1241": "15-1081",  # Computer Network Architects
    "15-1221": "15-1011",  # Computer & Information Research Scientists
    "19-3033": "19-3031",  # Clinical & Counseling Psychologists (2018 split)
    "19-3034": "19-3031",  # School Psychologists (2018 split)
    "29-1211": "29-1061",  # Anesthesiologists
    "29-1215": "29-1062",  # Family Medicine Physicians
    "29-1216": "29-1063",  # General Internal Medicine Physicians
    "29-1218": "29-1064",  # Obstetricians and Gynecologists
    "29-1221": "29-1065",  # Pediatricians, General
    "29-1222": "29-1066",  # Psychiatrists
    "29-1241": "29-1067",  # Ophthalmologists -> Surgeons lineage (first professional)
    "29-1242": "29-1067",  # Orthopedic Surgeons
    "29-1243": "29-1067",  # Pediatric Surgeons
    "29-1249": "29-1067",  # Surgeons, All Other
    "29-1228": "29-1067",  # Physicians, Pathologists (first-professional lineage)
    "13-1082": "13-1111",  # Project Mgmt Specialists -> Management Analysts (nearest)
}

# Degree ladder used for employer-requirement vs usual-education comparison
DEGREE_RANKS = {
    "none": 0,
    "high_school": 1,
    "associates": 2,
    "bachelors": 3,
    "masters": 4,
    "doctorate": 5,
    "professional": 5,
}
DEGREE_LABELS = {
    "none": "No degree requirement",
    "high_school": "High school / GED",
    "associates": "Associate's degree",
    "bachelors": "Bachelor's degree",
    "masters": "Master's degree",
    "doctorate": "Doctorate (Ph.D.)",
    "professional": "First professional degree (J.D., M.D., etc.)",
}

# Usual education by Job Zone when the SOC is not an Appendix D
# professional occupation (O*NET Job Zone descriptions).
ZONE_USUAL_EDUCATION_RANK = {1: 1, 2: 1, 3: 2, 4: 3, 5: 4}
ZONE_USUAL_EDUCATION_LABEL = {
    1: "little or no formal education",
    2: "high school diploma or GED",
    3: "vocational training / associate's degree",
    4: "bachelor's degree",
    5: "graduate degree (master's or higher)",
}

# Step 2 experience bands in months by Job Zone, derived from the zone
# svp_range (O*NET) and the DOT SVP scale (Appendix E):
#   (range_start, low_end_top, high_end_top)
# Points: <= start -> 0; <= low_end_top -> 1; <= high_end_top -> 2; else 3.
# The low/high split at the midpoint is a practitioner convention - the
# 2009 guidance says "low end" / "high end" without defining a boundary.
ZONE_EXPERIENCE_BANDS = {
    2: (0, 6, 12),     # SVP < 6.0  (up to 1 year)
    3: (12, 18, 24),   # SVP 6.0-<7.0 (>1 to 2 years)
    4: (24, 36, 48),   # SVP 7.0-<8.0 (>2 to 4 years)
    5: (48, 84, 120),  # SVP >= 8.0 (>4 years; SVP 8 tops at 10 years)
}

# Job Zone 1 uses the raw SVP scale (guidance Step 2, Zone 1 rules)
ZONE1_SVP_POINTS = [  # (max_months_inclusive, points)
    (0, 0),   # short demonstration only (SVP 1)
    (1, 1),   # up to 1 month (SVP 2)
    (3, 2),   # >1 to 3 months (SVP 3)
    (6, 3),   # >3 to 6 months (SVP 4)
]

# ── Informational SVP-equivalency (contested convention; NOT scored) ────────
# Education-to-SVP-time conversion used by some adjudicators when testing
# whether a job's TOTAL requirements exceed the occupation's SVP (the
# ETA-9089 G.9 / 656.17(h)(1) business-necessity question). The 2009 wage
# guidance does NOT adopt this conversion, and rules_onet.py (T4-007)
# deliberately declines it. Displayed for exposure analysis only.
EDUCATION_SVP_MONTHS = {
    "none": 0,
    "high_school": 0,      # SVP excludes general (non-vocational) education
    "associates": 12,
    "bachelors": 24,
    "masters": 48,         # bachelor's + 2
    "doctorate": 84,       # bachelor's + 5 (convention varies: 60-96)
    "professional": 84,    # J.D./M.D. (convention varies)
}

# Zone SVP ceiling in months for the informational comparison.
# Zone 5 is open-ended (8.0 and above); 120 is the SVP 8 ceiling and is
# reported with a caveat rather than as a hard bound.
ZONE_SVP_CEILING_MONTHS = {1: 6, 2: 12, 3: 24, 4: 48, 5: 120}
