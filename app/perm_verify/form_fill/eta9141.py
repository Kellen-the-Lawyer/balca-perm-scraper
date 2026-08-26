"""Canonical ETA-9141 JSON to the official fillable DOL PDF."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

import fitz

from .acroform import AcroFormValidationError, fill_interactive_pdf


TEMPLATE = "Form ETA-9141 - 508 Compliant - Expires 07-31-2026.pdf"


def _get(data: Mapping[str, Any], path: str, default: Any = None) -> Any:
    value: Any = data
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return default
        value = value[part]
    return value


def _choice(value: Any) -> str | None:
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


def _check(
    values: dict[str, Any], field: str, selected: bool, export: str = "On"
) -> None:
    values[field] = export if selected else "Off"


def _yes_no(
    values: dict[str, Any],
    selected: Any,
    yes_field: str,
    no_field: str,
    *,
    yes_export: str = "On",
    no_export: str = "On",
) -> None:
    choice = _choice(selected)
    _check(values, yes_field, choice == "yes", yes_export)
    _check(values, no_field, choice == "no", no_export)


def _yes_no_na(
    values: dict[str, Any],
    selected: Any,
    yes_field: str,
    no_field: str,
    na_field: str,
) -> None:
    choice = _choice(selected)
    _check(values, yes_field, choice == "yes")
    _check(values, no_field, choice == "no")
    _check(values, na_field, choice == "na")


def _money_parts(value: Any) -> tuple[str, str]:
    if value in (None, ""):
        return "", ""
    try:
        amount = Decimal(str(value).replace(",", "").replace("$", ""))
    except InvalidOperation as exc:
        raise ValueError(f"invalid wage amount: {value!r}") from exc
    dollars, cents = f"{amount.quantize(Decimal('0.01')):.2f}".split(".")
    return dollars, cents


def _text_values(data: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "visa_class": (
            "1 Enter Indicate the type of visa classification supported by this "
            "application Write classification symbol"
        ),
        "requestor_contact.last_name": "1 Enter Contacts last family name",
        "requestor_contact.first_name": "2 Enter First given name",
        "requestor_contact.middle_name": "3 Enter Middle names if applicable",
        "requestor_contact.job_title": "4 Enter Contacts job title",
        "requestor_contact.address1": "5 Enter Address 1",
        "requestor_contact.address2": "6 Enter Address 2",
        "requestor_contact.city": "7 Enter City",
        "requestor_contact.state": "8 Enter State",
        "requestor_contact.postal_code": "9 Enter Postal code",
        "requestor_contact.country": "10 Enter Country",
        "requestor_contact.province": "11 Enter Province if applicable",
        "requestor_contact.phone": "12 Enter Telephone number",
        "requestor_contact.extension": "13 Enter Extension if applicable",
        "requestor_contact.email": "14 Enter Business email address",
        "employer.legal_business_name": "1 Enter Legal business name",
        "employer.trade_name": "2 Enter Trade nameDoing Business As DBA if applicable",
        "employer.address1": "3 Enter Address 1",
        "employer.address2": "4 Enter Address 2",
        "employer.city": "5 Enter City",
        "employer.state": "6 Enter State",
        "employer.postal_code": "7 Enter Postal code",
        "employer.country": "8 Enter Country",
        "employer.province": "9 Enter Province if applicable",
        "employer.phone": "10 Enter Telephone number",
        "employer.extension": "11 Enter Extension if applicable",
        "employer.fein": (
            "12 Enter Federal Employer Identification Number FEIN from IRS"
        ),
        "employer.naics_code": "13 Enter NAICS code",
        "attorney_agent.last_name": "2 Enter Attorney or agents last family name",
        "attorney_agent.first_name": "3 Enter First given name",
        "attorney_agent.middle_name": "4 Enter Middle names",
        "attorney_agent.address1": "Enter Address 1",
        "attorney_agent.address2": (
            "6 Enter Address 2 apartmentsuitefloor and number"
        ),
        "attorney_agent.city": "7 Enter City_2",
        "attorney_agent.state": "8 Enter State_2",
        "attorney_agent.postal_code": "9 Enter Postal code_2",
        "attorney_agent.country": "10 Enter Country_2",
        "attorney_agent.province": "11 Enter Province if applicable_2",
        "attorney_agent.phone": "12 Enter Telephone number_2",
        "attorney_agent.extension": "13 Enter Extension",
        "attorney_agent.email": "14 Enter Law firm business email address",
        "attorney_agent.law_firm_name": "15 Enter Law firm business name",
        "attorney_agent.law_firm_fein": "16 Enter Law firmbusiness FEIN",
        "wage_source.survey_name": "a Enter Survey name or title",
        "wage_source.survey_date": (
            "b Enter Survey date of publication or if not published date of "
            "submission to DOL"
        ),
        "job_offer.job_title": "1 Enter Job title",
        "job_offer.job_duties": (
            "2 Enter Job duties Description of the specific services or labor to be "
            "performed  All job duties must be disclosed A description of the job "
            "duties MUST begin in this space For mailin applications an addendum may "
            "be used to complete the response fully"
        ),
        "job_offer.job_duties_continuation": "US Department of Labor",
        "job_offer.supervised_soc": (
            "a Enter If Yes please indicate the SOC codes and SOC titles of the "
            "occupations of the employees to be supervised"
        ),
        "requirements.other_degree": (
            "a Enter If Other degree in question 1 specify the US degree required"
        ),
        "requirements.majors": (
            "b Enter Indicate the majors andor fields of study required  May list "
            "more than one related major and more than one field"
        ),
        "requirements.second_degree": (
            "a Enter If Yes in question 2 indicate the second US degree and the "
            "majors andor fields of study required"
        ),
        "requirements.training_months": (
            "Enter Specify the months of training required if appicable"
        ),
        "requirements.training_field": (
            "b Enter Indicate the fieldsnames of training required  May list more "
            "than one related field and more than one type"
        ),
        "requirements.experience_months": (
            "a Enter If Yes in question 4 specify the number of months of experience "
            "required"
        ),
        "requirements.experience_occupation": (
            "b Enter Indicate the occupation required"
        ),
        "requirements.license": "i. License/Certification Free Text Field",
        "requirements.foreign_language": "ii. Foreign language free text field",
        "requirements.residency": "iii. Residency/Fellowship",
        "requirements.other_special": "iv. Other special skills or requirements",
        "alternate_requirements.other_degree": (
            "a Enter If Other degree in question 2 specify the USdegree accepted"
        ),
        "alternate_requirements.majors": (
            "b Enter Indicate the majors andor fields of study accepted  May list "
            "more than one related major and more than one field"
        ),
        "alternate_requirements.training_months": (
            "a Enter If Yes in question 3 specify the number of months of alternate "
            "training accepted"
        ),
        "alternate_requirements.training_field": (
            "b Enter Indicate the fields names of training accepted  May list more "
            "than one related field and more than one type"
        ),
        "alternate_requirements.experience_months": (
            "a Enter If Yes in question 4 specify the number of months of alternate "
            "experience accepted"
        ),
        "alternate_requirements.license": "fi. License/Certification",
        "alternate_requirements.foreign_language": "Fii. Foreign language",
        "alternate_requirements.residency": "Fiii. Residency/Fellowship",
        "alternate_requirements.other_special": (
            "Fiv. Other Special Skills or Requirements"
        ),
        "job_offer.suggested_soc_code": "1 Enter Suggested SOC ONET OEWS code",
        "job_offer.suggested_soc_title": (
            "a Enter Suggested SOC ONET OEWS occupation title"
        ),
        "job_offer.supervisor_job_title": (
            "2 Enter Job title of the official the employee will report to for this "
            "job opportunity if applicable"
        ),
        "job_offer.travel_details": (
            "a Enter If Yes provide geographic location and frequency of the travel"
        ),
        "job_offer.worksite.address1": "1 Enter Worksite address 1",
        "job_offer.worksite.address2": "2 Enter Address 2",
        "job_offer.worksite.city": "3 Enter City",
        "job_offer.worksite.state": "4 Enter State",
        "job_offer.worksite.county": "5 Enter County",
        "job_offer.worksite.postal_code": "6 Enter Postal code",
        "meta.pwd_case_number": "1 Enter PWD tracking number",
        "meta.received_date": "2 Enter PW receipt date",
        "determination.soc_code": "3 Enter SOC code",
        "determination.soc_title": "a Enter SOC occupation title",
        "determination.onet_code": "b Enter ONET code",
        "determination.onet_title": "c Enter ONET occupation title",
        "determination.combination_soc_code": "d Enter ONET code",
        "determination.combination_soc_title": "e Enter ONET occupation title",
        "determination.survey_name": (
            "d Enter If Survey in question 4c specify the name of the survey"
        ),
        "determination.alternate_survey_name": (
            "d Enter If Survey in question 5c specify the name of the survey"
        ),
        "determination.bls_area": (
            "6 Enter The wage is based on the following BLS area Metropolitan or "
            "NonMetropolitan Statistical Area"
        ),
        "determination.notes": "8 Enter Additional notes regarding wage determination",
        "meta.determination_date": "9 Enter Determination date",
        "meta.expiration_date": "10 Enter Expiration date",
    }
    return {
        field: "" if _get(data, path) is None else _get(data, path)
        for path, field in fields.items()
    }


def _degree_fields(
    values: dict[str, Any], degree: Any, *, alternate: bool = False
) -> None:
    normalized = _choice(degree)
    if alternate:
        mapping = {
            "none": "None",
            "high school/ged": "High school/GED",
            "associate's": "Associate's",
            "associate": "Associate's",
            "bachelor's": "Bachelor's",
            "bachelor": "Bachelor's",
            "master's": "Master's",
            "master": "Master's",
            "doctorate": "Doctorate (PhD)",
            "doctorate (phd)": "Doctorate (PhD)",
            "other": "Other degree (J.D).M.D.etc)",
        }
        all_fields = set(mapping.values())
    else:
        mapping = {
            "none": "None_2",
            "high school/ged": "High schoolGED",
            "associate's": "Associates",
            "associate": "Associates",
            "bachelor's": "Bachelors",
            "bachelor": "Bachelors",
            "master's": "Masters",
            "master": "Masters",
            "doctorate": "Doctorate PhD",
            "doctorate (phd)": "Doctorate PhD",
            "other": "Other degree JD MD etc",
        }
        all_fields = set(mapping.values())
    selected = mapping.get(normalized)
    for field in all_fields:
        _check(values, field, field == selected)


def _wage_source_field(source: Any, *, alternate: bool = False) -> str | None:
    normalized = _choice(source) or ""
    suffix = "_2" if alternate else ""
    if "acwia" in normalized:
        return "OEWS ACWIA" + suffix
    if "all industries" in normalized or normalized in {"oes", "oews"}:
        return "OEWS All Industries" + suffix
    if normalized == "cba":
        return "CBA" + suffix
    if normalized == "dba":
        return "DBA" + suffix
    if normalized == "sca":
        return "SCA" + suffix
    if "survey" in normalized:
        return "Alternative survey" if alternate else "Alternate survey"
    if "sports" in normalized:
        return "Professional sports league rules or" + suffix
    return None


def eta9141_values(data: Mapping[str, Any]) -> dict[str, Any]:
    """Map canonical ETA-9141 data to the template's terminal field names."""

    values = _text_values(data)

    representation = _choice(_get(data, "attorney_agent.representation_type"))
    for field in ("Attorney", "Agent", "None"):
        _check(values, field, representation == field.lower(), "Yes")

    _yes_no_na(values, _get(data, "wage_source.acwia"), "Yes_1", "No_2", "N/A_3")
    _check(
        values,
        "i Institution of higher education",
        _choice(_get(data, "wage_source.acwia_higher_education")) == "yes",
    )
    _check(
        values,
        "ii Affiliated or related nonprofit entity connected or associated with an "
        "institution of higher education",
        _choice(_get(data, "wage_source.acwia_affiliated_nonprofit")) == "yes",
    )
    _check(
        values,
        "iii Nonprofit research organization or Governmental research organization",
        _choice(_get(data, "wage_source.acwia_research_org")) == "yes",
    )
    _yes_no_na(
        values,
        _get(data, "wage_source.acwia_status_changed"),
        "Yes_4",
        "No_5",
        "N/A_6",
    )
    _yes_no(
        values, _get(data, "wage_source.professional_sports"), "Yes_7", "No_8"
    )
    _yes_no_na(values, _get(data, "wage_source.cba"), "Yes_9", "No_10", "N/A_11")
    _yes_no(
        values, _get(data, "wage_source.dba_sca_requested"), "Yes_12", "No_13"
    )
    requested_source = _choice(_get(data, "wage_source.requested_source"))
    _check(values, "DBA_14", requested_source == "dba")
    _check(values, "SCA_15", requested_source == "sca")
    _yes_no(values, _get(data, "wage_source.survey_requested"), "Yes_16", "No_17")

    _yes_no(
        values,
        _get(data, "job_offer.supervises_employees"),
        "Yes_18",
        "No_19",
    )
    _degree_fields(values, _get(data, "requirements.education_level"))
    _yes_no(
        values,
        _get(data, "requirements.second_degree_required"),
        "Yes_20",
        "No_21",
    )
    _yes_no(
        values,
        _get(data, "requirements.training_required"),
        "Yes_22",
        "No_22",
        yes_export="Yes",
        no_export="No",
    )
    experience = _choice(_get(data, "requirements.experience_required"))
    _check(values, "undefined_23", experience == "yes")
    values["no"] = "X" if experience == "no" else ""
    special = _choice(_get(data, "requirements.special_required"))
    _check(values, "undefined_24", special == "yes")
    _check(values, "undefined_25", special == "no")

    special_items = {
        "i LicenseCertification": "requirements.license",
        "(ii) Foreign language": "requirements.foreign_language",
        "(iii) Residency/Fellowship": "requirements.residency",
        "(iv) Other special skills or requirements": "requirements.other_special",
    }
    for field, path in special_items.items():
        _check(values, field, bool(_get(data, path)))

    alternate = _choice(_get(data, "alternate_requirements.accepted"))
    _check(values, "undefined_29", alternate == "yes")
    values["NO"] = "X" if alternate == "no" else ""
    _degree_fields(
        values, _get(data, "alternate_requirements.education_level"), alternate=True
    )
    alternate_training = _choice(
        _get(data, "alternate_requirements.training_accepted")
    )
    _check(values, "Yes_2", alternate_training == "yes")
    values["3. No"] = "X" if alternate_training == "no" else ""
    _yes_no(
        values,
        _get(data, "alternate_requirements.experience_accepted"),
        "undefined_37",
        "undefined_38",
    )
    _yes_no(
        values,
        _get(data, "alternate_requirements.special_required"),
        "undefined_39",
        "undefined_40",
    )
    alternate_items = {
        "(i) License/Certification:": "alternate_requirements.license",
        "(ii) Foreign language:": "alternate_requirements.foreign_language",
        "(iii) Residency/Fellowship:": "alternate_requirements.residency",
        "(iv) Other special skills or requirements:": (
            "alternate_requirements.other_special"
        ),
    }
    for field, path in alternate_items.items():
        values[field] = "X" if _get(data, path) else ""

    travel = _choice(_get(data, "job_offer.travel_required"))
    values["3 Will travel be required in order to perform the job duties"] = (
        "Yes_3" if travel == "yes" else "No_2" if travel == "no" else "Off"
    )
    other_area = _choice(_get(data, "job_offer.other_bls_area"))
    values["Yes"] = "Yes_4" if other_area == "yes" else "Off"
    values["No"] = "No_3" if other_area == "no" else "Off"

    wage, cents = _money_parts(_get(data, "determination.prevailing_wage"))
    values["4. Enter the dollar amount here"] = wage
    values["4. Enter the cents amount here"] = cents
    alternate_wage, alternate_cents = _money_parts(
        _get(data, "determination.alternate_prevailing_wage")
    )
    values["Enter the prevailing wage dollar amount here"] = alternate_wage
    values["Enter the prevailing wage cents amount here"] = alternate_cents
    hourly, hourly_cents = _money_parts(_get(data, "determination.h2b_highest_wage"))
    values["Enter the dollar amount per hour here"] = hourly
    values["Enter the cents amount per hour here"] = hourly_cents

    unit = _choice(_get(data, "determination.wage_unit"))
    unit_fields = {
        "hour": "Hour",
        "week": "Week",
        "bi-weekly": "BiWeekly",
        "biweekly": "BiWeekly",
        "month": "Month",
        "year": "Year",
        "annual": "Year",
    }
    selected_unit = unit_fields.get(unit)
    for field in {"Hour", "Week", "BiWeekly", "Month", "Year"}:
        _check(values, field, field == selected_unit)

    alternate_unit = _choice(_get(data, "determination.alternate_wage_unit"))
    selected_alternate_unit = unit_fields.get(alternate_unit)
    for field in {"Hour", "Week", "BiWeekly", "Month", "Year"}:
        _check(values, field + "_2", field == selected_alternate_unit)

    level = (_choice(_get(data, "determination.wage_level")) or "").replace(
        "level ", ""
    )
    level_fields = {
        "i": "I",
        "ii": "II",
        "iii": "III",
        "iv": "IV",
        "oews mean": "OEWS mean",
        "na": "NA",
    }
    selected_level = level_fields.get(level)
    for field in {"I", "II", "III", "IV", "OEWS mean", "NA"}:
        _check(values, field, field == selected_level)

    alternate_level = (
        _choice(_get(data, "determination.alternate_wage_level")) or ""
    ).replace("level ", "")
    selected_alternate_level = level_fields.get(alternate_level)
    for field in {"I", "II", "III", "IV", "OEWS mean", "NA"}:
        _check(values, field + "_2", field == selected_alternate_level)

    source_fields = {
        "OEWS All Industries",
        "OEWS ACWIA",
        "CBA",
        "DBA",
        "SCA",
        "Alternate survey",
        "Professional sports league rules or",
    }
    selected_source = _wage_source_field(_get(data, "determination.wage_source"))
    for field in source_fields:
        _check(values, field, field == selected_source)
    selected_alt_source = _wage_source_field(
        _get(data, "determination.alternate_wage_source"), alternate=True
    )
    for field in source_fields:
        alt_field = (
            "Alternative survey"
            if field == "Alternate survey"
            else field + "_2"
        )
        _check(values, alt_field, alt_field == selected_alt_source)
    return values


def eta9141_widget_values(data: Mapping[str, Any]) -> dict[tuple[int, str], Any]:
    """Return values for unrelated widgets that share a terminal field name.

    The official form reuses ``None`` for the representation checkbox on page 1
    and the alternate-education checkbox on page 4. They are separate PDF
    objects and can legitimately have different values.
    """

    representation = _choice(_get(data, "attorney_agent.representation_type"))
    alternate_degree = _choice(
        _get(data, "alternate_requirements.education_level")
    )
    return {
        (1, "None"): "Yes" if representation == "none" else "Off",
        (4, "None"): "On" if alternate_degree == "none" else "Off",
    }


def _terminal_defaults(template: Path) -> dict[str, Any]:
    values: dict[str, Any] = {}
    document = fitz.open(template)
    for page in document:
        for widget in page.widgets() or []:
            if widget.rect.width <= 0 or widget.rect.height <= 0:
                continue
            values[widget.field_name] = (
                "Off"
                if widget.field_type_string in {"CheckBox", "RadioButton"}
                else ""
            )
    document.close()
    return values


def fill_eta9141(
    form_data: Mapping[str, Any],
    template: Path,
    output: Path,
    *,
    watermark: str | None = None,
) -> dict[str, Any]:
    """Fill and validate the official ETA-9141 while keeping it interactive."""

    defaults = _terminal_defaults(template)
    mapped = eta9141_values(form_data)
    missing = sorted(set(mapped) - set(defaults))
    if missing:
        raise AcroFormValidationError(
            f"{template.name} does not contain mapped terminal fields: {missing}"
        )
    defaults.update(mapped)
    return fill_interactive_pdf(
        template,
        output,
        defaults,
        watermark=watermark,
        widget_values=eta9141_widget_values(form_data),
    )
