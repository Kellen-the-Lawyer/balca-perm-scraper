from __future__ import annotations

import logging

from scripts.scrape.download_govinfo_bulk import iter_api_packages


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeSession:
    def __init__(self) -> None:
        self.calls = 0

    def get(self, url: str, params: dict | None = None, timeout: tuple[int, int] = (10, 30)) -> FakeResponse:
        self.calls += 1
        if self.calls == 1:
            return FakeResponse(
                {
                    "packages": [
                        {"packageId": "CRPT-118hrpt1"},
                        {"packageId": "SERIALSET-13860_00_00-001-0000-0000"},
                    ],
                    "nextPage": "https://api.govinfo.gov/collections/CRPT/next?offsetMark=abc",
                }
            )
        return FakeResponse({"packages": [{"packageId": "CRPT-118hrpt2"}]})


def test_discovery_filters_mixed_collection_packages(caplog) -> None:
    session = FakeSession()

    with caplog.at_level(logging.WARNING):
        packages = list(iter_api_packages(session, "test-key", "CRPT", "1900-01-01", 1000, None))

    assert [package["packageId"] for package in packages] == ["CRPT-118hrpt1", "CRPT-118hrpt2"]
    assert "SERIALSET=1" in caplog.text
