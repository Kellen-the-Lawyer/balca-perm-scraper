from app.perm_verify.form_fill.eta9141 import (
    eta9141_values,
    eta9141_widget_values,
)


def _data(**determination):
    return {
        "attorney_agent": {"representation_type": "Attorney"},
        "alternate_requirements": {"education_level": "None"},
        "determination": determination,
    }


def test_mapper_covers_all_visible_terminal_field_names():
    values = eta9141_values(_data())

    assert len(values) == 200
    assert len(values) == len(set(values))


def test_wage_period_marks_exactly_one_period():
    expected_fields = {
        "Hour": "Hour",
        "Week": "Week",
        "Bi-Weekly": "BiWeekly",
        "Month": "Month",
        "Year": "Year",
        "Annual": "Year",
    }

    for wage_period, expected_field in expected_fields.items():
        values = eta9141_values(_data(wage_unit=wage_period))
        marked = {
            field
            for field in ("Hour", "Week", "BiWeekly", "Month", "Year")
            if values[field] == "On"
        }

        assert marked == {expected_field}


def test_duplicate_none_checkboxes_are_addressed_by_page():
    values = eta9141_widget_values(
        {
            "attorney_agent": {"representation_type": "None"},
            "alternate_requirements": {"education_level": "Bachelor's"},
        }
    )

    assert values[(1, "None")] == "Yes"
    assert values[(4, "None")] == "Off"


def test_oews_mean_is_a_supported_wage_level():
    values = eta9141_values(_data(wage_level="OEWS mean"))

    assert values["OEWS mean"] == "On"
