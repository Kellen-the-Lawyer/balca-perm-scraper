import os
import sys
from unittest.mock import patch


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from perm_verify.evl_compare import (
    RouteSelectionError,
    _needs_atomic_repair,
    build_atomic_requirements,
    build_report,
    compare_structured,
    select_qualification_route,
)


def _structured_requirements():
    return {
        "primary": {
            "education_level": "Bachelor's",
            "fields_of_study": ["Computer Science", "Information Systems"],
            "second_degree": None,
            "training_months": None,
            "training_fields": [],
            "experience_months": 24,
            "experience_occupation": "software engineering",
            "special_requirements": [
                {"category": "other", "text": "Python",
                 "source_clause": "Experience must include Python",
                 "experience_scope": "some_experience", "required_months": None},
                {"category": "foreign_language", "text": "Spanish",
                 "source_clause": "Spanish required",
                 "experience_scope": "standalone", "required_months": None},
            ],
        },
        "alternative": {
            "education_level": "Master's",
            "fields_of_study": ["Computer Science"],
            "second_degree": None,
            "training_months": None,
            "training_fields": [],
            "experience_months": 12,
            "experience_occupation": "software engineering",
            "special_requirements": [],
        },
    }


def _letter(relationship="hr_or_company_official"):
    return {
        "id": "EVL-1",
        "filename": "letter.pdf",
        "employer_name": "Example Corp",
        "employer_address": "1 Main Street",
        "writer_name": "Alex Smith",
        "writer_title": "HR Director",
        "writer_address": None,
        "writer_relationship": relationship,
        "writer_relationship_label": relationship,
        "start_date": "2020-01-01",
        "end_date": "2023-01-01",
        "currently_employed": False,
        "full_time": True,
        "hours_per_week": 40,
        "signed": True,
        "on_letterhead": True,
        "explicit_facts": [],
        "source_quotes": ["used Python", "stated"],
        "uncertainties": [],
        "document_text": "private extracted text used Python stated",
    }


def test_alternative_route_inherits_unchanged_special_requirements():
    routes = build_atomic_requirements(_structured_requirements())
    assert routes[0]["selection_label"].startswith("Bachelor's degree")
    assert all(r["category"] != "education" for r in routes[0]["requirements"])
    alternative = next(route for route in routes if route["id"] == "alternative")

    assert [r["text"] for r in alternative["requirements"]][-2:] == ["Python", "Spanish"]
    assert all(r["inherited_from_primary"] for r in alternative["requirements"][-2:])
    assert "24 months" not in " ".join(r["text"] for r in alternative["requirements"])


def test_degree_selects_corresponding_experience_route():
    routes = build_atomic_requirements(_structured_requirements())

    bachelors, bachelor_selection = select_qualification_route(
        routes, beneficiary_education={"degree": "Bachelor's"})
    masters, master_selection = select_qualification_route(
        routes, beneficiary_education={"degree": "Master's"})
    doctorate, _ = select_qualification_route(
        routes, beneficiary_education={"degree": "Doctorate"})

    assert bachelors["id"] == "primary" and bachelors["experience_months"] == 24
    assert masters["id"] == "alternative" and masters["experience_months"] == 12
    assert doctorate["id"] == "alternative"
    assert bachelor_selection["source"] == master_selection["source"] == "beneficiary_education"


def test_multiple_routes_require_degree_or_explicit_selection():
    routes = build_atomic_requirements(_structured_requirements())
    try:
        select_qualification_route(routes)
    except RouteSelectionError as exc:
        assert "Select" in str(exc)
    else:
        raise AssertionError("Expected unresolved route selection")


def test_skill_duration_semantics_are_not_flattened():
    structured = _structured_requirements()
    structured["alternative"] = None
    structured["primary"]["experience_months"] = 36
    structured["primary"]["special_requirements"] = [
        {"category": "other", "text": "Python",
         "source_clause": "Experience must include Python",
         "experience_scope": "some_experience", "required_months": None},
        {"category": "other", "text": "SQL",
         "source_clause": "The full term of experience must include SQL",
         "experience_scope": "full_term", "required_months": None},
        {"category": "other", "text": "AWS",
         "source_clause": "Two years of experience with AWS",
         "experience_scope": "explicit_duration", "required_months": 24},
        {"category": "other", "text": "Tableau",
         "source_clause": "One year of experience with Tableau",
         "experience_scope": "explicit_duration", "required_months": 12},
    ]
    requirements = build_atomic_requirements(structured)[0]["requirements"]
    by_text = {item["text"]: item for item in requirements}

    assert by_text["Python"]["experience_scope"] == "some_experience"
    assert by_text["Python"]["required_months"] is None
    assert by_text["SQL"]["experience_scope"] == "full_term"
    assert by_text["SQL"]["required_months"] == 36
    assert by_text["AWS"]["required_months"] == 24
    assert by_text["Tableau"]["required_months"] == 12


def test_atomic_safety_allows_same_requirement_on_different_routes_only():
    atomic = {
        "primary": {"special_requirements": [
            {"text": "Python", "source_clause": "Experience must include Python and SQL."},
            {"text": "SQL", "source_clause": "Experience must include Python and SQL."},
        ]},
        "alternative": {"special_requirements": [
            {"text": "Python", "source_clause": "Experience must include Python and SQL."},
            {"text": "SQL", "source_clause": "Experience must include Python and SQL."},
        ]},
    }
    assert not _needs_atomic_repair(atomic)
    atomic["primary"]["special_requirements"][1]["text"] = "Python"
    assert _needs_atomic_repair(atomic)


def test_alternative_inherits_special_items_it_does_not_repeat():
    structured = _structured_requirements()
    structured["primary"]["experience_months"] = 60
    structured["primary"]["special_requirements"].append({
        "category": "other", "text": "AWS", "source_clause": "Two years with AWS",
        "experience_scope": "explicit_duration", "required_months": 24,
    })
    structured["primary"]["special_requirements"].append({
        "category": "other", "text": "data modeling",
        "source_clause": "The full term must include data modeling",
        "experience_scope": "full_term", "required_months": 60,
    })
    structured["alternative"]["experience_months"] = 36
    structured["alternative"]["special_requirements"] = [
        structured["primary"]["special_requirements"][0]
    ]
    alternative = build_atomic_requirements(structured)[1]
    by_text = {item["text"]: item for item in alternative["requirements"]}

    assert by_text["AWS"]["required_months"] == 24
    assert by_text["AWS"]["inherited_from_primary"] is True
    assert by_text["data modeling"]["required_months"] == 36


def test_empty_alternative_does_not_create_false_route():
    structured = _structured_requirements()
    structured["alternative"] = {
        "education_level": None, "fields_of_study": [], "special_requirements": []
    }
    routes = build_atomic_requirements(structured)
    assert [route["id"] for route in routes] == ["primary"]


def test_report_lists_missing_requirements_and_keeps_model_text_private():
    routes = build_atomic_requirements({**_structured_requirements(), "alternative": None})
    assessments = {"assessments": [
        {"requirement_id": requirement["id"],
         "status": "covered" if requirement["text"] == "Python" else "missing",
         "evl_ids": ["EVL-1"] if requirement["text"] == "Python" else [],
         "evidence_quotes": ["used Python"] if requirement["text"] == "Python" else [],
         "explanation": "Explicitly stated" if requirement["text"] == "Python" else "Not stated"}
        for requirement in routes[0]["requirements"]
    ]}
    report = build_report({"requirements": _structured_requirements()}, routes,
                          [_letter()], assessments)

    assert report["summary"]["status"] == "gaps"
    assert report["summary"]["missing"] == len(routes[0]["requirements"]) - 1
    assert "document_text" not in report["letters"][0]
    assert not report["document_findings"]  # employer address satisfies address information


def test_coworker_letter_creates_advisory_not_insufficiency_finding():
    routes = build_atomic_requirements({**_structured_requirements(), "alternative": None})
    assessments = {"assessments": [
        {"requirement_id": requirement["id"], "status": "covered",
         "evl_ids": ["EVL-1"], "evidence_quotes": ["stated"],
         "explanation": "Explicitly stated"}
        for requirement in routes[0]["requirements"]
    ]}
    report = build_report({}, routes, [_letter("coworker")], assessments)

    assert report["summary"]["status"] == "covered"
    assert not report["document_findings"]
    assert len(report["supporting_evidence_advisories"]) == 1
    message = report["supporting_evidence_advisories"][0]["message"].lower()
    assert "not a finding that the letter is insufficient" in message


def test_missing_writer_identity_is_a_document_finding():
    letter = _letter()
    letter["writer_name"] = None
    report = build_report({}, [], [letter], {"assessments": []})

    assert any(f["code"] == "EVL-DOC-001" for f in report["document_findings"])


def test_unverifiable_model_quote_is_downgraded_to_unclear():
    routes = build_atomic_requirements({**_structured_requirements(), "alternative": None})
    requirement = routes[0]["requirements"][0]
    assessments = {"assessments": [{
        "requirement_id": requirement["id"], "status": "covered",
        "evl_ids": ["EVL-1"], "evidence_quotes": ["fabricated quotation"],
        "explanation": "Claimed coverage",
    }]}
    report = build_report({}, [{**routes[0], "requirements": [requirement]}],
                          [_letter()], assessments)

    assert report["routes"][0]["requirements"][0]["status"] == "unclear"
    assert not report["routes"][0]["requirements"][0]["evidence_quotes"]


def test_graphite_degree_data_selects_route_before_evl_assessment():
    pwd = {"requirements": _structured_requirements()}

    def covered(routes, _letters):
        return {"assessments": [{
            "requirement_id": requirement["id"], "status": "covered",
            "evl_ids": ["EVL-1"], "evidence_quotes": ["stated"],
            "explanation": "Explicitly stated",
        } for requirement in routes[0]["requirements"]]}

    with patch("perm_verify.evl_compare.extract_evl_text", return_value=_letter()), \
            patch("perm_verify.evl_compare._coverage_assessments", side_effect=covered):
        report = compare_structured(
            pwd, [{"filename": "letter.txt", "fullText": "stated"}],
            beneficiary_education={"degree": "Master of Science"})

    assert report["qualification_selection"]["source"] == "beneficiary_education"
    assert report["qualification_selection"]["route_id"] == "alternative"
    assert report["routes"][0]["experience_months"] == 12
    assert report["summary"]["status"] == "covered"
