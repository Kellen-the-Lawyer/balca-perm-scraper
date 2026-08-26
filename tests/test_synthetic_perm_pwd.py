import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.perm_verify.synthetic.models import PermPwdPair
from app.perm_verify.synthetic.oflc_seed import build_pair_seed


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = (
    ROOT
    / "app/perm_verify/synthetic/examples/oflc_pair_seed.example.json"
)
SCHEMA = (
    ROOT
    / "app/perm_verify/synthetic/schemas/perm_pwd_pair.v1.schema.json"
)


def _rows():
    perm = {
        "id": 11,
        "case_number": "G-100-25120-123456",
        "pwd_number": "P-100-25001-654321",
        "case_status": "Certified",
        "received_date": date(2025, 4, 30),
        "employer_name": "Example Analytics LLC",
        "employer_fein": "12-3456789",
        "job_title": "Data Scientist",
        "soc_code": "15-2051",
        "soc_title": "Data Scientists",
        "wage_from": 125000,
        "wage_per": "Annual",
        "worksite_city": "Chicago",
        "worksite_state": "IL",
        "worksite_postal_code": "60601",
        "source_file": "perm.xlsx",
        "fiscal_year": "2025",
    }
    pwd = {
        "id": 22,
        "case_number": "P-100-25001-654321",
        "case_status": "Determination Issued",
        "determination_date": date(2025, 2, 14),
        "pwd_wage_expiration_date": date(2025, 6, 30),
        "employer_name": "Example Analytics LLC",
        "employer_fein": "12-3456789",
        "job_title": "Data Scientist",
        "soc_code": "15-2051",
        "pwd_wage_rate": 120000,
        "pwd_unit": "Annual",
        "pw_wage_level": "II",
        "worksite_city": "Chicago",
        "worksite_state": "IL",
        "worksite_postal_code": "60601",
        "source_file": "pw.xlsx",
        "fiscal_year": "2025",
    }
    return perm, pwd


def test_checked_in_example_validates():
    parsed = PermPwdPair.model_validate_json(EXAMPLE.read_text())

    assert parsed.pwd.form_data.meta.pwd_case_number == "P-100-25001-654321"
    assert parsed.perm.form_data.E_job_wage["pwd_case_number"] == "P-100-25001-654321"
    assert parsed.privacy.training_approved is True


def test_oflc_seed_maps_provenance_and_preserves_non_form_facts():
    perm, pwd = _rows()
    pair = build_pair_seed(
        perm,
        pwd,
        random_seed=42,
        created_at=datetime(2026, 8, 17, tzinfo=timezone.utc),
    )

    assert pair.shared_case_facts.job_title == "Data Scientist"
    assert "job_title" not in pair.perm.form_data.G_job_info
    assert pair.perm.form_data.E_job_wage["wage_per"] == "Year"
    assert pair.pwd.form_data.determination.wage_unit == "Year"
    assert pair.pwd.form_data.determination.prevailing_wage == 120000
    annotation = pair.perm.annotations["E_job_wage.pwd_case_number"]
    assert annotation.source.kind == "oflc_perm"
    assert annotation.source.source_field == "pwd_number"


def test_oflc_seed_rejects_unlinked_rows():
    perm, pwd = _rows()
    pwd["case_number"] = "P-100-25001-999999"

    with pytest.raises(ValueError, match="must match"):
        build_pair_seed(perm, pwd)


def test_checked_in_json_schema_is_current():
    checked_in = json.loads(SCHEMA.read_text())

    assert checked_in == PermPwdPair.model_json_schema()
