"""Tests for app/ingestion/sources/kumu.py's kumu_price_bounds (#424)."""

from bs4 import BeautifulSoup

from app._generated.shared_constants import DEFAULT_CURRENCY
from app.constants.core import HTML_PARSER
from app.ingestion.sources.kumu import kumu_price_bounds


def _price_html(inner: str) -> BeautifulSoup:
    html = f'<div class="event-header__ticket-price">{inner}</div>'
    return BeautifulSoup(html, HTML_PARSER)


class TestKumuPriceBounds:
    def test_no_price_tag_returns_none(self):
        soup = BeautifulSoup("<html></html>", HTML_PARSER)
        assert kumu_price_bounds(soup) == (None, None, None, False)

    def test_single_price_returns_exact_bounds(self):
        soup = _price_html("&euro;16")
        assert kumu_price_bounds(soup) == (16.0, 16.0, DEFAULT_CURRENCY, False)

    def test_multiple_tiers_return_min_max_span(self):
        soup = _price_html(
            '<span>Adult:</span>&euro;16'
            '<div class="tooltip-list__item">'
            '<span class="tooltip-list__item-title">Family:</span>'
            '<span class="tooltip-list__item-value">&euro;32</span>'
            "</div>"
        )
        assert kumu_price_bounds(soup) == (16.0, 32.0, DEFAULT_CURRENCY, False)

    def test_no_parseable_amount_returns_none(self):
        soup = _price_html("Free")
        assert kumu_price_bounds(soup) == (None, None, None, False)

    def test_fee_clause_is_stripped_from_bounds(self):
        # "agenditasu 3,20 €" must not be mistaken for a real ticket price
        # (mirrors classify_event's strip_fee_amounts step, #424 review).
        soup = _price_html("agenditasu 3,20 &euro; Pilet 45 &euro;")
        assert kumu_price_bounds(soup) == (45.0, 45.0, DEFAULT_CURRENCY, False)

    def test_hint_truncated_to_price_hint_max_chars(self):
        # A tier past PRICE_HINT_MAX_CHARS must not surface here either — it
        # never reached the stored price_hint at ingest time, so treating it
        # as a "price changed" diff would be a false positive.
        from app.constants.ingestion import PRICE_HINT_MAX_CHARS

        padding = "x" * (PRICE_HINT_MAX_CHARS + 10)
        soup = _price_html(f"&euro;16 {padding} &euro;9999")
        price_min, price_max, _currency, _free = kumu_price_bounds(soup)
        assert price_max != 9999.0
