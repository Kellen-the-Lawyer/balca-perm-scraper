from balca_perm_scraper.normalize import clean_text, extract_docket, parse_decision_date


def test_extract_docket():
    assert extract_docket("Acme, 2024-PER-00123") == "2024-PER-00123"


def test_clean_text():
    assert clean_text("  a   b  ") == "a b"


def test_parse_decision_date():
    assert parse_decision_date("Jan. 4, 2025").isoformat() == "2025-01-04"
