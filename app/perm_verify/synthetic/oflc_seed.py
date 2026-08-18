"""Map joined OFLC disclosure rows into the paired synthetic-data contract."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Mapping

from .models import PermPwdPair


PERM_FIELD_MAP = {
    "case_number": "perm.form_data.meta.perm_case_number",
    "case_status": "perm.form_data.meta.case_status",
    "received_date": "perm.form_data.meta.received_date",
    "decision_date": "perm.form_data.meta.decision_date",
    "employer_name": "perm.form_data.A_employer.legal_business_name",
    "employer_city": "perm.form_data.A_employer.city",
    "employer_state": "perm.form_data.A_employer.state",
    "employer_postal_code": "perm.form_data.A_employer.postal_code",
    "employer_fein": "perm.form_data.A_employer.fein",
    "employer_naics": "perm.form_data.A_employer.naics_code",
    "employer_year_commenced": "perm.form_data.A_employer.year_commenced_business",
    "atty_law_firm": "perm.form_data.C_attorney_agent.law_firm_name",
    "atty_last_name": "perm.form_data.C_attorney_agent.last_name",
    "atty_first_name": "perm.form_data.C_attorney_agent.first_name",
    "wage_from": "perm.form_data.E_job_wage.offered_wage_from",
    "wage_to": "perm.form_data.E_job_wage.offered_wage_to",
    "wage_per": "perm.form_data.E_job_wage.wage_per",
    "worksite_city": "perm.form_data.F_worksite.city",
    "worksite_state": "perm.form_data.F_worksite.state",
    "worksite_postal_code": "perm.form_data.F_worksite.postal_code",
    "worksite_bls_area": "perm.form_data.F_worksite.msa_oes_area_title",
    "pwd_number": "perm.form_data.E_job_wage.pwd_case_number",
    "fw_currently_employed": "perm.form_data.G_job_info.fw_currently_employed",
    "is_multiple_locations": "perm.form_data.F_worksite.additional_worksites",
    "employer_layoff": "perm.form_data.G_job_info.layoff_6mo",
}

SHARED_FIELD_MAP = {
    "employer_name": "employer_name",
    "employer_fein": "employer_fein",
    "job_title": "job_title",
    "soc_code": "soc_code",
    "soc_title": "soc_title",
    "worksite_city": "worksite_city",
    "worksite_state": "worksite_state",
    "worksite_postal_code": "worksite_postal_code",
}

PWD_FIELD_MAP = {
    "case_number": "pwd.form_data.meta.pwd_case_number",
    "case_status": "pwd.form_data.meta.case_status",
    "received_date": "pwd.form_data.meta.received_date",
    "determination_date": "pwd.form_data.meta.determination_date",
    "pwd_wage_expiration_date": "pwd.form_data.meta.validity_to",
    "employer_name": "pwd.form_data.employer.legal_business_name",
    "employer_city": "pwd.form_data.employer.address.city",
    "employer_state": "pwd.form_data.employer.address.state",
    "employer_postal_code": "pwd.form_data.employer.address.postal_code",
    "employer_fein": "pwd.form_data.employer.fein",
    "naics_code": "pwd.form_data.employer.naics_code",
    "job_title": "pwd.form_data.job_offer.job_title",
    "soc_code": "pwd.form_data.determination.soc_code",
    "soc_title": "pwd.form_data.determination.soc_title",
    "pwd_wage_rate": "pwd.form_data.determination.prevailing_wage",
    "pwd_unit": "pwd.form_data.determination.wage_unit",
    "pw_wage_level": "pwd.form_data.determination.wage_level",
    "wage_source": "pwd.form_data.determination.wage_source",
    "bls_area": "pwd.form_data.determination.bls_area",
    "worksite_city": "pwd.form_data.job_offer.worksite.city",
    "worksite_state": "pwd.form_data.job_offer.worksite.state",
    "worksite_postal_code": "pwd.form_data.job_offer.worksite.postal_code",
}


def _date_value(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    return value


def _yes_no(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    text = str(value).strip().upper()
    if text in {"Y", "YES", "TRUE", "1"}:
        return "Yes"
    if text in {"N", "NO", "FALSE", "0"}:
        return "No"
    return value


def _wage_unit(value: Any) -> Any:
    return {"Annual": "Year", "Hourly": "Hour"}.get(value, value)


def _set_path(root: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    node = root
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def _source_ref(kind: str, row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_id": f"{kind}:{row.get('id') or row.get('case_number')}",
        "kind": kind,
        "table": kind,
        "record_id": str(row.get("id")) if row.get("id") is not None else None,
        "source_file": row.get("source_file"),
        "fiscal_year": str(row.get("fiscal_year")) if row.get("fiscal_year") else None,
        "public_data": True,
    }


def _annotation(kind: str, source_id: str, source_field: str) -> dict[str, Any]:
    return {
        "state": "present",
        "source": {
            "kind": kind,
            "source_id": source_id,
            "source_field": source_field,
            "transformation": "direct OFLC disclosure mapping",
        },
        "review_status": "auto_validated",
    }


def build_pair_seed(
    perm_row: Mapping[str, Any],
    pwd_row: Mapping[str, Any],
    *,
    case_id: str | None = None,
    random_seed: int | None = None,
    created_at: datetime | None = None,
) -> PermPwdPair:
    """Create a partial, provenance-rich pair from matching disclosure rows.

    The result is intentionally a ``seed``.  Fields absent from the disclosure
    data must be supplied by rules or reviewed real forms before rendering.
    """

    perm_pwd = perm_row.get("pwd_number")
    pwd_number = pwd_row.get("case_number")
    if not perm_pwd or not pwd_number or perm_pwd != pwd_number:
        raise ValueError("OFLC PERM pwd_number must match OFLC PW case_number")

    perm_source = _source_ref("oflc_perm", perm_row)
    pwd_source = _source_ref("oflc_pw", pwd_row)
    payload: dict[str, Any] = {
        "schema_version": "casebase.perm-pwd-pair.v1",
        "case_id": case_id or f"oflc-{perm_row.get('case_number')}",
        "created_at": (created_at or datetime.now(timezone.utc)).isoformat(),
        "random_seed": random_seed,
        "lifecycle_stage": "seed",
        "privacy": {
            "classification": "public",
            "contains_real_person_data": False,
            "contains_real_employer_data": bool(
                perm_row.get("employer_name") or pwd_row.get("employer_name")
            ),
            "training_approved": False,
            "redaction_notes": (
                "Replace or explicitly approve employer identity fields before training."
            ),
        },
        "sources": [perm_source, pwd_source],
        "shared_case_facts": {},
        "shared_fact_annotations": {},
        "pwd": {
            "metadata": {
                "document_id": f"pwd-{pwd_number}",
                "form": "ETA-9141",
                "form_edition": "unassigned",
                "stage": "seed",
                "artifact_kind": "training_render",
                "source_type": "semi_synthetic",
                "artifact": {},
            },
            "form_data": {},
            "annotations": {},
        },
        "perm": {
            "metadata": {
                "document_id": f"perm-{perm_row.get('case_number')}",
                "form": "ETA-9089",
                "form_edition": "unassigned",
                "stage": "seed",
                "artifact_kind": "training_render",
                "source_type": "semi_synthetic",
                "artifact": {},
            },
            "form_data": {},
            "annotations": {},
        },
        "expected_comparisons": [
            {
                "comparison_id": "pwd-number-link",
                "pwd_path": "pwd.form_data.meta.pwd_case_number",
                "perm_path": "perm.form_data.E_job_wage.pwd_case_number",
                "expected": "match",
                "rule": "linked OFLC disclosure records",
            }
        ],
        "tags": ["oflc_seed", "paired_pwd_perm"],
    }

    for source_field, target_path in PERM_FIELD_MAP.items():
        value = perm_row.get(source_field)
        if value is None:
            continue
        if source_field in {"received_date", "decision_date"}:
            value = _date_value(value)
        elif source_field in {
            "fw_currently_employed",
            "is_multiple_locations",
            "employer_layoff",
        }:
            value = _yes_no(value)
        elif source_field == "wage_per":
            value = _wage_unit(value)
        local_path = target_path.removeprefix("perm.")
        _set_path(payload["perm"], local_path, value)
        payload["perm"]["annotations"][local_path.removeprefix("form_data.")] = _annotation(
            "oflc_perm", perm_source["source_id"], source_field
        )

    for source_field, target_field in SHARED_FIELD_MAP.items():
        value = perm_row.get(source_field)
        if value is None:
            continue
        payload["shared_case_facts"][target_field] = value
        payload["shared_fact_annotations"][target_field] = _annotation(
            "oflc_perm", perm_source["source_id"], source_field
        )

    for source_field, target_path in PWD_FIELD_MAP.items():
        value = pwd_row.get(source_field)
        if value is None:
            continue
        if source_field in {
            "received_date",
            "determination_date",
            "pwd_wage_expiration_date",
        }:
            value = _date_value(value)
        elif source_field == "pwd_unit":
            value = _wage_unit(value)
        local_path = target_path.removeprefix("pwd.")
        _set_path(payload["pwd"], local_path, value)
        payload["pwd"]["annotations"][local_path.removeprefix("form_data.")] = _annotation(
            "oflc_pw", pwd_source["source_id"], source_field
        )

    return PermPwdPair.model_validate(payload)
