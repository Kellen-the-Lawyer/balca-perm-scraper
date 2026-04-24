#!/usr/bin/env python3
"""
OFLC Disclosure Data Ingestion
Loads PERM, LCA, and PW disclosure files into perm_decisions DB.

Usage:
    python3 ingest_oflc.py                    # ingest all
    python3 ingest_oflc.py --program perm
    python3 ingest_oflc.py --program lca
    python3 ingest_oflc.py --program pw
    python3 ingest_oflc.py --reset            # truncate tables before loading
    python3 ingest_oflc.py --dry-run          # count rows only, no DB writes
"""

import os, sys, re, argparse
from pathlib import Path
import pandas as pd
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

DB_URL   = os.environ.get("DATABASE_URL", "postgresql://perm:perm_local_pw@localhost:5432/perm_decisions")
DATA_DIR = Path(__file__).parent / "oflc_data"
BATCH    = 2000

def get_conn():
    return psycopg2.connect(DB_URL)

def coerce_date(val):
    if val is None: return None
    try:
        if str(val).strip() in ("", "nan", "NaT"): return None
        return pd.Timestamp(val).date()
    except Exception:
        return None

def coerce_str(val):
    if val is None: return None
    s = str(val).strip()
    if s in ("nan", "NaT", ""): return None
    if s.startswith('="') and s.endswith('"'): s = s[2:-1]
    return s or None

def coerce_num(val):
    if val is None: return None
    try:
        if str(val).strip() in ("", "nan"): return None
        return float(val)
    except Exception:
        return None

def coerce_int(val):
    n = coerce_num(val)
    return int(n) if n is not None else None

def fy_from_path(path: Path) -> str:
    m = re.match(r'(FY\d{4})', path.parent.name)
    return m.group(1) if m else path.parent.name

def g(row, *keys):
    for k in keys:
        if k in row and str(row[k]).strip() not in ("", "nan", "NaT"):
            return row[k]
    return None

# ── PERM ──────────────────────────────────────────────────────────────────────

PERM_SQL = """
INSERT INTO oflc_perm (
  case_number, fiscal_year, source_file, case_status,
  received_date, decision_date, occupation_type,
  employer_name, employer_state, employer_city, employer_postal_code,
  employer_fein, employer_naics, employer_num_payroll, employer_year_commenced,
  atty_law_firm, atty_last_name, atty_first_name, atty_state,
  job_title, soc_code, soc_title, wage_from, wage_to, wage_per,
  worksite_city, worksite_state, worksite_postal_code, worksite_bls_area,
  pwd_number, fw_currently_employed, is_multiple_locations, employer_layoff
) VALUES (
  %(case_number)s, %(fiscal_year)s, %(source_file)s, %(case_status)s,
  %(received_date)s, %(decision_date)s, %(occupation_type)s,
  %(employer_name)s, %(employer_state)s, %(employer_city)s, %(employer_postal_code)s,
  %(employer_fein)s, %(employer_naics)s, %(employer_num_payroll)s, %(employer_year_commenced)s,
  %(atty_law_firm)s, %(atty_last_name)s, %(atty_first_name)s, %(atty_state)s,
  %(job_title)s, %(soc_code)s, %(soc_title)s, %(wage_from)s, %(wage_to)s, %(wage_per)s,
  %(worksite_city)s, %(worksite_state)s, %(worksite_postal_code)s, %(worksite_bls_area)s,
  %(pwd_number)s, %(fw_currently_employed)s, %(is_multiple_locations)s, %(employer_layoff)s
) ON CONFLICT (case_number, fiscal_year) DO NOTHING
"""

def map_perm_row(row, fy, sf):
    return {
        "case_number":             coerce_str(g(row, "CASE_NUMBER")),
        "fiscal_year":             fy, "source_file": sf,
        "case_status":             coerce_str(g(row, "CASE_STATUS")),
        "received_date":           coerce_date(g(row, "RECEIVED_DATE")),
        "decision_date":           coerce_date(g(row, "DECISION_DATE")),
        "occupation_type":         coerce_str(g(row, "OCCUPATION_TYPE")),
        "employer_name":           coerce_str(g(row, "EMP_BUSINESS_NAME")),
        "employer_state":          coerce_str(g(row, "EMP_STATE")),
        "employer_city":           coerce_str(g(row, "EMP_CITY")),
        "employer_postal_code":    coerce_str(g(row, "EMP_POSTCODE")),
        "employer_fein":           coerce_str(g(row, "EMP_FEIN")),
        "employer_naics":          coerce_str(g(row, "EMP_NAICS")),
        "employer_num_payroll":    coerce_int(g(row, "EMP_NUM_PAYROLL")),
        "employer_year_commenced": coerce_int(g(row, "EMP_YEAR_COMMENCED")),
        "atty_law_firm":           coerce_str(g(row, "ATTY_AG_LAW_FIRM_NAME")),
        "atty_last_name":          coerce_str(g(row, "ATTY_AG_LAST_NAME")),
        "atty_first_name":         coerce_str(g(row, "ATTY_AG_FIRST_NAME")),
        "atty_state":              coerce_str(g(row, "ATTY_AG_STATE")),
        "job_title":               coerce_str(g(row, "JOB_TITLE")),
        "soc_code":                coerce_str(g(row, "PWD_SOC_CODE")),
        "soc_title":               coerce_str(g(row, "PWD_SOC_TITLE")),
        "wage_from":               coerce_num(g(row, "JOB_OPP_WAGE_FROM")),
        "wage_to":                 coerce_num(g(row, "JOB_OPP_WAGE_TO")),
        "wage_per":                coerce_str(g(row, "JOB_OPP_WAGE_PER")),
        "worksite_city":           coerce_str(g(row, "PRIMARY_WORKSITE_CITY")),
        "worksite_state":          coerce_str(g(row, "PRIMARY_WORKSITE_STATE")),
        "worksite_postal_code":    coerce_str(g(row, "PRIMARY_WORKSITE_POSTAL_CODE")),
        "worksite_bls_area":       coerce_str(g(row, "PRIMARY_WORKSITE_BLS_AREA")),
        "pwd_number":              coerce_str(g(row, "JOB_OPP_PWD_NUMBER")),
        "fw_currently_employed":   coerce_str(g(row, "OTHER_REQ_IS_FW_CURRENTLY_WRK")),
        "is_multiple_locations":   coerce_str(g(row, "IS_MULTIPLE_LOCATIONS")),
        "employer_layoff":         coerce_str(g(row, "OTHER_REQ_EMP_LAYOFF")),
    }

# ── LCA ───────────────────────────────────────────────────────────────────────

LCA_SQL = """
INSERT INTO oflc_lca (
  case_number, fiscal_year, source_file, case_status, visa_class,
  received_date, decision_date, begin_date, end_date,
  employer_name, employer_state, employer_city, employer_postal_code,
  employer_fein, naics_code,
  law_firm_name, agent_last_name, agent_first_name, agent_state,
  job_title, soc_code, soc_title, full_time_position, total_worker_positions,
  wage_from, wage_to, wage_unit, prevailing_wage, pw_unit,
  pw_wage_level, pw_oes_year,
  worksite_city, worksite_state, worksite_postal_code,
  h1b_dependent, willful_violator
) VALUES (
  %(case_number)s, %(fiscal_year)s, %(source_file)s, %(case_status)s, %(visa_class)s,
  %(received_date)s, %(decision_date)s, %(begin_date)s, %(end_date)s,
  %(employer_name)s, %(employer_state)s, %(employer_city)s, %(employer_postal_code)s,
  %(employer_fein)s, %(naics_code)s,
  %(law_firm_name)s, %(agent_last_name)s, %(agent_first_name)s, %(agent_state)s,
  %(job_title)s, %(soc_code)s, %(soc_title)s, %(full_time_position)s, %(total_worker_positions)s,
  %(wage_from)s, %(wage_to)s, %(wage_unit)s, %(prevailing_wage)s, %(pw_unit)s,
  %(pw_wage_level)s, %(pw_oes_year)s,
  %(worksite_city)s, %(worksite_state)s, %(worksite_postal_code)s,
  %(h1b_dependent)s, %(willful_violator)s
) ON CONFLICT (case_number, fiscal_year) DO NOTHING
"""

def map_lca_row(row, fy, sf):
    return {
        "case_number":            coerce_str(g(row, "CASE_NUMBER")),
        "fiscal_year":            fy, "source_file": sf,
        "case_status":            coerce_str(g(row, "CASE_STATUS")),
        "visa_class":             coerce_str(g(row, "VISA_CLASS")),
        "received_date":          coerce_date(g(row, "RECEIVED_DATE")),
        "decision_date":          coerce_date(g(row, "DECISION_DATE")),
        "begin_date":             coerce_date(g(row, "BEGIN_DATE")),
        "end_date":               coerce_date(g(row, "END_DATE")),
        "employer_name":          coerce_str(g(row, "EMPLOYER_NAME")),
        "employer_state":         coerce_str(g(row, "EMPLOYER_STATE")),
        "employer_city":          coerce_str(g(row, "EMPLOYER_CITY")),
        "employer_postal_code":   coerce_str(g(row, "EMPLOYER_POSTAL_CODE")),
        "employer_fein":          coerce_str(g(row, "EMPLOYER_FEIN")),
        "naics_code":             coerce_str(g(row, "NAICS_CODE")),
        "law_firm_name":          coerce_str(g(row, "LAWFIRM_NAME_BUSINESS_NAME")),
        "agent_last_name":        coerce_str(g(row, "AGENT_ATTORNEY_LAST_NAME")),
        "agent_first_name":       coerce_str(g(row, "AGENT_ATTORNEY_FIRST_NAME")),
        "agent_state":            coerce_str(g(row, "AGENT_ATTORNEY_STATE")),
        "job_title":              coerce_str(g(row, "JOB_TITLE")),
        "soc_code":               coerce_str(g(row, "SOC_CODE")),
        "soc_title":              coerce_str(g(row, "SOC_TITLE")),
        "full_time_position":     coerce_str(g(row, "FULL_TIME_POSITION")),
        "total_worker_positions": coerce_int(g(row, "TOTAL_WORKER_POSITIONS")),
        "wage_from":              coerce_num(g(row, "WAGE_RATE_OF_PAY_FROM")),
        "wage_to":                coerce_num(g(row, "WAGE_RATE_OF_PAY_TO")),
        "wage_unit":              coerce_str(g(row, "WAGE_UNIT_OF_PAY")),
        "prevailing_wage":        coerce_num(g(row, "PREVAILING_WAGE")),
        "pw_unit":                coerce_str(g(row, "PW_UNIT_OF_PAY")),
        "pw_wage_level":          coerce_str(g(row, "PW_WAGE_LEVEL")),
        "pw_oes_year":            coerce_str(g(row, "PW_OES_YEAR")),
        "worksite_city":          coerce_str(g(row, "WORKSITE_CITY")),
        "worksite_state":         coerce_str(g(row, "WORKSITE_STATE")),
        "worksite_postal_code":   coerce_str(g(row, "WORKSITE_POSTAL_CODE")),
        "h1b_dependent":          coerce_str(g(row, "H_1B_DEPENDENT")),
        "willful_violator":       coerce_str(g(row, "WILLFUL_VIOLATOR")),
    }

# ── PW ────────────────────────────────────────────────────────────────────────

PW_SQL = """
INSERT INTO oflc_pw (
  case_number, fiscal_year, source_file, case_status, visa_class,
  received_date, determination_date,
  employer_name, employer_state, employer_city, employer_postal_code,
  employer_fein, naics_code,
  law_firm_name, agent_last_name, agent_first_name,
  job_title, soc_code, soc_title,
  suggested_soc_code, suggested_soc_title,
  pwd_soc_code, pwd_soc_title,
  o_net_code, o_net_title,
  emp_soc_codes, emp_soc_titles,
  pwd_wage_rate, pwd_unit, pw_wage_level, wage_source, wage_source_requested,
  survey_name, bls_area, pwd_wage_expiration_date,
  alt_pwd_wage_rate, alt_pwd_unit, alt_pwd_wage_level, alt_pwd_wage_source,
  worksite_city, worksite_state, worksite_postal_code
) VALUES (
  %(case_number)s, %(fiscal_year)s, %(source_file)s, %(case_status)s, %(visa_class)s,
  %(received_date)s, %(determination_date)s,
  %(employer_name)s, %(employer_state)s, %(employer_city)s, %(employer_postal_code)s,
  %(employer_fein)s, %(naics_code)s,
  %(law_firm_name)s, %(agent_last_name)s, %(agent_first_name)s,
  %(job_title)s, %(soc_code)s, %(soc_title)s,
  %(suggested_soc_code)s, %(suggested_soc_title)s,
  %(pwd_soc_code)s, %(pwd_soc_title)s,
  %(o_net_code)s, %(o_net_title)s,
  %(emp_soc_codes)s, %(emp_soc_titles)s,
  %(pwd_wage_rate)s, %(pwd_unit)s, %(pw_wage_level)s, %(wage_source)s, %(wage_source_requested)s,
  %(survey_name)s, %(bls_area)s, %(pwd_wage_expiration_date)s,
  %(alt_pwd_wage_rate)s, %(alt_pwd_unit)s, %(alt_pwd_wage_level)s, %(alt_pwd_wage_source)s,
  %(worksite_city)s, %(worksite_state)s, %(worksite_postal_code)s
) ON CONFLICT (case_number, fiscal_year) DO UPDATE SET
  suggested_soc_code   = EXCLUDED.suggested_soc_code,
  suggested_soc_title  = EXCLUDED.suggested_soc_title,
  pwd_soc_code         = EXCLUDED.pwd_soc_code,
  pwd_soc_title        = EXCLUDED.pwd_soc_title,
  o_net_code           = EXCLUDED.o_net_code,
  o_net_title          = EXCLUDED.o_net_title,
  emp_soc_codes        = EXCLUDED.emp_soc_codes,
  emp_soc_titles       = EXCLUDED.emp_soc_titles,
  wage_source_requested= EXCLUDED.wage_source_requested,
  survey_name          = EXCLUDED.survey_name,
  alt_pwd_wage_rate    = EXCLUDED.alt_pwd_wage_rate,
  alt_pwd_unit         = EXCLUDED.alt_pwd_unit,
  alt_pwd_wage_level   = EXCLUDED.alt_pwd_wage_level,
  alt_pwd_wage_source  = EXCLUDED.alt_pwd_wage_source
"""

def map_pw_row(row, fy, sf):
    emp = (coerce_str(g(row, "EMPLOYER_LEGAL_BUSINESS_NAME")) or
           coerce_str(g(row, "EMPLOYER_NAME")))
    soc_code  = (coerce_str(g(row, "PWD_SOC_CODE"))  or
                 coerce_str(g(row, "SUGGESTED_SOC_CODE")))
    soc_title = (coerce_str(g(row, "PWD_SOC_TITLE")) or
                 coerce_str(g(row, "SUGGESTED_SOC_TITLE")))
    return {
        "case_number":              coerce_str(g(row, "CASE_NUMBER")),
        "fiscal_year":              fy, "source_file": sf,
        "case_status":              coerce_str(g(row, "CASE_STATUS")),
        "visa_class":               coerce_str(g(row, "VISA_CLASS")),
        "received_date":            coerce_date(g(row, "RECEIVED_DATE")),
        "determination_date":       coerce_date(g(row, "DETERMINATION_DATE",
                                                     "PREVAIL_WAGE_DETERM_DATE")),
        "employer_name":            emp,
        "employer_state":           coerce_str(g(row, "EMPLOYER_STATE")),
        "employer_city":            coerce_str(g(row, "EMPLOYER_CITY")),
        "employer_postal_code":     coerce_str(g(row, "EMPLOYER_POSTAL_CODE")),
        "employer_fein":            coerce_str(g(row, "EMPLOYER_FEIN")),
        "naics_code":               coerce_str(g(row, "NAICS_CODE")),
        "law_firm_name":            coerce_str(g(row, "LAWFIRM_NAME_BUSINESS_NAME")),
        "agent_last_name":          coerce_str(g(row, "AGENT_ATTORNEY_LAST_NAME")),
        "agent_first_name":         coerce_str(g(row, "AGENT_ATTORNEY_FIRST_NAME")),
        "job_title":                coerce_str(g(row, "JOB_TITLE")),
        "soc_code":                 soc_code,
        "soc_title":                soc_title,
        "suggested_soc_code":       coerce_str(g(row, "SUGGESTED_SOC_CODE")),
        "suggested_soc_title":      coerce_str(g(row, "SUGGESTED_SOC_TITLE")),
        "pwd_soc_code":             coerce_str(g(row, "PWD_SOC_CODE")),
        "pwd_soc_title":            coerce_str(g(row, "PWD_SOC_TITLE")),
        "o_net_code":               coerce_str(g(row, "O_NET_CODE", "O_NET_CODE_COMBO")),
        "o_net_title":              coerce_str(g(row, "O_NET_TITLE", "O_NET_TITLE_COMBO")),
        "emp_soc_codes":            coerce_str(g(row, "EMP_SOC_CODES")),
        "emp_soc_titles":           coerce_str(g(row, "EMP_SOC_TITLES")),
        "pwd_wage_rate":            coerce_num(g(row, "PWD_WAGE_RATE", "H2B_HIGHEST_PWD")),
        "pwd_unit":                 coerce_str(g(row, "PWD_UNIT_OF_PAY")),
        "pw_wage_level":            coerce_str(g(row, "PWD_OES_WAGE_LEVEL")),
        "wage_source":              coerce_str(g(row, "PWD_WAGE_SOURCE")),
        "wage_source_requested":    coerce_str(g(row, "WAGE_SOURCE_REQUESTED")),
        "survey_name":              coerce_str(g(row, "SURVEY_NAME", "PWD_SURVEY_NAME")),
        "bls_area":                 coerce_str(g(row, "BLS_AREA")),
        "pwd_wage_expiration_date": coerce_date(g(row, "PWD_WAGE_EXPIRATION_DATE")),
        "alt_pwd_wage_rate":        coerce_num(g(row, "ALT_PWD_WAGE_RATE")),
        "alt_pwd_unit":             coerce_str(g(row, "ALT_PWD_UNIT_OF_PAY")),
        "alt_pwd_wage_level":       coerce_str(g(row, "ALT_PWD_OES_WAGE_LEVEL")),
        "alt_pwd_wage_source":      coerce_str(g(row, "ALT_PWD_WAGE_SOURCE")),
        "worksite_city":            coerce_str(g(row, "PRIMARY_WORKSITE_CITY")),
        "worksite_state":           coerce_str(g(row, "PRIMARY_WORKSITE_STATE")),
        "worksite_postal_code":     coerce_str(g(row, "PRIMARY_WORKSITE_POSTAL_CODE")),
    }

# ── Core loader ───────────────────────────────────────────────────────────────

def load_file(conn, path: Path, program: str, dry_run: bool) -> int:
    fy  = fy_from_path(path)
    sf  = path.name
    rel = str(path.relative_to(DATA_DIR))
    print(f"  {rel}  ", end="", flush=True)

    df = pd.read_excel(path, engine="openpyxl", dtype=str)
    df.columns = [c.strip().upper() for c in df.columns]

    mapper, sql = {
        "perm": (map_perm_row, PERM_SQL),
        "lca":  (map_lca_row,  LCA_SQL),
        "pw":   (map_pw_row,   PW_SQL),
    }[program]

    rows = [mapper(r, fy, sf) for _, r in df.iterrows()
            if coerce_str(r.get("CASE_NUMBER"))]

    if dry_run:
        print(f"({len(rows):,} rows — dry run)")
        return len(rows)

    inserted = 0
    with conn.cursor() as cur:
        for i in range(0, len(rows), BATCH):
            psycopg2.extras.execute_batch(cur, sql, rows[i:i+BATCH], page_size=BATCH)
            inserted += len(rows[i:i+BATCH])
    conn.commit()
    print(f"({len(rows):,} rows, {inserted:,} upserted)")
    return inserted


def lca_files_deduped() -> list:
    """Per FY, prefer Q4 (annual cumulative). Avoids double-counting."""
    fy_map: dict = {}
    for p in sorted((DATA_DIR / "LCA").rglob("LCA_Disclosure_Data_FY*.xlsx")):
        fy = fy_from_path(p)
        fy_map.setdefault(fy, []).append(p)
    result = []
    for fy, files in sorted(fy_map.items()):
        for q in ("Q4", "Q3", "Q2", "Q1"):
            match = [f for f in files if q in f.parent.name]
            if match:
                result.append(match[0])
                break
    return result


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Ingest OFLC disclosure data")
    parser.add_argument("--program", choices=["perm","lca","pw","all"], default="all")
    parser.add_argument("--reset",   action="store_true",
                        help="Truncate tables before loading")
    parser.add_argument("--dry-run", action="store_true",
                        help="Count rows only, no DB writes")
    args = parser.parse_args()

    conn = None if args.dry_run else get_conn()

    if args.reset and not args.dry_run:
        targets = (["oflc_perm","oflc_lca","oflc_pw"]
                   if args.program == "all"
                   else [f"oflc_{args.program}"])
        with conn.cursor() as cur:
            for t in targets:
                cur.execute(f"TRUNCATE {t} RESTART IDENTITY")
        conn.commit()
        print(f"Reset: truncated {', '.join(targets)}")

    programs = ["perm","lca","pw"] if args.program == "all" else [args.program]
    total = 0

    for program in programs:
        print(f"\n{'='*60}\n {program.upper()} Disclosure Data\n{'='*60}")

        if program == "perm":
            files = sorted((DATA_DIR / "PERM").rglob("PERM_Disclosure_Data_FY*.xlsx"))
        elif program == "lca":
            files = lca_files_deduped()
        else:
            files = sorted((DATA_DIR / "PW").rglob("PW_Disclosure_Data_FY*.xlsx"))

        if not files:
            print(f"  No files found — check {DATA_DIR / program.upper()}")
            continue

        for f in files:
            total += load_file(conn, f, program, args.dry_run)

    if conn:
        conn.close()

    print(f"\n{'='*60}")
    print(f" Done — {total:,} rows {'counted' if args.dry_run else 'processed'}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
