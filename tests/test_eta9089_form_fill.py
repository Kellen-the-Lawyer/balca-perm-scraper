from app.perm_verify.form_fill.eta9089 import (
    YES_NO_FIELDS,
    YES_NO_NA_FIELDS,
    _appendix_a_values,
    _appendix_b_values,
    _appendix_c_values,
    _appendix_d_values,
    _base_values,
)


def _set_path(data, path, value):
    target = data
    parts = path.split(".")
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    target[parts[-1]] = value


def _complete_application_data():
    data = {}
    for path in YES_NO_FIELDS:
        _set_path(data, path, "Yes")
    for path in YES_NO_NA_FIELDS:
        _set_path(data, path, "N/A")
    _set_path(data, "C_attorney_agent.representation_type", "Attorney")
    _set_path(data, "E_job_wage.offered_wage_from", "100000")
    _set_path(data, "E_job_wage.offered_wage_to", "125000")
    _set_path(data, "E_job_wage.wage_per", "Year")
    _set_path(data, "F_worksite.worksite_type", "Business premises")
    _set_path(data, "F_worksite.additional_worksites", "No")
    _set_path(data, "G_job_info.kellogg_suitable_combination", "I ACCEPT")
    _set_path(data, "H_recruitment.supervised_recruitment", "No")
    _set_path(data, "H_recruitment.occupation_type", "1a_professional")
    _set_path(data, "H_recruitment.ad2_type", "Newspaper")
    _set_path(data, "H_recruitment.additional_steps", {})
    _set_path(data, "H_recruitment.notice_of_posting", [])
    return data


def _complete_appendix_a_data():
    contact_keys = (
        "last_name",
        "first_name",
        "middle_name",
        "address1",
        "address2",
        "city",
        "state",
        "postal_code",
        "country",
        "province",
        "dob",
        "class_of_admission",
        "a_number",
        "country_of_birth",
        "country_of_citizenship",
    )
    return {
        "contact": {key: "" for key in contact_keys},
        "education": [{} for _ in range(5)],
        "training": [],
        "skills": [],
        "work_experience": [{"present": "Yes"}],
    }


def test_application_mapper_covers_all_terminal_widgets():
    values = _base_values(_complete_application_data())

    assert len(values) == 200
    assert len(values) == len(set(values))


def test_appendix_mappers_cover_every_field():
    assert len(_appendix_a_values(_complete_appendix_a_data())) == 114
    assert len(_appendix_b_values({})) == 20
    assert len(_appendix_c_values({})) == 6
    assert len(_appendix_d_values({})) == 8


def test_radio_groups_write_selected_export_and_clear_other_options():
    values = _base_values(_complete_application_data())

    assert values["16 Yes"] == "Yes"
    assert values["16 No"] == "Off"
    assert values["E 2 Yes"] == "Off"
    assert values["E 2 No"] == "Off"
    assert values["E 2 N/A"] == "NA"


def test_wage_period_marks_exactly_one_period():
    expected_fields = {
        "Hour": "Enter Hour here",
        "Week": "Enter Week here",
        "Bi-Weekly": "Enter BiWeekly here",
        "Month": "Enter Month here",
        "Year": "Enter Year here",
        "Annual": "Enter Year here",
    }

    for wage_period, expected_field in expected_fields.items():
        data = _complete_application_data()
        _set_path(data, "E_job_wage.wage_per", wage_period)
        values = _base_values(data)
        marked = {
            field
            for field in (
                "Enter Hour here",
                "Enter Week here",
                "Enter BiWeekly here",
                "Enter Month here",
                "Enter Year here",
            )
            if values[field] in {"X", "On"}
        }

        assert marked == {expected_field}


def test_second_section_d_record_includes_its_description():
    data = _complete_appendix_a_data()
    data["skills"] = [
        {
            "provider": "Employer One",
            "country": "United States",
            "state": "IL",
            "description": "Skill group one",
        },
        {
            "provider": "Employer Two",
            "country": "United States",
            "state": "TX",
            "description": "Skill group two",
        },
    ]

    values = _appendix_a_values(data)

    assert values[
        "1c Description of specific skills abilities andor proficiencies "
        "the foreign worker possesses or attained which help establish "
        "whether the foreign worker meets the requirements identified "
        "for the job opportunity up to 1500 characters"
    ] == "Skill group one"
    assert values["b"] == "Skill group two"
