"""Detect missing inputs the PERM verifier needs, for interactive repair.

Produces the `needs_input` list attached to engine.verify_data() output:
fields the rule tiers consume that are blank or unreadable, so the UI can
pop a sidebar, collect the values from the user, and re-verify.

Appendix A (foreign-national) information is deliberately excluded — per
product decision the sidebar never asks for it.

Entry shape (stable contract for the frontend and Graphite):
  {
    "scope":  "form" | "pwd",
    "path":   dotted path into the form/pwd dict,
    "label":  human label,
    "section_item": 9089/9141 item reference,
    "kind":   "text" | "money" | "number" | "date" | "select",
    "options": [...]            # only for kind == "select"
    "reason": "missing",        # extensible: "low_confidence" later
    "why":    what checks are degraded without it,
  }
"""
from __future__ import annotations

from .rules import _get

YES_NO = ["Yes", "No"]
PER_UNITS = ["Hour", "Week", "Bi-Weekly", "Month", "Year"]

# (path, section_item, label, kind, options, why)
FORM_FIELDS = [
    ("A_employer.legal_business_name", "A.1", "Employer legal business name",
     "text", None, "employer identity cross-check vs PWD (T3-012)"),
    ("A_employer.address1", "A.3", "Employer address", "text", None,
     "completeness (T1-001)"),
    ("A_employer.city", "A.5", "Employer city", "text", None,
     "completeness (T1-001)"),
    ("A_employer.state", "A.6", "Employer state", "text", None,
     "completeness (T1-001)"),
    ("A_employer.postal_code", "A.7", "Employer ZIP", "text", None,
     "completeness (T1-001)"),
    ("A_employer.country", "A.8", "Employer country", "text", None,
     "completeness (T1-001)"),
    ("A_employer.phone", "A.10", "Employer phone", "text", None,
     "completeness (T1-001)"),
    ("A_employer.fein", "A.12", "Employer FEIN", "text", None,
     "FEIN match vs PWD (T3-011)"),
    ("A_employer.naics_code", "A.13", "NAICS code", "text", None,
     "completeness (T1-001)"),
    ("A_employer.num_employees_in_area", "A.14",
     "Employees in area of intended employment", "number", None,
     "EPT threshold basis (T5-025); completeness (T1-001)"),
    ("A_employer.year_commenced_business", "A.15",
     "Year business commenced", "number", None, "completeness (T1-001)"),
    ("A_employer.closely_held_ownership_interest", "A.16",
     "Closely held / FW ownership interest", "select", YES_NO,
     "Appendix C trigger checks"),
    ("A_employer.familial_relationship", "A.17",
     "Familial relationship with FW", "select", YES_NO,
     "Appendix C trigger checks"),
    ("B_poc.last_name", "B.1", "Point of contact last name", "text", None,
     "notice-signer match (T5-032); completeness"),
    ("B_poc.first_name", "B.2", "Point of contact first name", "text", None,
     "notice-signer match (T5-032); completeness"),
    ("B_poc.job_title", "B.4", "Point of contact job title", "text", None,
     "completeness (T1-001)"),
    ("B_poc.email", "B.14", "Point of contact email", "text", None,
     "completeness (T1-001)"),
    ("D_foreign_worker_flags.appendix_a_attached", "D.1",
     "Appendix A attached", "select", YES_NO, "T1-002"),
    ("D_foreign_worker_flags.dual_representation", "D.2",
     "Dual representation", "select", YES_NO, "completeness (T1-001)"),
    ("E_job_wage.pwd_case_number", "E.1", "PWD case number", "text", None,
     "PWD linkage (T3-010) — Tier 3 halts without it"),
    ("E_job_wage.offered_wage_from", "E.3", "Offered wage (from)", "money",
     None, "wage floor vs PWD (T3-001); recruitment wage match (T5-024)"),
    ("E_job_wage.wage_per", "E.4", "Offered wage per", "select", PER_UNITS,
     "wage annualization for T3-001 / T5-024"),
    ("F_worksite.address1", "F.a.2", "Worksite address", "text", None,
     "worksite match vs PWD (T3-014)"),
    ("F_worksite.city", "F.a.4", "Worksite city", "text", None,
     "worksite match vs PWD (T3-014)"),
    ("F_worksite.county", "F.a.5", "Worksite county", "text", None,
     "OES area resolution (T3-014, geo)"),
    ("F_worksite.state", "F.a.6", "Worksite state", "text", None,
     "OES area resolution (T3-014); EPT law lookup (T5-025)"),
    ("F_worksite.postal_code", "F.a.7", "Worksite ZIP", "text", None,
     "worksite match vs PWD (T3-014)"),
    ("F_worksite.msa_oes_area_code", "F.a.8", "MSA/OES area code", "text",
     None, "completeness (T1-001)"),
    ("F_worksite.msa_oes_area_title", "F.a.8a", "MSA/OES area title", "text",
     None, "OES area match vs PWD (T3-014)"),
    ("G_job_info.full_time_35hrs", "G.1", "Full time (35+ hrs)", "select",
     YES_NO, "completeness (T1-001)"),
    ("G_job_info.live_in_domestic", "G.2", "Live-in domestic", "select",
     YES_NO, "completeness (T1-001)"),
    ("G_job_info.fw_currently_employed", "G.4",
     "FW currently employed by employer", "select", YES_NO,
     "Kellogg routing (T3-032)"),
    ("G_job_info.relying_solely_on_experience_with_employer", "G.5",
     "Relying solely on experience with employer", "select", YES_NO,
     "656.17(i)(3) checks (T1-010d)"),
    ("G_job_info.live_on_premises", "G.6", "Live on premises", "select",
     YES_NO, "completeness (T1-001)"),
    ("G_job_info.combination_of_occupations", "G.7",
     "Combination of occupations", "select", YES_NO,
     "PWD-derived answer check (T3-033)"),
    ("G_job_info.foreign_language", "G.8", "Foreign language required",
     "select", YES_NO, "PWD-derived answer check (T3-034)"),
    ("G_job_info.exceeds_svp", "G.9", "Requirements exceed SVP", "select",
     YES_NO, "O*NET SVP checks"),
    ("G_job_info.credentialing_service", "G.10",
     "Credential evaluation accepted", "select", YES_NO,
     "foreign-equivalency check (T3-035)"),
    ("G_job_info.employer_received_payment", "G.11",
     "Employer received payment", "select", YES_NO,
     "completeness (T1-001)"),
    ("G_job_info.layoff_6mo", "G.12", "Layoff in last 6 months", "select",
     YES_NO, "completeness (T1-001)"),
]

# PWD-side fields — only requested when a 9141 was supplied but the
# extractor came back empty on a field Tier 3 consumes.
PWD_FIELDS = [
    ("pwd_case_number", "9141", "PWD case number", "text", None,
     "linkage to 9089 E.1 (T3-010)"),
    ("employer_fein", "9141 A", "Employer FEIN on PWD", "text", None,
     "FEIN match (T3-011)"),
    ("employer_name", "9141 A", "Employer name on PWD", "text", None,
     "name match (T3-012)"),
    ("pw_minimum", "9141 wage", "Prevailing wage (minimum)", "money", None,
     "wage floor (T3-001) — check cannot run without it"),
    ("pw_per", "9141 wage", "Prevailing wage per", "select", PER_UNITS,
     "wage annualization (T3-001)"),
    ("validity_from", "9141 validity", "PWD validity start", "date", None,
     "656.40(c) filing/validity postures (T3-005)"),
    ("validity_to", "9141 validity", "PWD validity end", "date", None,
     "656.40(c) filing/validity postures (T3-005, T3-013)"),
    ("soc_code", "9141", "SOC code", "text", None,
     "O*NET job-zone checks (T2-014/T4-007)"),
    ("bls_area", "9141", "BLS/OES area", "text", None,
     "OES area match (T3-014)"),
    ("worksite_county", "9141 worksite", "PWD worksite county", "text", None,
     "OES area resolution (T3-014, geo)"),
    ("worksite_state", "9141 worksite", "PWD worksite state", "text", None,
     "OES area resolution (T3-014, geo)"),
]


def _blank(v):
    return v is None or (isinstance(v, str) and not v.strip())


def needs_input(form, pwd=None):
    """List of missing inputs the verifier would use if supplied."""
    out = []
    for path, item, label, kind, options, why in FORM_FIELDS:
        if _blank(_get(form, path)):
            e = {"scope": "form", "path": path, "label": label,
                 "section_item": item, "kind": kind, "reason": "missing",
                 "why": why}
            if options:
                e["options"] = options
            out.append(e)
    if pwd is not None:
        for path, item, label, kind, options, why in PWD_FIELDS:
            if _blank(pwd.get(path)):
                e = {"scope": "pwd", "path": path, "label": label,
                     "section_item": item, "kind": kind,
                     "reason": "missing", "why": why}
                if options:
                    e["options"] = options
                out.append(e)
    return out
