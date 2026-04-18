from balca_perm_scraper.normalize import extract_docket, parse_decision_date

print(extract_docket("Acme Corp., 2024-PER-00123 (Jan. 4, 2025)"))
print(parse_decision_date("Jan. 4, 2025"))
