from balca_perm_scraper.storage import DecisionStore


def test_scrape_run_metadata_round_trip(tmp_path):
    store = DecisionStore(tmp_path / "decisions.sqlite")
    run_id = store.start_run(
        query="PERM",
        docket_prefix=None,
        max_pages=2,
        page_size=50,
        fiscal_years=["2025"],
        search_url="https://example.test/search",
    )

    store.record_run_page(
        run_id=run_id,
        fiscal_year="2025",
        page_number=1,
        request_body={"search": "PERM", "top": 50},
        status="success",
        result_count=3,
        upserted_count=3,
        azure_count=10,
    )
    store.finish_run(
        run_id,
        status="completed",
        total_pages=1,
        total_records=3,
        total_upserted=3,
    )

    [run] = store.recent_runs()
    assert run["id"] == run_id
    assert run["status"] == "completed"
    assert run["total_pages"] == 1
    assert run["total_records"] == 3
    assert run["total_upserted"] == 3
