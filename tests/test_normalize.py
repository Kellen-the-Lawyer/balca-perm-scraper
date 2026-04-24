from balca_perm_scraper.normalize import clean_text, extract_docket, parse_decision_date
from balca_perm_scraper.models import DecisionRecord


def test_extract_docket():
    assert extract_docket("Acme, 2024-PER-00123") == "2024-PER-00123"


def test_clean_text():
    assert clean_text("  a   b  ") == "a b"


def test_parse_decision_date():
    assert parse_decision_date("Jan. 4, 2025").isoformat() == "2025-01-04"


def test_parse_decision_date_from_sentence():
    assert parse_decision_date("Decision issued Jan. 4, 2025").isoformat() == "2025-01-04"


def test_fallback_stable_id_distinguishes_partial_records():
    first = DecisionRecord(case_name="Acme", source_url="https://www.dol.gov/case/acme")
    second = DecisionRecord(case_name="Beta", source_url="https://www.dol.gov/case/beta")
    assert first.stable_id != second.stable_id
