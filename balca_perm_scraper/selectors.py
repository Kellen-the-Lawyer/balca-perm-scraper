from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResultSelectors:
    result_container: str = "[data-search-results], .usa-search-results, .views-row, .search-result"
    result_item: str = "article, .views-row, li, .search-result"
    title_link: str = "h2 a, h3 a, .search-result__title a, a"
    snippet: str = ".search-result__snippet, .views-field-search-api-excerpt, p"
    pdf_link: str = "a[href$='.pdf'], a[href*='.pdf?']"
    metadata: str = ".search-result__meta, .views-field, .usa-collection__body"
    next_link: str = "a[rel='next'], .pager__next a, .usa-pagination__next a"


SELECTORS = ResultSelectors()
