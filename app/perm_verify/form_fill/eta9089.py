"""Canonical ETA-9089 JSON to official fillable DOL PDF mappings."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from .acroform import fill_interactive_pdf


TEMPLATES = {
    "application": "ETA-9089-Application-for-Perm-Employment-Certification-Expires02-28-29 (1).pdf",
    "appendix_a": "ETA-9089-AppendixA-Expires02-28-29.pdf",
    "appendix_b": "ETA-9089-AppendixB-Expires02-28-29.pdf",
    "appendix_c": "ETA-9089-AppendixC-Expires02-28-29.pdf",
    "appendix_d": "ETA-9089-AppendixD-Expires02-28-29.pdf",
}


BASE_TEXT_FIELDS = {
    "A_employer.legal_business_name": "1  Legal Business Name",
    "A_employer.dba": "2  Trade NameDoing Business As DBA if applicable",
    "A_employer.address1": "3  Address 1",
    "A_employer.address2": "4  Address 2 apartmentsuitefloor and number",
    "A_employer.city": "5  City",
    "A_employer.state": "6  State",
    "A_employer.postal_code": "7  Postal Code",
    "A_employer.country": "8  Country",
    "A_employer.province": "9  Province",
    "A_employer.phone": "10  Telephone Number",
    "A_employer.extension": "11  Extension",
    "A_employer.fein": "12  Federal Employer Identification Number FEIN from IRS",
    "A_employer.naics_code": "13  NAICS Code",
    "A_employer.num_employees_in_area": (
        "14 Enter Number of current employees on payroll in the area of "
        "intended employment Here"
    ),
    "A_employer.year_commenced_business": (
        "15 Enter Year Commenced Business (if household, year issued FEIN) here"
    ),
    "B_poc.last_name": "1  Contacts Last family Name",
    "B_poc.first_name": "2  First given Name",
    "B_poc.middle_name": "3  Middle Names",
    "B_poc.job_title": "4 Contacts Job Title",
    "B_poc.address1": "5  Address 1",
    "B_poc.address2": "6  Address 2 apartmentsuitefloor and number",
    "B_poc.city": "7  City",
    "B_poc.state": "8  State",
    "B_poc.postal_code": "9  Postal Code",
    "B_poc.country": "10  Country",
    "B_poc.province": "11  Province",
    "B_poc.phone": "12  Telephone Number",
    "B_poc.extension": "13  Extension",
    "B_poc.email": "14 Business Email Address",
    "C_attorney_agent.last_name": "2  Attorney or Agents Last family Name",
    "C_attorney_agent.first_name": "3  First given Name",
    "C_attorney_agent.middle_name": "4  Middle Names",
    "C_attorney_agent.address1": "5  Address 1_2",
    "C_attorney_agent.address2": "6  Address 2 apartmentsuitefloor and number_2",
    "C_attorney_agent.city": "7  City_2",
    "C_attorney_agent.state": "8  State_2",
    "C_attorney_agent.postal_code": "9  Postal Code_2",
    "C_attorney_agent.country": "10  Country_2",
    "C_attorney_agent.province": "11  Province_2",
    "C_attorney_agent.phone": "12  Telephone Number_2",
    "C_attorney_agent.extension": "13 Extension",
    "C_attorney_agent.email": "14 Law FirmBusiness Email Address",
    "C_attorney_agent.law_firm_name": "15  Law FirmBusiness Name",
    "C_attorney_agent.law_firm_fein": "16  Law FirmBusiness FEIN",
    "C_attorney_agent.state_bar_number": "17  State Bar Numbers",
    "C_attorney_agent.state_of_good_standing": (
        "18  State of highest court where attorney is in good standing"
    ),
    "C_attorney_agent.highest_court_name": (
        "19  Name of the highest state court where attorney is in good standing"
    ),
    "E_job_wage.pwd_case_number": (
        "1 Enter the valid Prevailing Wage Determination PWD case number issued "
        "by the Department of Labor to identify the job opportunity and prevailing "
        "wages covered by this application"
    ),
    "E_job_wage.wage_conditions": (
        "Additional conditions about the offered wage. (Enter up to 500 characters) §"
    ),
    "F_worksite.address1": "2  Worksite Address",
    "F_worksite.address2": "3  Worksite Address  apartmentsuitefloor and number",
    "F_worksite.city": "4  City",
    "F_worksite.county": "5  County",
    "F_worksite.state": "6  StateDistrictTerritory",
    "F_worksite.postal_code": "7  Postal Code_2",
    "F_worksite.msa_oes_area_code": "8  MSAOES Area Code",
    "F_worksite.msa_oes_area_title": "8a  MSA NameOES Area Title",
    "F_worksite.other_geographic_areas": (
        "1  Identify the geographic areas where work will be performed For example "
        "this can include a listing of cities or townshipsstates countiesstates or "
        "states located within a geographic region up to 1500 characters"
    ),
    "H_recruitment.swa_job_order_start": "1a  Start date of SWA job order",
    "H_recruitment.swa_job_order_end": "1b  End date of SWA job order",
    "H_recruitment.ad1_newspaper_name": (
        "2a  Name of newspaper of general circulation in which an advertisement was placed"
    ),
    "H_recruitment.ad1_date": "2b  Advertisement date",
    "H_recruitment.ad2_name": (
        "3a  Name of newspaper or professional journal in which an advertisement was placed"
    ),
    "H_recruitment.ad2_date": "3b  Advertisement Date",
    "J_preparer.last_name": "1  Last family Name",
    "J_preparer.first_name": "2  First given Name_2",
    "J_preparer.middle_name": "3  Middle Names_2",
    "J_preparer.fein": "4  Law FirmBusiness FEIN",
    "J_preparer.business_name": "5  Law FirmBusiness Name",
    "J_preparer.email": "6  Law FirmBusiness Email Address",
}


YES_NO_FIELDS = {
    "A_employer.closely_held_ownership_interest": (("16 Yes", "Yes"), ("16 No", "No")),
    "A_employer.familial_relationship": (("17 Yes", "Yes_2"), ("17 No", "No_2")),
    "D_foreign_worker_flags.appendix_a_attached": (("D 1 Yes", "Yes_3"), ("D 1 No", "No_3")),
    "D_foreign_worker_flags.dual_representation": (("D 2 Yes", "Yes_4"), ("D 2 No", "No_4")),
    "G_job_info.full_time_35hrs": (("1 Yes", "On"), ("1 No", "On")),
    "G_job_info.live_in_domestic": (("2 Yes", "On"), ("2 No", "On")),
    "G_job_info.fw_currently_employed": (("4 Yes", "On"), ("4 No", "On")),
    "G_job_info.relying_solely_on_experience_with_employer": (("5 Yes", "On"), ("5 No", "On")),
    "G_job_info.live_on_premises": (("6 Yes", "On"), ("6 No", "On")),
    "G_job_info.combination_of_occupations": (("7 Yes", "On"), ("7 No", "On")),
    "G_job_info.foreign_language": (("8 Yes", "On"), ("8 No", "On")),
    "G_job_info.employer_received_payment": (("11 Yes", "On"), ("11 No", "On")),
    "G_job_info.layoff_6mo": (("12 Yes", "On"), ("12 No", "On")),
    "I_attestations.certify_labor_condition_statements": (("Yes", "Yes_17"), ("No", "No_17")),
}


YES_NO_NA_FIELDS = {
    "E_job_wage.supervised_recruitment_9141_attached": (
        ("E 2 Yes", "Yes_5"), ("E 2 No", "No_5"), ("E 2 N/A", "NA")
    ),
    "F_worksite.appendix_b_attached": (
        ("B 2 Yes", "Yes_6"), ("B 2 No", "No_6"), ("B 2 N/A", "NA_2")
    ),
    "G_job_info.live_in_1yr_experience": (
        ("2a Yes", "Yes_7"), ("2a No", "No_7"), ("2a N/A", "NA_3")
    ),
    "G_job_info.live_in_contract_executed": (
        ("2b Yes", "Yes_8"), ("2b No", "No_8"), ("2b N/A", "NA_4")
    ),
    "G_job_info.live_in_contract_copy_provided": (
        ("2c Yes", "Yes_9"), ("2c No", "No_9"), ("2c N/A", "NA_5")
    ),
    "G_job_info.accept_foreign_degree_equivalent": (
        ("3 Yes", "Yes_10"), ("3 No", "No_10"), ("3 N/A", "NA_6")
    ),
    "G_job_info.fw_qualifies_only_by_alternative_reqs": (
        ("4a Yes", "Yes_11"), ("4a No", "No_11"), ("4a N/A", "NA_7")
    ),
    "G_job_info.experience_substantially_comparable": (
        ("5a Yes", "Yes_12"), ("5a No", "No_12"), ("5a N/A", "NA_8")
    ),
    "G_job_info.employer_paid_training": (
        ("5b Yes", "Yes_13"), ("5b No", "No_13"), ("5b N/A", "NA_9")
    ),
    "G_job_info.exceeds_svp": (
        ("9 Yes", "Yes_14"), ("9 No", "No_14"), ("9 N/A", "NA_10")
    ),
    "G_job_info.credentialing_service": (
        ("10 Yes", "Yes_15"), ("10 No", "No_15"), ("10 N/A", "NA_11")
    ),
    "H_recruitment.sunday_edition_exists": (
        ("2 c Yes", "Yes_16"), ("2 c No", "No_16"), ("2 c N/A", "NA_12")
    ),
}


def _get(data: Mapping[str, Any], path: str, default: Any = None) -> Any:
    value: Any = data
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return default
        value = value[part]
    return value


def _normalized_choice(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "yes" if value else "no"
    text = str(value).strip().lower().replace("_", " ")
    if text in {"y", "yes", "true", "1"}:
        return "yes"
    if text in {"n", "no", "false", "0"}:
        return "no"
    if text in {"n/a", "na", "not applicable"}:
        return "na"
    return text


def _mark_choice(
    values: dict[str, Any],
    selected: Any,
    options: tuple[tuple[str, str], ...],
) -> None:
    choice = _normalized_choice(selected)
    for index, (field, export) in enumerate(options):
        option = ("yes", "no", "na")[index]
        values[field] = export if choice == option else "Off"


def _mark_independent(
    values: dict[str, Any], field: str, selected: bool, export: str = "On"
) -> None:
    values[field] = export if selected else "Off"


def _money_parts(value: Any) -> tuple[str, str]:
    if value in (None, ""):
        return "", ""
    try:
        amount = Decimal(str(value).replace(",", "").replace("$", ""))
    except InvalidOperation as exc:
        raise ValueError(f"invalid wage amount: {value!r}") from exc
    amount = amount.quantize(Decimal("0.01"))
    dollars, cents = f"{amount:.2f}".split(".")
    return dollars, cents


def _base_values(data: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for path, field in BASE_TEXT_FIELDS.items():
        value = _get(data, path)
        values[field] = "" if value is None else value

    for path, options in YES_NO_FIELDS.items():
        value = _get(data, path)
        if value is not None:
            _mark_choice(values, value, options)
    for path, options in YES_NO_NA_FIELDS.items():
        value = _get(data, path)
        if value is not None:
            _mark_choice(values, value, options)

    representation = _normalized_choice(_get(data, "C_attorney_agent.representation_type"))
    for option in ("Attorney", "Agent", "None"):
        _mark_independent(values, option, representation == option.lower())

    worksite = _normalized_choice(_get(data, "F_worksite.worksite_type"))
    worksite_options = {
        "business premises": "Business premises",
        "business premises": "Business premises",
        "business_premises": "Business premises",
        "employee residence": (
            "Employees private residence when work is performed directly out of the residence"
        ),
        "employees private residence": (
            "Employees private residence when work is performed directly out of the residence"
        ),
        "employee_residence": (
            "Employees private residence when work is performed directly out of the residence"
        ),
        "no specific worksite": "No one specific worksite address or physical location",
        "no_specific_worksite": "No one specific worksite address or physical location",
        "private household": (
            "Employer's private household (includes live-in and domestic household worker)"
        ),
        "employer_household": (
            "Employer's private household (includes live-in and domestic household worker)"
        ),
    }
    for field in set(worksite_options.values()):
        _mark_independent(values, field, worksite_options.get(worksite) == field)

    additional = _get(data, "F_worksite.additional_worksites")
    if additional is not None:
        _mark_choice(values, additional, (("B 1 Yes", "On"), ("B 1 No", "On")))

    kellogg = _normalized_choice(_get(data, "G_job_info.kellogg_suitable_combination"))
    _mark_independent(values, "I ACCEPT", kellogg in {"i accept", "accept"})
    _mark_independent(values, "I DO NOT ACCEPT", kellogg in {"i do not accept", "do not accept"})

    from_dollars, from_cents = _money_parts(_get(data, "E_job_wage.offered_wage_from"))
    to_dollars, to_cents = _money_parts(_get(data, "E_job_wage.offered_wage_to"))
    values.update({
        "Enter From The Wage Offer Dollar Amount Here": from_dollars,
        "Enter From The Wage Offer Cents Amount Here": from_cents,
        "Enter To The Wage Offer Dollar Amount Here": to_dollars,
        "Enter To The Wage Offer Cents Amount Here": to_cents,
    })
    wage_per = _normalized_choice(_get(data, "E_job_wage.wage_per"))
    wage_per_fields = {
        "hour": "Enter Hour here",
        "week": "Enter Week here",
        "bi-weekly": "Enter BiWeekly here",
        "biweekly": "Enter BiWeekly here",
        "month": "Enter Month here",
        "year": "Enter Year here",
        "annual": "Enter Year here",
    }
    selected_wage_field = wage_per_fields.get(wage_per)
    values["Enter Hour here"] = (
        "X" if selected_wage_field == "Enter Hour here" else ""
    )
    for field in {
        "Enter Week here",
        "Enter BiWeekly here",
        "Enter Month here",
        "Enter Year here",
    }:
        _mark_independent(values, field, selected_wage_field == field)

    supervised = _normalized_choice(_get(data, "H_recruitment.supervised_recruitment"))
    _mark_choice(
        values,
        supervised,
        (("Check this box to indicate Yes", "On"), ("Check this box to indicate No", "On")),
    )

    occupation = _normalized_choice(_get(data, "H_recruitment.occupation_type"))
    occupation_map = {
        "1a professional": "Mark 1a Here",
        "1a_professional": "Mark 1a Here",
        "professional occupation": "Mark 1a Here",
        "1b nonprofessional": "Mark 1b here",
        "1b_nonprofessional": "Mark 1b here",
        "non-professional": "Mark 1b here",
        "1c college university teacher": "Mark 1c Here",
        "1c_college_university_teacher": "Mark 1c Here",
        "college/university teacher": "Mark 1c Here",
        "1d schedule a sheepherder": "Mark 1d Here",
        "1d_schedule_a_sheepherder": "Mark 1d Here",
        "schedule a": "Mark 1d Here",
        "1e professional athlete": "Mark 1e Here",
        "1e_professional_athlete": "Mark 1e Here",
    }
    for field in occupation_map.values():
        values[field] = "X" if occupation_map.get(occupation) == field else ""

    ad_type = _normalized_choice(_get(data, "H_recruitment.ad2_type"))
    ad_type_fields = {
        "newspaper": "Newspaper of general circulation",
        "newspaper of general circulation": "Newspaper of general circulation",
        "professional journal": "Professional journal",
        "na": "NA_13",
    }
    selected_ad_type_field = ad_type_fields.get(ad_type)
    for field in {
        "Newspaper of general circulation",
        "Professional journal",
        "NA_13",
    }:
        _mark_independent(values, field, selected_ad_type_field == field)

    step_fields = {
        "job_fair": ("Job Fair", "1a From", "1b To"),
        "employer_website": ("Employer website", "2a From", "2b To"),
        "job_search_website": ("Job search website", "3a From", "3b To"),
        "on_campus": ("On-campus recruiting", "4a From", "4b To"),
        "trade_org": ("Trade or professional organization", "5a From", "5b To"),
        "private_firm": ("Private employment firm", "6a From", "6b To"),
        "employee_referral": ("Employee referral program", "7a From", "7b To"),
        "campus_placement": ("Campus placement office", "8a From", "8b To"),
        "local_ethnic_newspaper": ("Local or ethnic newspaper", "9a From", "9b To"),
        "radio_tv": ("Radio and/or TV advertisemen", "10a From", "10b To"),
    }
    steps = _get(data, "H_recruitment.additional_steps", {}) or {}
    for key, (mark, start_field, end_field) in step_fields.items():
        item = steps.get(key) or {}
        start = item.get("from") or item.get("from_date")
        end = item.get("to") or item.get("to_date")
        values[mark] = "X" if start or end else ""
        values[start_field] = start or ""
        values[end_field] = end or ""

    selected_notices = set(_get(data, "H_recruitment.notice_of_posting", []) or [])
    notice_fields = {
        "1a_bargaining_rep": "Mark 1a. Bargaining Representative Here",
        "1b_physical_notice": "Mark 1b. No Bargaining Representative – Physical Notice Here",
        "1c_electronic_notice": "Mark 1c. No Bargaining Representative – Electronic Notice Here",
        "1d_inhouse_media": "Mark 1d. No Bargaining Representative – In-House Media Here",
        "1e_private_household": "Mark 1e. No Bargaining Representative – Private Household Here",
        "1f_did_not_post": "Mark 1f. The employer DID NOT post the notice of filing Here",
    }
    for key, field in notice_fields.items():
        values[field] = "X" if key in selected_notices else ""

    return values


def _appendix_a_values(data: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    contact = data.get("contact", {}) or {}
    contact_fields = {
        "last_name": "1  Foreign Workers Last family Name",
        "first_name": "2  Foreign Workers First given Name",
        "middle_name": "3  Foreign Workers Middle Names",
        "address1": "4  Address 1 current",
        "address2": "5  Address 2 apartmentsuitefloor and number",
        "city": "6  City",
        "state": "7  State",
        "postal_code": "8  Postal Code",
        "country": "9  Country",
        "province": "10  Province",
        "dob": "11  Date of Birth mmddyyyy",
        "class_of_admission": "12  Class of Admission",
        "a_number": "13  Alien Registration Number A if applicable",
        "country_of_birth": "14  Country of Birth",
        "country_of_citizenship": "15  Country of Citizenship or Nationality",
    }
    for key, field in contact_fields.items():
        if contact.get(key) is not None:
            values[field] = contact[key]

    degree_names = {
        "none": "None",
        "high school/ged": "High SchoolGED",
        "associate": "Associate",
        "associate's": "Associate",
        "bachelor's": "Bachelors",
        "master's": "Master",
        "doctorate": "Doctorate PhD",
        "doctorate (phd)": "Doctorate PhD",
        "other": "Other Degree JD MD etc",
    }
    degree_field_sets = [
        (
            "None",
            "High SchoolGED",
            "Associate",
            "Bachelors",
            "Master",
            "Doctorate PhD",
            "Other Degree JD MD etc",
        ),
        (
            "None_2",
            "High SchoolGED_2",
            "Associate_2",
            "Bachelors_2",
            "Master_2",
            "Doctorate PhD_2",
            "Other Degree JD MD etc_2",
        ),
        (
            "None_3",
            "High SchoolGED_3",
            "Associate_3",
            "Bachelors_3",
            "Master_3",
            "Doctorate PhD_3",
            "Other Degree JD MD etc_3",
        ),
        (
            "None_4",
            "High SchoolGED_4",
            "Associates",
            "Bachelors_4",
            "Master_4",
            "Doctorate PhD_4",
            "Other Degree JD MD etc_4",
        ),
        (
            "None_5",
            "High SchoolGED_5",
            "Associates_2",
            "Bachelors_5",
            "Master_5",
            "Doctorate PhD_5",
            "Other Degree JD MD etc_5",
        ),
    ]
    text_suffixes = ["", "_2", "_3", "_4", "_5"]
    for index in range(5):
        item = (data.get("education") or [{}] * 5)
        item = item[index] if index < len(item) else {}
        degree = _normalized_choice(item.get("degree"))
        canonical_degrees = (
            "None", "High SchoolGED", "Associate", "Bachelors", "Master",
            "Doctorate PhD", "Other Degree JD MD etc",
        )
        for canonical_degree, field in zip(canonical_degrees, degree_field_sets[index]):
            _mark_independent(
                values, field, degree_names.get(degree) == canonical_degree
            )
        suffix = text_suffixes[index]
        fields = {
            "other_degree_specify": (
                "1a If Other Degree in question 1 specify the diplomadegree attained"
                + suffix
            ),
            "majors": (
                "1b  Specify majors andor fields of study may list more than one "
                "related major and more than one field" + suffix
            ),
            "institution": "1c  Name of Institution that issued the degreediploma" + suffix,
            "country": (
                "1d  Name of Country of institution identified in question 1c"
                if index == 0
                else "1d  Name of Country of Institution identified in question 1c"
                + ("" if index == 1 else f"_{index}")
            ),
            "month_year_attained": "1e  Monthyear attained mmyyyy" + suffix,
        }
        for key, field in fields.items():
            values[field] = item.get(key) or ""

    training_fields = [
        (
            "1 Name of InstitutionSchoolTraining provider",
            "1a Name of training coursework experience received",
            "1b  TrainingCertificationslicenses attained if applicable",
            "1c  Start date of training mmyyyy",
            "1d  End date of training mmyyyy",
            "1e  Monthyear awarded mmyyyy",
        ),
        (
            "1 Name of InstitutionSchoolTraining provider_2",
            "1a Name of training coursework experience received_2",
            "1b  TrainingCertificationsLicenses attained if applicable",
            "1c  Start date of training mmyyyy_2",
            "1d  End date of training mmyyyy_2",
            "1e  Monthyear awarded mmyyyy_2",
        ),
        (
            "1 Name of InstitutionSchoolTraining provider_3",
            "1a Name of training coursework experience received_3",
            "1b  Trainingcertificationslicenses attained if applicable",
            "1c  Start date of training mmyyyy_3",
            "1d  End date of training mmyyyy_3",
            "1e  Monthyear awarded mmyyyy_3",
        ),
    ]
    training = data.get("training") or []
    for index, fields in enumerate(training_fields):
        item = training[index] if index < len(training) else {}
        for key, field in zip(
            ("provider", "training_name", "licenses_attained", "start", "end", "awarded"),
            fields,
        ):
            values[field] = item.get(key) or ""

    skills_fields = [
        (
            "1 Name of EmployerInstitutionSchoolTraining Provider",
            "1a  Country",
            "1b  State Territory or Province",
            (
                "1c Description of specific skills abilities andor proficiencies "
                "the foreign worker possesses or attained which help establish "
                "whether the foreign worker meets the requirements identified "
                "for the job opportunity up to 1500 characters"
            ),
        ),
        (
            "1 Name of EmployerInstitutionSchoolTraining Provider_2",
            "1a  Country_2",
            "1b  State Territory or Province_2",
            "b",
        ),
    ]
    skills = data.get("skills") or []
    for index, fields in enumerate(skills_fields):
        item = skills[index] if index < len(skills) else {}
        for key, field in zip(("provider", "country", "state", "description"), fields):
            if field:
                values[field] = item.get(key) or ""
    if data.get("skills_continuation") is not None:
        values["b"] = data.get("skills_continuation") or ""

    experiences = data.get("work_experience") or []
    experience = experiences[0] if experiences else {}
    experience_fields = {
        "employer_name": "1 Employer Name",
        "address1": "1a  Address 1",
        "address2": "1b  Address 2",
        "city": "1c  City or Town",
        "postal_code": "1d  Postal Code",
        "country": "1e  Country",
        "state": "1f  State Territory or Province",
        "job_title": "1g Job Title",
        "start": "1h  Start Date mmyyyy",
        "end": "1i  End Date mmyyyy",
        "hours_per_week": "1k  Hours Worked Per Week",
        "duties": (
            "1l Job Duties Specify details of the job work tasks performed use of "
            "toolsequipment supervision etc up to 3500 characters"
        ),
    }
    for key, field in experience_fields.items():
        values[field] = experience.get(key) or ""
    present = _normalized_choice(experience.get("present"))
    values["1j  Present"] = "Yes" if present == "yes" else "No" if present == "no" else "Off"
    return values


def _appendix_b_values(data: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    rows = data.get("worksites") or []
    for index in range(5):
        item = rows[index] if index < len(rows) else {}
        suffix = "" if index == 0 else f"_{index + 1}"
        for key, base in {
            "county": "1  County",
            "state": "2  StateDistrictTerritory",
            "msa_oes_code": "3  MSAOES Area Code",
            "msa_oes_title": "3a  MSA NameOES Area Title",
        }.items():
            values[base + suffix] = item.get(key) or ""
    return values


def _appendix_c_values(data: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    rows = data.get("entries") or []
    for index in range(2):
        item = rows[index] if index < len(rows) else {}
        suffix = "" if index == 0 else "_2"
        values["1  Section and Item Number" + suffix] = item.get("section_item") or ""
        values[
            "1a Section Name or Category of Supplemental Information" + suffix
        ] = item.get("category") or ""
        values[
            "1b Supplemental Information up to 1500 characters" + suffix
        ] = item.get("explanation") or ""
    return values


def _appendix_d_values(data: Mapping[str, Any]) -> dict[str, Any]:
    values = {
        "1  Enter Specify the date the foreign worker was selected for the position": (
            data.get("selection_date") or ""
        ),
        "5 Enter Specify additional recruitment information up to 3500 characters": (
            data.get("additional_recruitment") or ""
        ),
    }
    rows = data.get("publications") or []
    for index, (name_field, date_field) in enumerate((("2", "2a"), ("3", "3a"), ("4", "4a"))):
        item = rows[index] if index < len(rows) else {}
        values[name_field] = item.get("name") or ""
        values[date_field] = item.get("start_date") or ""
    return values


def fill_eta9089_package(
    form_data: Mapping[str, Any],
    templates_dir: Path,
    output_dir: Path,
    *,
    watermark: str | None = None,
) -> dict[str, Any]:
    """Fill the ETA-9089 application and every supplied appendix."""

    output_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}
    jobs = [("application", "application", form_data, _base_values)]
    for key, json_key, mapper in (
        ("appendix_b", "appendix_B", _appendix_b_values),
        ("appendix_c", "appendix_C", _appendix_c_values),
        ("appendix_d", "appendix_D", _appendix_d_values),
    ):
        section = form_data.get(json_key)
        if section:
            jobs.append((key, key, section, mapper))

    appendix_a = form_data.get("appendix_A")
    if appendix_a:
        experiences = appendix_a.get("work_experience") or []
        copies = max(1, len(experiences))
        for index in range(copies):
            section = deepcopy(appendix_a)
            if experiences:
                section["work_experience"] = [experiences[index]]
                section["skills"] = [
                    skill
                    for skill in (appendix_a.get("skills") or [])
                    if skill.get("experience_index", 0) == index
                ]
            output_key = "appendix_a" if index == 0 else f"appendix_a_{index + 1}"
            jobs.append((output_key, "appendix_a", section, _appendix_a_values))

    for output_key, template_key, section, mapper in jobs:
        template = templates_dir / TEMPLATES[template_key]
        if not template.exists():
            raise FileNotFoundError(template)
        output = output_dir / f"{output_key}.pdf"
        results[output_key] = fill_interactive_pdf(
            template,
            output,
            mapper(section),
            watermark=watermark,
        )
    return results
