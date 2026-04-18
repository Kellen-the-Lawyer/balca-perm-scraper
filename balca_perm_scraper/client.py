from __future__ import annotations

import time
from contextlib import AbstractContextManager
from typing import Any, Optional

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .config import SETTINGS


class ScraperClient(AbstractContextManager["ScraperClient"]):
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url
        kwargs: dict = dict(
            timeout=SETTINGS.timeout_seconds,
            headers={"User-Agent": SETTINGS.user_agent},
            follow_redirects=True,
        )
        if base_url:
            kwargs["base_url"] = base_url
        self.client = httpx.Client(**kwargs)

    def __exit__(self, exc_type, exc, tb):
        self.client.close()
        return False

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def get(self, url: str, params: Optional[dict[str, Any]] = None) -> httpx.Response:
        response = self.client.get(url, params=params)
        response.raise_for_status()
        time.sleep(SETTINGS.sleep_seconds)
        return response

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        stop=stop_after_attempt(4),
        reraise=True,
    )
    def post_json(self, url: str, body: dict[str, Any], api_key: str) -> httpx.Response:
        response = self.client.post(
            url,
            json=body,
            headers={
                "api-key": api_key,
                "Content-Type": "application/json",
            },
        )
        response.raise_for_status()
        time.sleep(SETTINGS.sleep_seconds)
        return response

    def stream_to_file(self, url: str, destination) -> bool:
        headers = {"Referer": "https://www.dol.gov/agencies/oalj/apps/keyword-search"}
        with self.client.stream("GET", url, headers=headers) as response:
            if response.status_code in (403, 404):
                return False
            response.raise_for_status()
            with open(destination, "wb") as fh:
                for chunk in response.iter_bytes():
                    fh.write(chunk)
        return True
