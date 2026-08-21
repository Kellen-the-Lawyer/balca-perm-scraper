import tempfile
from pathlib import Path

import fitz
from pypdf import PdfReader

from app.perm_verify.form_fill.eta9141_addendum import (
    eta9141_addendum_sections,
    eta9141_with_addendum_references,
    generate_eta9141_addendum,
    merge_eta9141_package,
)


def _form_data():
    return {
        "meta": {
            "pwd_case_number": "P-TEST-00001",
            "case_status": "Determination Issued",
            "determination_date": "01/01/2026",
            "expiration_date": "06/30/2026",
        },
        "job_offer": {
            "job_title": "Software Engineer",
            "job_duties": "Design and maintain software services.",
            "travel_required": "Yes",
            "travel_details": "Up to 10% domestic travel.",
        },
        "requirements": {
            "education_level": "Bachelor's",
            "majors": "See F.a.2",
            "experience_required": "Yes",
            "experience_occupation": "See F.a.2",
            "license": None,
            "foreign_language": None,
            "residency": None,
            "other_special": "See F.a.2",
        },
        "alternate_requirements": {"accepted": "No"},
        "determination": {"soc_code": "15-1252", "notes": "Synthetic note."},
    }


def test_sections_resolve_cross_references_without_losing_full_content():
    sections = eta9141_addendum_sections(_form_data())
    by_id = {item["section"]: item["content"] for item in sections}

    assert list(by_id) == [
        "F.a.2",
        "F.b.1.b",
        "F.b.4.b",
        "F.b.5.a(iv)",
        "F.d.3.a",
        "G.8",
    ]
    assert "Computer Science" in by_id["F.b.1.b"]
    assert "Software Engineer" in by_id["F.b.4.b"]
    assert "Design and maintain software services" in by_id["F.b.5.a(iv)"]


def test_main_form_points_to_each_generated_addendum_section():
    data = _form_data()
    sections = eta9141_addendum_sections(data)
    rendered = eta9141_with_addendum_references(data, sections)

    assert rendered["job_offer"]["job_duties"] == "See Addendum for Section F.a.2."
    assert rendered["requirements"]["majors"] == "See Addendum for Section F.b.1.b."
    assert rendered["requirements"]["experience_occupation"] == "See Addendum for Section F.b.4.b."
    assert rendered["requirements"]["other_special"] == "See Addendum for Section F.b.5.a(iv)."
    assert rendered["job_offer"]["travel_details"] == "See Addendum for Section F.d.3.a."


def test_generated_and_merged_addendum_reopen_with_expected_pages_and_text():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        template = root / "template.pdf"
        form_pdf = root / "form.pdf"
        addendum_pdf = root / "addendum.pdf"
        complete_pdf = root / "complete.pdf"
        document = fitz.open()
        document.new_page(width=612, height=792)
        document.save(template)
        document.close()
        document = fitz.open()
        for _ in range(5):
            document.new_page(width=612, height=792)
        document.save(form_pdf)
        document.close()

        sections = eta9141_addendum_sections(_form_data())
        generated = generate_eta9141_addendum(
            _form_data(), sections, template, addendum_pdf, watermark="TRAINING"
        )
        merged = merge_eta9141_package(form_pdf, addendum_pdf, complete_pdf)

        assert generated["page_count"] == len(sections)
        assert merged["page_count"] == 5 + len(sections)
        text = " ".join(page.extract_text() or "" for page in PdfReader(addendum_pdf).pages)
        normalized = " ".join(text.replace("\xad", "-").split())
        assert "Section F.a.2: Job Duties" in normalized
        assert "TRAINING" in normalized
