"""Build canonical ETA-9089 JSON from matched raw DOL disclosure rows."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Mapping


def _value(row: Mapping[str, Any], key: str, default: Any = None) -> Any:
    value = row.get(key, default)
    if value is None:
        return default
    try:
        if value != value:  # NaN without importing pandas
            return default
    except TypeError:
        pass
    return value


def _yn(value: Any, *, na_when_missing: bool = False) -> str | None:
    if value is None:
        return "N/A" if na_when_missing else None
    text = str(value).strip().upper()
    if text in {"Y", "YES", "TRUE", "1"}:
        return "Yes"
    if text in {"N", "NO", "FALSE", "0"}:
        return "No"
    if text in {"N/A", "NA", "NOT APPLICABLE"}:
        return "N/A"
    return str(value)


def _date(value: Any, *, month_only: bool = False) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).replace("T00:00:00", "")
        parsed = None
        for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
            try:
                parsed = datetime.strptime(text, pattern)
                break
            except ValueError:
                continue
        if parsed is None:
            return str(value)
    return parsed.strftime("%m/%Y" if month_only else "%m/%d/%Y")


def _phone(value: Any) -> str | None:
    if value in (None, ""):
        return None
    digits = "".join(character for character in str(value) if character.isdigit())
    if len(digits) == 11 and digits[0] == "1":
        return f"+1 ({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return str(value)


def _postal(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text.zfill(5) if text.isdigit() and len(text) < 5 else text


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _occupation_type(value: Any) -> str | None:
    mapping = {
        "Professional occupation": "1a_professional",
        "Non-professional": "1b_nonprofessional",
        "College/University Teacher": "1c_college_university_teacher",
        "Schedule A": "1d_schedule_a_sheepherder",
        "None/Professional Athlete": "1e_professional_athlete",
    }
    return mapping.get(str(value), _text(value))


def _notice_fields(perm: Mapping[str, Any]) -> list[str]:
    mapping = {
        "NOTICE_POST_BARGAIN_REP": "1a_bargaining_rep",
        "NOTICE_POST_BARGAIN_REP_PHYSICAL": "1b_physical_notice",
        "NOTICE_POST_BARGAIN_REP_ELECTRONIC": "1c_electronic_notice",
        "NOTICE_POST_BARGAIN_REP_INHOUSE": "1d_inhouse_media",
        "NOTICE_POST_BARGAIN_REP_PRIVATE": "1e_private_household",
        "NOTICE_POST_EMP_NOT_POSTED": "1f_did_not_post",
    }
    return [target for source, target in mapping.items() if _yn(_value(perm, source)) == "Yes"]


def _additional_steps(perm: Mapping[str, Any]) -> dict[str, dict[str, str | None]]:
    columns = {
        "job_fair": ("RECR_OCC_JOB_FAIR_FROM", "RECR_OCC_JOB_FAIR_TO"),
        "employer_website": ("RECR_OCC_EMP_WEBSITE_FROM", "RECR_OCC_EMP_WEBSITE_TO"),
        "job_search_website": ("RECR_OCC_JOB_SEARCH_FROM", "RECR_OCC_JOB_SEARCH_TO"),
        "on_campus": ("RECR_OCC_ON_CAMPUS_FROM", "RECR_OCC_ON_CAMPUS_TO"),
        "trade_org": ("RECR_OCC_TRADE_ORG_FROM", "RECR_OCC_TRADE_ORG_TO"),
        "private_firm": ("RECR_OCC_PRIVATE_EMP_FROM", "RECR_OCC_PRIVATE_EMP_TO"),
        "employee_referral": ("RECR_OCC_EMP_REFERRAL_FROM", "RECR_OCC_EMP_REFERRAL_TO"),
        "campus_placement": ("RECR_OCC_CAMPUS_PLACEMENT_FROM", "RECR_OCC_CAMPUS_PLACEMENT_TO"),
        "local_ethnic_newspaper": ("RECR_OCC_LOCAL_NEWSPAPER_FROM", "RECR_OCC_LOCAL_NEWSPAPER_TO"),
        "radio_tv": ("RECR_OCC_RADIO_AD_FROM", "RECR_OCC_RADIO_AD_TO"),
    }
    return {
        key: {"from": _date(_value(perm, start)), "to": _date(_value(perm, end))}
        for key, (start, end) in columns.items()
    }


def _clean_disclosure_text(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    if text.startswith('="') and text.endswith('"'):
        text = text[2:-1]
    return re.sub(r"[ \t]+", " ", text).strip()


def _requirement_items(pwd: Mapping[str, Any]) -> list[dict[str, str]]:
    """Return atomic primary-route PWD requirements for Appendix A evidence."""

    items: list[dict[str, str]] = []

    def add(identifier: str, category: str, text: str | None) -> None:
        if text:
            items.append({"id": identifier, "category": category, "text": text})

    degree = _clean_disclosure_text(_value(pwd, "REQUIRED_EDUCATION_LEVEL"))
    major = _clean_disclosure_text(_value(pwd, "REQUIRED_EDUCATION_MAJOR"))
    if degree and degree.lower() != "none":
        add(
            "education",
            "education",
            f"Education: {degree} degree"
            + (f" in {major}" if major else ""),
        )
    if _yn(_value(pwd, "SECOND_EDUCATION")) == "Yes":
        second_level = _clean_disclosure_text(
            _value(pwd, "SECOND_EDUCATION_LEVEL")
        )
        second_major = _clean_disclosure_text(
            _value(pwd, "SECOND_EDUCATION_MAJOR")
        )
        add(
            "second_education",
            "education",
            "Second degree: "
            + " in ".join(part for part in (second_level, second_major) if part),
        )
    if _yn(_value(pwd, "REQUIRED_TRAINING")) == "Yes":
        months = _clean_disclosure_text(_value(pwd, "REQUIRED_TRAINING_MONTHS"))
        name = _clean_disclosure_text(_value(pwd, "REQUIRED_TRAINING_NAME"))
        add(
            "training",
            "training",
            f"Training: {months or 'specified'} months"
            + (f" in {name}" if name else ""),
        )
    if _yn(_value(pwd, "REQUIRED_EXPERIENCE")) == "Yes":
        months = _clean_disclosure_text(_value(pwd, "REQUIRED_EXPERIENCE_MONTHS"))
        occupation = _clean_disclosure_text(_value(pwd, "REQUIRED_OCCUPATION"))
        add(
            "experience",
            "experience",
            f"Experience: {months or 'specified'} months"
            + (f" in {occupation}" if occupation else ""),
        )

    for identifier, label, column in (
        ("license", "License/certification", "SPEC_REQ_LICENSE_CERT"),
        ("foreign_language", "Foreign language", "SPEC_REQ_FOREIGN_LANG"),
        ("residency", "Residency/fellowship", "SPEC_REQ_RES_FELLOW"),
    ):
        add(
            identifier,
            "special",
            (
                f"{label}: {_clean_disclosure_text(_value(pwd, column))}"
                if _clean_disclosure_text(_value(pwd, column))
                else None
            ),
        )

    other = _clean_disclosure_text(_value(pwd, "SPEC_REQ_OTHER"))
    if other:
        raw_parts = re.split(r"\n+|(?=\([a-zivx]+\)\s)|;\s+(?=(?:and\s+)?\(?[a-zivx]+\)?)", other)
        parts = []
        for part in raw_parts:
            cleaned = part.strip(" -;\n\r\t")
            if not cleaned or cleaned.lower().startswith("[***note"):
                continue
            parts.append(cleaned)
        for index, part in enumerate(parts or [other], 1):
            add(f"special_{index}", "special", f"Special requirement: {part}")
    return items


def _month_shift(month_year: str, months: int) -> str:
    month, year = (int(part) for part in month_year.split("/"))
    serial = year * 12 + month - 1 + months
    return f"{serial % 12 + 1:02d}/{serial // 12:04d}"


def _month_allocations(total: int, count: int) -> list[int]:
    if total <= 0:
        return [24]
    count = max(1, min(count, total))
    base, remainder = divmod(total, count)
    return [base + (1 if index < remainder else 0) for index in range(count)]


def _synthetic_employers(count: int) -> list[dict[str, str]]:
    rows = [
        ("NORTHSTAR PROFESSIONAL SOLUTIONS", "2200 SAMPLE STREET", "CHICAGO", "60602", "IL"),
        ("CEDAR RIDGE TECHNOLOGIES", "4100 TRAINING BOULEVARD", "AUSTIN", "78701", "TX"),
        ("ATLAS PROJECT SERVICES", "875 EXAMPLE ROAD", "DENVER", "80202", "CO"),
    ]
    return [
        {
            "employer_name": name,
            "address1": address,
            "address2": "",
            "city": city,
            "postal_code": postal,
            "country": "UNITED STATES OF AMERICA",
            "state": state,
        }
        for name, address, city, postal, state in rows[:count]
    ]


def synthetic_foreign_national(
    perm: Mapping[str, Any],
    pwd: Mapping[str, Any],
    *,
    evidence_pattern: str = "single_employer",
    employer_count: int = 1,
) -> dict[str, Any]:
    """Create fictional Appendix A evidence tied to every primary PWD requirement."""

    degree = _text(_value(pwd, "REQUIRED_EDUCATION_LEVEL")) or "None"
    major = _text(_value(pwd, "REQUIRED_EDUCATION_MAJOR")) or ""
    experience_months = int(_value(pwd, "REQUIRED_EXPERIENCE_MONTHS", 0) or 0)
    occupation = _text(_value(pwd, "REQUIRED_OCCUPATION")) or _text(
        _value(perm, "JOB_TITLE")
    )
    requirements = _requirement_items(pwd)
    if evidence_pattern == "single_employer" or experience_months <= 0:
        employer_count = 1
    employer_count = max(1, min(employer_count, 3))
    employers = _synthetic_employers(employer_count)
    allocations = _month_allocations(experience_months, employer_count)

    employment_requirements = [
        item for item in requirements if item["category"] not in {"education", "training"}
    ]
    assigned: list[list[dict[str, str]]] = [[] for _ in employers]
    for index, item in enumerate(employment_requirements):
        target = index % len(employers) if evidence_pattern == "split_skills" else 0
        assigned[target].append(item)
    if evidence_pattern == "multiple_employers":
        for index in range(1, len(employers)):
            assigned[index].append(
                {
                    "id": f"experience_segment_{index + 1}",
                    "category": "experience_segment",
                    "text": "Related occupational experience contributing to the cumulative duration requirement",
                }
            )

    work_experience = []
    skills = []
    end = "12/2023"
    for index, (employer, credited_months) in enumerate(zip(employers, allocations)):
        start = _month_shift(end, -credited_months + 1)
        assigned_text = "; ".join(item["text"] for item in assigned[index])
        if not assigned_text:
            assigned_text = (
                f"Occupational proficiency in {occupation or 'the job offered'}"
            )
        duties = (
            f"Performed progressively responsible duties in {occupation or 'the job offered'}. "
            f"Work included and demonstrated: {assigned_text}. Coordinated assigned "
            "projects, used occupation-specific tools and methods, maintained records, "
            "and communicated results to coworkers and stakeholders."
        )[:3500]
        experience = {
            **employer,
            "job_title": occupation or "Related Position",
            "start": start,
            "end": end,
            "present": "No",
            "hours_per_week": "40",
            "duties": duties,
            "credited_months": credited_months,
            "evidence_requirement_ids": [item["id"] for item in assigned[index]],
        }
        work_experience.append(experience)
        skills.append(
            {
                "provider": employer["employer_name"],
                "country": employer["country"],
                "state": employer["state"],
                "description": (
                    "PWD requirements evidenced by this employer: " + assigned_text
                )[:1500],
                "experience_index": index,
                "requirement_ids": [item["id"] for item in assigned[index]],
            }
        )
        end = _month_shift(start, -1)

    academic_requirements = [
        item for item in requirements if item["category"] in {"education", "training"}
    ]
    if academic_requirements:
        skills.append(
            {
                "provider": "NORTHLAKE TRAINING UNIVERSITY",
                "country": "INDIA",
                "state": "N/A",
                "description": (
                    "PWD education/training requirements evidenced in Sections B/C: "
                    + "; ".join(item["text"] for item in academic_requirements)
                )[:1500],
                "experience_index": 0,
                "requirement_ids": [item["id"] for item in academic_requirements],
            }
        )

    training = []
    if _yn(_value(pwd, "REQUIRED_TRAINING")) == "Yes":
        training_months = int(_value(pwd, "REQUIRED_TRAINING_MONTHS", 0) or 0)
        training_end = "12/2017"
        training.append(
            {
                "provider": "NORTHLAKE TRAINING INSTITUTE",
                "training_name": _clean_disclosure_text(
                    _value(pwd, "REQUIRED_TRAINING_NAME")
                )
                or "Occupation-related training",
                "licenses_attained": "",
                "start": _month_shift(training_end, -max(training_months, 1) + 1),
                "end": training_end,
                "awarded": training_end,
            }
        )
    license_requirement = _clean_disclosure_text(
        _value(pwd, "SPEC_REQ_LICENSE_CERT")
    )
    if license_requirement:
        training.append(
            {
                "provider": "SYNTHETIC LICENSING AUTHORITY",
                "training_name": "Professional credential",
                "licenses_attained": license_requirement,
                "start": "01/2018",
                "end": "05/2018",
                "awarded": "05/2018",
            }
        )

    return {
        "contact": {
            "last_name": "TRAINING-SAMPLE",
            "first_name": "ALEX",
            "middle_name": "TEST",
            "address1": "100 EXAMPLE AVENUE",
            "address2": "APT 1",
            "city": "CHICAGO",
            "state": "IL",
            "postal_code": "60601",
            "country": "UNITED STATES OF AMERICA",
            "province": "N/A",
            "dob": "01/15/1990",
            "class_of_admission": "H-1B",
            "a_number": "",
            "country_of_birth": "INDIA",
            "country_of_citizenship": "INDIA",
        },
        "education": [
            {
                "degree": degree,
                "other_degree_specify": "",
                "majors": major,
                "institution": "NORTHLAKE TRAINING UNIVERSITY",
                "country": "INDIA",
                "month_year_attained": "05/2018",
            }
        ],
        "training": training,
        "skills": skills,
        "work_experience": work_experience,
        "synthetic": True,
        "evidence_pattern": evidence_pattern,
        "requirements": requirements,
        "required_experience_months": experience_months,
        "credited_experience_months": sum(allocations),
    }


def build_eta9089_form_data(
    perm: Mapping[str, Any],
    pwd: Mapping[str, Any],
    *,
    foreign_national: Mapping[str, Any] | None = None,
    evidence_pattern: str = "single_employer",
    employer_count: int = 1,
) -> dict[str, Any]:
    """Map a matched raw disclosure pair into the current ETA-9089 sections."""

    perm_pwd = _text(_value(perm, "JOB_OPP_PWD_NUMBER"))
    pwd_number = _text(_value(pwd, "CASE_NUMBER"))
    if not perm_pwd or perm_pwd != pwd_number:
        raise ValueError("PERM JOB_OPP_PWD_NUMBER must match PW CASE_NUMBER")

    fn = dict(
        foreign_national
        or synthetic_foreign_national(
            perm,
            pwd,
            evidence_pattern=evidence_pattern,
            employer_count=employer_count,
        )
    )
    live_in = _yn(_value(perm, "OTHER_REQ_IS_LIVEIN_HOUSEHOLD"))
    currently = _yn(_value(perm, "OTHER_REQ_IS_FW_CURRENTLY_WRK"))
    additional = _yn(_value(perm, "IS_MULTIPLE_LOCATIONS"))
    appendix_b = _yn(_value(perm, "IS_APPENDIX_B_ATTACHED"))

    return {
        "meta": {
            "perm_case_number": _text(_value(perm, "CASE_NUMBER")),
            "case_status": _text(_value(perm, "CASE_STATUS")),
            "received_date": _date(_value(perm, "RECEIVED_DATE")),
            "decision_date": _date(_value(perm, "DECISION_DATE")),
        },
        "A_employer": {
            "legal_business_name": _text(_value(perm, "EMP_BUSINESS_NAME")),
            "dba": _text(_value(perm, "EMP_TRADE_NAME")),
            "address1": _text(_value(perm, "EMP_ADDR1")),
            "address2": _text(_value(perm, "EMP_ADDR2")),
            "city": _text(_value(perm, "EMP_CITY")),
            "state": _text(_value(perm, "EMP_STATE")),
            "postal_code": _postal(_value(perm, "EMP_POSTCODE")),
            "country": _text(_value(perm, "EMP_COUNTRY")),
            "province": _text(_value(perm, "EMP_PROVINCE")),
            "phone": _phone(_value(perm, "EMP_PHONE")),
            "extension": _text(_value(perm, "EMP_PHONEEXT")),
            "fein": _text(_value(perm, "EMP_FEIN")),
            "naics_code": _text(_value(perm, "EMP_NAICS")),
            "num_employees_in_area": _text(_value(perm, "EMP_NUM_PAYROLL")),
            "year_commenced_business": _text(_value(perm, "EMP_YEAR_COMMENCED")),
            "closely_held_ownership_interest": _yn(_value(perm, "EMP_WORKER_INTEREST")),
            "familial_relationship": _yn(_value(perm, "EMP_RELATIONSHIP_WORKER")),
        },
        "B_poc": {
            "last_name": _text(_value(perm, "EMP_POC_LAST_NAME")),
            "first_name": _text(_value(perm, "EMP_POC_FIRST_NAME")),
            "middle_name": _text(_value(perm, "EMP_POC_MIDDLE_NAME")),
            "job_title": _text(_value(perm, "EMP_POC_JOB_TITLE")),
            "address1": _text(_value(perm, "EMP_POC_ADDR1")),
            "address2": _text(_value(perm, "EMP_POC_ADDR2")),
            "city": _text(_value(perm, "EMP_POC_CITY")),
            "state": _text(_value(perm, "EMP_POC_STATE")),
            "postal_code": _postal(_value(perm, "EMP_POC_POSTAL_CODE")),
            "country": _text(_value(perm, "EMP_POC_COUNTRY")),
            "province": _text(_value(perm, "EMP_POC_PROVINCE")),
            "phone": _phone(_value(perm, "EMP_POC_PHONE")),
            "extension": _text(_value(perm, "EMP_POC_PHONEEXT")),
            "email": _text(_value(perm, "EMP_POC_EMAIL")),
        },
        "C_attorney_agent": {
            "representation_type": _text(_value(perm, "ATTY_AG_REP_TYPE")) or "None",
            "last_name": _text(_value(perm, "ATTY_AG_LAST_NAME")),
            "first_name": _text(_value(perm, "ATTY_AG_FIRST_NAME")),
            "middle_name": _text(_value(perm, "ATTY_AG_MIDDLE_NAME")),
            "address1": _text(_value(perm, "ATTY_AG_ADDRESS1")),
            "address2": _text(_value(perm, "ATTY_AG_ADDRESS2")),
            "city": _text(_value(perm, "ATTY_AG_CITY")),
            "state": _text(_value(perm, "ATTY_AG_STATE")),
            "postal_code": _postal(_value(perm, "ATTY_AG_POSTAL_CODE")),
            "country": _text(_value(perm, "ATTY_AG_COUNTRY")),
            "province": _text(_value(perm, "ATTY_AG_PROVINCE")),
            "phone": _phone(_value(perm, "ATTY_AG_PHONE")),
            "extension": _text(_value(perm, "ATTY_AG_PHONE_EXT")),
            "email": _text(_value(perm, "ATTY_AG_EMAIL")),
            "law_firm_name": _text(_value(perm, "ATTY_AG_LAW_FIRM_NAME")),
            "law_firm_fein": _text(_value(perm, "ATTY_AG_FEIN")),
            "state_bar_number": _text(_value(perm, "ATTY_AG_STATE_BAR_NUMBER")),
            "state_of_good_standing": _text(_value(perm, "ATTY_AG_GOOD_STANDING_STATE")),
            "highest_court_name": _text(_value(perm, "ATTY_AG_GOOD_STANDING_COURT")),
        },
        "D_foreign_worker_flags": {
            "appendix_a_attached": _yn(_value(perm, "FW_INFO_APPX_A_ATTACHED")),
            "dual_representation": _yn(_value(perm, "FW_INFO_ATTY_OR_AGENT")),
        },
        "E_job_wage": {
            "pwd_case_number": perm_pwd,
            "supervised_recruitment_9141_attached": "N/A",
            "offered_wage_from": _value(perm, "JOB_OPP_WAGE_FROM"),
            "offered_wage_to": _value(perm, "JOB_OPP_WAGE_TO"),
            "wage_per": _text(_value(perm, "JOB_OPP_WAGE_PER")),
            "wage_conditions": _text(_value(perm, "JOB_OPP_WAGE_CONDITIONS")),
        },
        "F_worksite": {
            "worksite_type": _text(_value(perm, "PRIMARY_WORKSITE_TYPE")),
            "address1": _text(_value(perm, "PRIMARY_WORKSITE_ADDR1")),
            "address2": _text(_value(perm, "PRIMARY_WORKSITE_ADDR2")),
            "city": _text(_value(perm, "PRIMARY_WORKSITE_CITY")),
            "county": _text(_value(perm, "PRIMARY_WORKSITE_COUNTY")),
            "state": _text(_value(perm, "PRIMARY_WORKSITE_STATE")),
            "postal_code": _postal(_value(perm, "PRIMARY_WORKSITE_POSTAL_CODE")),
            "msa_oes_area_code": None,
            "msa_oes_area_title": _text(_value(perm, "PRIMARY_WORKSITE_BLS_AREA")),
            "additional_worksites": additional,
            "appendix_b_attached": appendix_b if additional == "Yes" else "N/A",
            "other_geographic_areas": None,
        },
        "G_job_info": {
            "full_time_35hrs": _yn(_value(perm, "OTHER_REQ_IS_FULLTIME_EMP")),
            "live_in_domestic": live_in,
            "live_in_1yr_experience": _yn(
                _value(perm, "OTHER_REQ_IS_PAID_EXPERIENCE"),
                na_when_missing=live_in == "No",
            ),
            "live_in_contract_executed": _yn(
                _value(perm, "OTHER_REQ_IS_FW_EXECUTED_CONT"),
                na_when_missing=live_in == "No",
            ),
            "live_in_contract_copy_provided": _yn(
                _value(perm, "OTHER_REQ_IS_EMP_PROVIDED_CONT"),
                na_when_missing=live_in == "No",
            ),
            "accept_foreign_degree_equivalent": _yn(
                _value(perm, "OTHER_REQ_ACCEPT_DIPLOMA_PWD"),
                na_when_missing=True,
            ),
            "fw_currently_employed": currently,
            "fw_qualifies_only_by_alternative_reqs": _yn(
                _value(perm, "OTHER_REQ_IS_FW_QUALIFY"), na_when_missing=True
            ),
            "kellogg_suitable_combination": _text(_value(perm, "OTHER_REQ_EMP_WILL_ACCEPT")),
            "relying_solely_on_experience_with_employer": _yn(
                _value(perm, "OTHER_REQ_EMP_RELY_EXP")
            ),
            "experience_substantially_comparable": _yn(
                _value(perm, "OTHER_REQ_FW_GAIN_EXP"), na_when_missing=True
            ),
            "employer_paid_training": _yn(
                _value(perm, "OTHER_REQ_EMP_PAY_EDUCATION"), na_when_missing=True
            ),
            "live_on_premises": _yn(_value(perm, "OTHER_REQ_JOB_EMP_PREMISES")),
            "combination_of_occupations": _yn(_value(perm, "OTHER_REQ_JOB_COMBO_OCCUP")),
            "foreign_language": _yn(_value(perm, "OTHER_REQ_JOB_FOREIGN_LANGUAGE")),
            "exceeds_svp": _yn(_value(perm, "OTHER_REQ_JOB_REQ_EXCEED"), na_when_missing=True),
            "credentialing_service": _yn(
                _value(perm, "OTHER_REQ_EMP_USE_CREDENTIAL"), na_when_missing=True
            ),
            "employer_received_payment": _yn(_value(perm, "OTHER_REQ_EMP_REC_PAYMENT")),
            "layoff_6mo": _yn(_value(perm, "OTHER_REQ_EMP_LAYOFF")),
        },
        "H_recruitment": {
            "supervised_recruitment": _yn(_value(perm, "RECR_INFO_RECRUIT_SUPERVISED_REQ")),
            "occupation_type": _occupation_type(_value(perm, "OCCUPATION_TYPE")),
            "swa_job_order_start": _date(_value(perm, "RECR_INFO_JOB_START_DATE")),
            "swa_job_order_end": _date(_value(perm, "RECR_INFO_JOB_END_DATE")),
            "sunday_edition_exists": _yn(
                _value(perm, "RECR_INFO_IS_NEWSPAPER_SUNDAY"), na_when_missing=True
            ),
            "ad1_newspaper_name": _text(_value(perm, "RECR_INFO_NEWSPAPER_NAME")),
            "ad1_date": _date(_value(perm, "RECR_INFO_AD_DATE1")),
            "ad2_type": _text(_value(perm, "RECR_INFO_RECRUIT_AD_TYPE")),
            "ad2_name": _text(_value(perm, "RECR_INFO_NEWSPAPER_NAME2")),
            "ad2_date": _date(_value(perm, "RECR_INFO_AD_DATE2")),
            "additional_steps": _additional_steps(perm),
            "notice_of_posting": _notice_fields(perm),
        },
        "I_attestations": {
            "certify_labor_condition_statements": _yn(_value(perm, "EMP_CERTIFY_COMPLIANCE")),
        },
        "J_preparer": {
            "last_name": _text(_value(perm, "DECL_PREP_LAST_NAME")),
            "first_name": _text(_value(perm, "DECL_PREP_FIRST_NAME")),
            "middle_name": _text(_value(perm, "DECL_PREP_MIDDLE_NAME")),
            "fein": _text(_value(perm, "DECL_PREP_LAWFIRM_FEIN")),
            "business_name": _text(_value(perm, "DECL_PREP_FIRM_BUSINESS_NAME")),
            "email": _text(_value(perm, "DECL_PREP_EMAIL")),
        },
        "appendix_A": fn,
        "appendix_B": {},
        "appendix_C": {},
        "appendix_D": {},
    }
