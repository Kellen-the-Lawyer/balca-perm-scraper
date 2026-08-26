"""Build canonical ETA-9141 JSON from matched DOL disclosure rows."""

from __future__ import annotations

from typing import Any, Mapping

from .dol_eta9089 import _date, _phone, _postal, _text, _value, _yn


def _combined(*values: Any) -> str | None:
    parts = [_text(value) for value in values]
    return "; ".join(part for part in parts if part) or None


_DUTY_LIBRARY = {
    "37-2011": (
        "Clean and sanitize production, storage, and common areas; operate floor "
        "care and sanitation equipment; prepare and apply approved cleaning "
        "solutions; remove waste; restock supplies; and document completed work "
        "while following safety and contamination-control procedures."
    ),
    "47-2061": (
        "Clean demolition and construction areas; remove debris and salvageable "
        "materials; load, unload, and move tools and supplies; prepare work areas; "
        "assist craft workers as directed; and follow site, fall-protection, and "
        "hazardous-material safety procedures."
    ),
    "43-6011": (
        "Coordinate calendars, meetings, correspondence, records, and office "
        "supplies; prepare and proofread documents and reports; answer and route "
        "inquiries; maintain electronic and paper files; enter data; and support "
        "routine administrative workflows."
    ),
    "25-2022": (
        "Plan and deliver Mandarin-language instruction; prepare lessons and "
        "instructional materials; assess student comprehension and language "
        "proficiency; maintain attendance and academic records; communicate with "
        "families and staff; and adapt instruction to student needs."
    ),
    "11-3021": (
        "Lead software engineering projects and teams; translate product and "
        "operational needs into technical plans; review architecture and code; "
        "coordinate releases and incident response; establish engineering "
        "standards; mentor engineers; and monitor the reliability, security, and "
        "performance of cloud-based systems."
    ),
    "15-1252": (
        "Design, develop, test, deploy, and maintain software applications and "
        "services; analyze requirements; write and review code; troubleshoot "
        "defects and production issues; automate testing and deployment; document "
        "technical decisions; and collaborate with product and engineering teams."
    ),
    "17-3011": (
        "Develop medical-planning layouts and technical drawings for healthcare "
        "facilities; coordinate room, equipment, circulation, and clinical workflow "
        "requirements; create and revise design documentation; participate in user "
        "meetings; and coordinate plans with architects, engineers, and consultants."
    ),
    "19-4099": (
        "Prepare samples and reagents; perform routine laboratory tests and "
        "instrument checks; record, review, and report results; maintain laboratory "
        "equipment and inventories; investigate variances; and follow quality, "
        "safety, documentation, and contamination-control procedures."
    ),
    "13-1082": (
        "Lead customer implementation and service-delivery programs; gather and "
        "translate business requirements; coordinate technical deployments; track "
        "service performance and escalations; analyze operational data; prepare "
        "status reports; and guide customers through adoption and issue resolution."
    ),
    "15-1211": (
        "Define product requirements and priorities for consumer-commerce systems; "
        "analyze user, market, and operational data; write product specifications; "
        "coordinate design and engineering delivery; manage launches; evaluate "
        "product performance; and communicate plans and results to stakeholders."
    ),
}


def _synthetic_duties(pwd: Mapping[str, Any]) -> str:
    title = _text(_value(pwd, "JOB_TITLE")) or "the job offered"
    soc = _text(_value(pwd, "PWD_SOC_CODE")) or ""
    duties = _DUTY_LIBRARY.get(soc)
    if duties:
        return duties
    return (
        f"Perform the customary duties of {title}; plan and complete assigned work; "
        "use the tools and methods normally associated with the occupation; "
        "coordinate with coworkers and stakeholders; maintain required records; "
        "and follow applicable quality and safety procedures."
    )


def _job_duties(
    pwd: Mapping[str, Any],
    perm: Mapping[str, Any],
    supplied: str | None = None,
) -> tuple[str, bool]:
    disclosed = _text(supplied) or _text(_value(pwd, "JOB_DUTIES")) or _text(
        _value(perm, "JOB_DUTIES")
    )
    if disclosed:
        return disclosed, False
    return _synthetic_duties(pwd), True


def build_eta9141_form_data(
    pwd: Mapping[str, Any],
    perm: Mapping[str, Any],
    *,
    job_duties: str | None = None,
) -> dict[str, Any]:
    """Map a matched PWD/PERM disclosure pair into ETA-9141 sections."""

    pwd_number = _text(_value(pwd, "CASE_NUMBER"))
    perm_pwd_number = _text(_value(perm, "JOB_OPP_PWD_NUMBER"))
    if not pwd_number or pwd_number != perm_pwd_number:
        raise ValueError("PERM JOB_OPP_PWD_NUMBER must match PW CASE_NUMBER")

    duties, duties_synthetic = _job_duties(pwd, perm, job_duties)
    requested_source = _text(_value(pwd, "WAGE_SOURCE_REQUESTED"))
    requested_source_upper = (requested_source or "").upper()
    dba_sca = requested_source_upper in {"DBA", "SCA"}
    survey_requested = "SURVEY" in requested_source_upper
    special_required = _yn(_value(pwd, "SPECIAL_SKILLS_REQUIREMENTS"))
    alternate_required = _yn(_value(pwd, "ALTERNATIVE_REQUIREMENTS"))

    supervised_soc = _combined(
        _value(pwd, "EMP_SOC_CODES"), _value(pwd, "EMP_SOC_TITLES")
    )
    second_degree = _combined(
        _value(pwd, "SECOND_EDUCATION_MAJOR"),
        _value(pwd, "SECOND_EDUCATION_LEVEL"),
    )
    county = _text(_value(pwd, "PRIMARY_WORKSITE_COUNTY")) or _text(
        _value(perm, "PRIMARY_WORKSITE_COUNTY")
    )

    wage_level = _text(_value(pwd, "PWD_OES_WAGE_LEVEL"))
    if not wage_level:
        wage_level = "N/A"
    alternate_wage_level = _text(_value(pwd, "ALT_PWD_OES_WAGE_LEVEL"))
    if _value(pwd, "ALT_PWD_WAGE_RATE") is not None and not alternate_wage_level:
        alternate_wage_level = "N/A"

    return {
        "meta": {
            "pwd_case_number": pwd_number,
            "case_status": _text(_value(pwd, "CASE_STATUS")),
            "received_date": _date(_value(pwd, "RECEIVED_DATE")),
            "determination_date": _date(_value(pwd, "PREVAIL_WAGE_DETERM_DATE")),
            "expiration_date": _date(_value(pwd, "PWD_WAGE_EXPIRATION_DATE")),
        },
        "visa_class": _text(_value(pwd, "VISA_CLASS")) or "PERM",
        "requestor_contact": {
            "last_name": _text(_value(pwd, "EMPLOYER_POC_LAST_NAME")),
            "first_name": _text(_value(pwd, "EMPLOYER_POC_FIRST_NAME")),
            "middle_name": _text(_value(pwd, "EMPLOYER_POC_MIDDLE_NAME")),
            "job_title": _text(_value(pwd, "EMPLOYER_POC_JOB_TITLE")),
            "address1": _text(_value(pwd, "EMPLOYER_POC_ADDRESS1")),
            "address2": _text(_value(pwd, "EMPLOYER_POC_ADDRESS2")),
            "city": _text(_value(pwd, "EMPLOYER_POC_CITY")),
            "state": _text(_value(pwd, "EMPLOYER_POC_STATE")),
            "postal_code": _postal(_value(pwd, "EMPLOYER_POC_POSTAL_CODE")),
            "country": _text(_value(pwd, "EMPLOYER_POC_COUNTRY")),
            "province": _text(_value(pwd, "EMPLOYER_POC_PROVINCE")),
            "phone": _phone(_value(pwd, "EMPLOYER_POC_PHONE")),
            "extension": _text(_value(pwd, "EMPLOYER_POC_PHONE_EXT")),
            "email": _text(_value(pwd, "EMPLOYER_POC_EMAIL")),
        },
        "employer": {
            "legal_business_name": _text(
                _value(pwd, "EMPLOYER_LEGAL_BUSINESS_NAME")
            ),
            "trade_name": _text(_value(pwd, "TRADE_NAME_DBA")),
            "address1": _text(_value(pwd, "EMPLOYER_ADDRESS_1")),
            "address2": _text(_value(pwd, "EMPLOYER_ADDRESS_2")),
            "city": _text(_value(pwd, "EMPLOYER_CITY")),
            "state": _text(_value(pwd, "EMPLOYER_STATE")),
            "postal_code": _postal(_value(pwd, "EMPLOYER_POSTAL_CODE")),
            "country": _text(_value(pwd, "EMPLOYER_COUNTRY")),
            "province": _text(_value(pwd, "EMPLOYER_PROVINCE")),
            "phone": _phone(_value(pwd, "EMPLOYER_PHONE")),
            "extension": _text(_value(pwd, "EMPLOYER_EXTENSION")),
            "fein": _text(_value(pwd, "EMPLOYER_FEIN")),
            "naics_code": _text(_value(pwd, "NAICS_CODE")),
        },
        "attorney_agent": {
            "representation_type": _text(_value(pwd, "TYPE_OF_REPRESENTATION"))
            or "None",
            "last_name": _text(_value(pwd, "AGENT_ATTORNEY_LAST_NAME")),
            "first_name": _text(_value(pwd, "AGENT_ATTORNEY_FIRST_NAME")),
            "middle_name": _text(_value(pwd, "AGENT_ATTORNEY_MIDDLE_NAME")),
            "address1": _text(_value(pwd, "AGENT_ATTORNEY_ADDRESS_1")),
            "address2": _text(_value(pwd, "AGENT_ATTORNEY_ADDRESS_2")),
            "city": _text(_value(pwd, "AGENT_ATTORNEY_CITY")),
            "state": _text(_value(pwd, "AGENT_ATTORNEY_STATE")),
            "postal_code": _postal(_value(pwd, "AGENT_ATTORNEY_POSTAL_CODE")),
            "country": _text(_value(pwd, "AGENT_ATTORNEY_COUNTRY")),
            "province": _text(_value(pwd, "AGENT_ATTORNEY_PROVINCE")),
            "phone": _phone(_value(pwd, "AGENT_ATTORNEY_PHONE")),
            "extension": _text(_value(pwd, "AGENT_ATTORNEY_PHONE_EXT")),
            "email": _text(_value(pwd, "AGENT_ATTORNEY_EMAIL_ADDRESS")),
            "law_firm_name": _text(_value(pwd, "LAWFIRM_NAME_BUSINESS_NAME")),
            "law_firm_fein": _text(_value(pwd, "LAWFIRM_FEIN"))
            or _text(_value(perm, "ATTY_AG_FEIN")),
        },
        "wage_source": {
            "acwia": _yn(_value(pwd, "COVERED_BY_ACWIA")),
            "acwia_higher_education": _yn(
                _value(pwd, "ACWIA_INST_HIGHER_EDUCATION")
            ),
            "acwia_affiliated_nonprofit": _yn(
                _value(pwd, "ACWIA_AFFILIATED_NON_PROFIT")
            ),
            "acwia_research_org": _yn(_value(pwd, "ACWIA_RESEARCH_ORG")),
            "acwia_status_changed": _yn(_value(pwd, "ACWIA_STATUS_CHANGED")),
            "professional_sports": _yn(_value(pwd, "PROF_SPORTS_LEAGUE")),
            "cba": _yn(_value(pwd, "CBA")),
            "dba_sca_requested": "Yes" if dba_sca else "No",
            "requested_source": requested_source,
            "survey_requested": "Yes" if survey_requested else "No",
            "survey_name": _text(_value(pwd, "SURVEY_NAME")),
            "survey_date": _date(_value(pwd, "SURVEY_PUBLICATION_DATE")),
        },
        "job_offer": {
            "job_title": _text(_value(pwd, "JOB_TITLE")),
            "job_duties": duties,
            "job_duties_continuation": "",
            "supervises_employees": _yn(_value(pwd, "SUPERVISE_OTHER_EMP")),
            "supervised_soc": supervised_soc,
            "suggested_soc_code": _text(_value(pwd, "SUGGESTED_SOC_CODE")),
            "suggested_soc_title": _text(_value(pwd, "SUGGESTED_SOC_TITLE")),
            "supervisor_job_title": _text(_value(pwd, "SUPERVISOR_JOB_TITLE")),
            "travel_required": _yn(_value(pwd, "TRAVEL_REQUIRED")),
            "travel_details": _text(_value(pwd, "TRAVEL_DETAILS")),
            "other_bls_area": _yn(_value(pwd, "OTHER_WORKSITE_LOCATION")),
            "worksite": {
                "address1": _text(_value(pwd, "PRIMARY_WORKSITE_ADDRESS_1")),
                "address2": _text(_value(pwd, "PRIMARY_WORKSITE_ADDRESS_2")),
                "city": _text(_value(pwd, "PRIMARY_WORKSITE_CITY")),
                "state": _text(_value(pwd, "PRIMARY_WORKSITE_STATE")),
                "county": county,
                "postal_code": _postal(_value(pwd, "PRIMARY_WORKSITE_POSTAL_CODE")),
            },
        },
        "requirements": {
            "education_level": _text(_value(pwd, "REQUIRED_EDUCATION_LEVEL")),
            "other_degree": _text(_value(pwd, "REQUIRED_OTHER_DEGREE")),
            "majors": _text(_value(pwd, "REQUIRED_EDUCATION_MAJOR")),
            "second_degree_required": _yn(_value(pwd, "SECOND_EDUCATION")),
            "second_degree": second_degree,
            "training_required": _yn(_value(pwd, "REQUIRED_TRAINING")),
            "training_months": _text(_value(pwd, "REQUIRED_TRAINING_MONTHS")),
            "training_field": _text(_value(pwd, "REQUIRED_TRAINING_NAME")),
            "experience_required": _yn(_value(pwd, "REQUIRED_EXPERIENCE")),
            "experience_months": _text(_value(pwd, "REQUIRED_EXPERIENCE_MONTHS")),
            "experience_occupation": _text(_value(pwd, "REQUIRED_OCCUPATION")),
            "special_required": special_required,
            "license": _text(_value(pwd, "SPEC_REQ_LICENSE_CERT")),
            "foreign_language": _text(_value(pwd, "SPEC_REQ_FOREIGN_LANG")),
            "residency": _text(_value(pwd, "SPEC_REQ_RES_FELLOW")),
            "other_special": _text(_value(pwd, "SPEC_REQ_OTHER")),
        },
        "alternate_requirements": {
            "accepted": alternate_required,
            "education_level": _text(_value(pwd, "ALT_EDUCATION_LEVEL")),
            "other_degree": _text(_value(pwd, "ALT_OTHER_DEGREE")),
            "majors": _text(_value(pwd, "ALT_EDUCATION_MAJOR")),
            "training_accepted": _yn(_value(pwd, "ALT_TRAINING")),
            "training_months": _text(_value(pwd, "ALT_TRAINING_MONTHS")),
            "training_field": _text(_value(pwd, "ALT_TRAINING_NAME")),
            "experience_accepted": _yn(_value(pwd, "ALT_EXPERIENCE")),
            "experience_months": _text(_value(pwd, "ALT_EXPERIENCE_MONTHS")),
            "special_required": _yn(_value(pwd, "ALT_SPECIAL_SKILLS")),
            "license": _text(_value(pwd, "ALT_LICENSE_CERT")),
            "foreign_language": _text(_value(pwd, "ALT_FOREIGN_LANGUAGE")),
            "residency": _text(_value(pwd, "ALT_RES_FELLOWSHIP")),
            "other_special": _text(_value(pwd, "ALT_OTHER_REQ")),
        },
        "determination": {
            "soc_code": _text(_value(pwd, "PWD_SOC_CODE")),
            "soc_title": _text(_value(pwd, "PWD_SOC_TITLE")),
            "onet_code": _text(_value(pwd, "O_NET_CODE")),
            "onet_title": _text(_value(pwd, "O_NET_TITLE")),
            "combination_soc_code": _text(_value(pwd, "O_NET_CODE_COMBO")),
            "combination_soc_title": _text(_value(pwd, "O_NET_TITLE_COMBO")),
            "prevailing_wage": _value(pwd, "PWD_WAGE_RATE"),
            "wage_unit": _text(_value(pwd, "PWD_UNIT_OF_PAY")),
            "wage_level": wage_level,
            "wage_source": _text(_value(pwd, "PWD_WAGE_SOURCE")),
            "survey_name": _text(_value(pwd, "PWD_SURVEY_NAME")),
            "alternate_prevailing_wage": _value(pwd, "ALT_PWD_WAGE_RATE"),
            "alternate_wage_unit": _text(_value(pwd, "ALT_PWD_UNIT_OF_PAY")),
            "alternate_wage_level": alternate_wage_level,
            "alternate_wage_source": _text(_value(pwd, "ALT_PWD_WAGE_SOURCE")),
            "alternate_survey_name": _text(_value(pwd, "ALT_PWD_SURVEY_NAME")),
            "bls_area": _text(_value(pwd, "BLS_AREA")),
            "h2b_highest_wage": _value(pwd, "H2B_HIGHEST_PWD"),
            "notes": _text(_value(pwd, "WAGE_DET_NOTES")),
        },
        "synthetic_fields": (
            ["job_offer.job_duties"] if duties_synthetic else []
        ),
    }
