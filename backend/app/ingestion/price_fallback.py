"""Selector-based price fallback registry (#424).

refetch.py's detail-page reconciliation and pinning.py's claim
price-mismatch check both read price via schema.org Event/offers JSON-LD
first; some sources (KUMU today) carry no such block at all, so both callers
fall back to a per-host, selector-based extractor. One shared dict keeps the
two dispatch sites in sync — a host added here takes effect in both places.
"""

from collections.abc import Callable

from bs4 import BeautifulSoup

from app.ingestion.selectors import KUMU_HOST
from app.ingestion.sources.kumu import kumu_price_bounds

PriceFallbackExtractor = Callable[
    [BeautifulSoup], tuple[float | None, float | None, str | None, bool]
]

PRICE_FALLBACK_EXTRACTORS: dict[str, PriceFallbackExtractor] = {
    KUMU_HOST: kumu_price_bounds,
}
