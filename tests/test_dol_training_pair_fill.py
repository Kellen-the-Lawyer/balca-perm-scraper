from app.perm_verify.form_fill.dol_eta9089 import synthetic_foreign_national
from app.perm_verify.form_fill.dol_eta9141 import build_eta9141_form_data


def test_pwd_uses_matched_perm_law_firm_fein_and_not_special_skills_as_duties():
    pwd = {
        "CASE_NUMBER": "P-TEST",
        "JOB_TITLE": "Software Development Engineer",
        "PWD_SOC_CODE": "15-1252",
        "SPEC_REQ_OTHER": "Five years using ExampleTool.",
    }
    perm = {
        "JOB_OPP_PWD_NUMBER": "P-TEST",
        "ATTY_AG_FEIN": "12-3456789",
    }

    form = build_eta9141_form_data(pwd, perm)

    assert form["attorney_agent"]["law_firm_fein"] == "12-3456789"
    assert "ExampleTool" not in form["job_offer"]["job_duties"]
    assert "Design, develop, test" in form["job_offer"]["job_duties"]
    assert form["synthetic_fields"] == ["job_offer.job_duties"]


def test_split_skill_evidence_covers_requirements_and_cumulative_time():
    pwd = {
        "REQUIRED_EDUCATION_LEVEL": "Bachelor's",
        "REQUIRED_EDUCATION_MAJOR": "Computer Science",
        "REQUIRED_EXPERIENCE": "Yes",
        "REQUIRED_EXPERIENCE_MONTHS": 48,
        "REQUIRED_OCCUPATION": "Software engineering",
        "SPECIAL_SKILLS_REQUIREMENTS": "Yes",
        "SPEC_REQ_OTHER": "Cloud architecture\nDistributed systems\nNoSQL databases",
    }
    perm = {"JOB_TITLE": "Engineering Manager"}

    appendix = synthetic_foreign_national(
        perm,
        pwd,
        evidence_pattern="split_skills",
        employer_count=2,
    )

    required = {item["id"] for item in appendix["requirements"]}
    covered = {
        identifier
        for skill in appendix["skills"]
        for identifier in skill.get("requirement_ids", [])
    }
    employer_skills = [
        skill for skill in appendix["skills"] if skill["provider"].endswith(("SOLUTIONS", "TECHNOLOGIES"))
    ]

    assert len(appendix["work_experience"]) == 2
    assert appendix["credited_experience_months"] == 48
    assert required <= covered
    assert len(employer_skills) == 2
    assert employer_skills[0]["requirement_ids"] != employer_skills[1]["requirement_ids"]
