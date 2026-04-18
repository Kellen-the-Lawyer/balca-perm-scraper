from __future__ import annotations

from urllib.parse import urljoin

BASE_URL = "https://www.dol.gov"
AZURE_SEARCH_SERVICE = "oasam-prod-pace-oaljsearch-ue-search-public"
AZURE_SEARCH_INDEX = "oalj-search-prod"
AZURE_API_VERSION = "2017-11-11"
KEYWORD_SEARCH_URL = (
    f"https://{AZURE_SEARCH_SERVICE}.search.windows.net"
    f"/indexes/{AZURE_SEARCH_INDEX}/docs/search"
    f"?api-version={AZURE_API_VERSION}"
)


def absolute_url(url: str) -> str:
    return urljoin(BASE_URL, url)
