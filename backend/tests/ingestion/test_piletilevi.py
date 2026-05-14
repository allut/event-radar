"""Tests for PiletileviAdapter — normalize(), fetch_raw(), and _parse_piletilevi_date()."""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.ingestion.sources.piletilevi import PiletileviAdapter, _parse_piletilevi_date
from app.ingestion.base import NormalizedEvent
from app.constants import TALLINN_TZ, PILETILEVI_BASE_URL


def _make_source():
    source = MagicMock()
    source.slug = "piletilevi"
    source.config = {}
    return source


def _adapter():
    return PiletileviAdapter(_make_source())


def _raw(**kwargs):
    defaults = {
        "href": "/en/tickets/ABC123/test-event",
        "title": "Jazz Night",
        "date_str": "We 19.08.2026 • 19:00",
        "venue": "Jazz Club, Tallinn",
        "image_url": None,
        "description": "A great jazz concert.",
    }
    return {**defaults, **kwargs}


# ---------------------------------------------------------------------------
# _parse_piletilevi_date
# ---------------------------------------------------------------------------

class TestDateParsing:
    def test_standard_date_time(self):
        result = _parse_piletilevi_date("We 19.08.2026 • 19:00")
        assert result is not None
        assert result.year == 2026
        assert result.month == 8
        assert result.day == 19
        assert result.hour == 19
        assert result.minute == 0
        assert result.tzinfo == TALLINN_TZ

    def test_midnight(self):
        result = _parse_piletilevi_date("Fr 01.01.2027 • 00:00")
        assert result is not None
        assert result.hour == 0
        assert result.minute == 0

    def test_malformed_no_bullet(self):
        assert _parse_piletilevi_date("19.08.2026 19:00") is None

    def test_empty_string(self):
        assert _parse_piletilevi_date("") is None

    def test_different_weekday_abbreviation(self):
        result = _parse_piletilevi_date("Sa 15.03.2026 • 14:30")
        assert result is not None
        assert result.day == 15
        assert result.month == 3
        assert result.hour == 14
        assert result.minute == 30

    def test_wrong_date_format(self):
        assert _parse_piletilevi_date("Mo 2026-08-19 • 19:00") is None


# ---------------------------------------------------------------------------
# normalize()
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_happy_path_all_fields(self):
        adapter = _adapter()
        result = adapter.normalize(_raw())
        assert isinstance(result, NormalizedEvent)
        assert result.title == "Jazz Night"
        assert result.external_id == "/en/tickets/ABC123/test-event"
        assert result.venue_name == "Jazz Club, Tallinn"
        assert result.description == "A great jazz concert."
        assert result.url == PILETILEVI_BASE_URL + "/en/tickets/ABC123/test-event"

    def test_external_id_is_href(self):
        adapter = _adapter()
        result = adapter.normalize(_raw(href="/en/tickets/XYZ/my-event"))
        assert result.external_id == "/en/tickets/XYZ/my-event"

    def test_url_is_absolute(self):
        adapter = _adapter()
        result = adapter.normalize(_raw(href="/en/tickets/XYZ/my-event"))
        assert result.url == PILETILEVI_BASE_URL + "/en/tickets/XYZ/my-event"

    def test_missing_title_returns_none(self):
        adapter = _adapter()
        assert adapter.normalize(_raw(title="")) is None

    def test_missing_href_returns_none(self):
        adapter = _adapter()
        assert adapter.normalize(_raw(href="")) is None

    def test_missing_date_returns_none(self):
        adapter = _adapter()
        assert adapter.normalize(_raw(date_str="")) is None

    def test_malformed_date_returns_none(self):
        adapter = _adapter()
        assert adapter.normalize(_raw(date_str="not a date")) is None

    def test_starts_at_is_tz_aware(self):
        adapter = _adapter()
        result = adapter.normalize(_raw())
        assert result.starts_at.tzinfo is not None

    def test_image_url_relative_becomes_absolute(self):
        adapter = _adapter()
        result = adapter.normalize(_raw(image_url="/media/img/event.jpg"))
        assert result.image_url == PILETILEVI_BASE_URL + "/media/img/event.jpg"

    def test_image_url_absolute_unchanged(self):
        adapter = _adapter()
        result = adapter.normalize(_raw(image_url="https://cdn.piletilevi.ee/img.jpg"))
        assert result.image_url == "https://cdn.piletilevi.ee/img.jpg"

    def test_image_url_none_when_absent(self):
        adapter = _adapter()
        result = adapter.normalize(_raw(image_url=None))
        assert result.image_url is None

    def test_no_price_fields(self):
        adapter = _adapter()
        result = adapter.normalize(_raw())
        assert result.price_min is None
        assert result.price_max is None
        assert result.currency is None


# ---------------------------------------------------------------------------
# fetch_raw() — listing page parsing
# ---------------------------------------------------------------------------

LISTING_HTML = """
<html><body>
  <a class="card" href="/en/tickets/AA1/jazz-night">
    <div class="card__time-title"><h3>Jazz Night</h3></div>
    <div class="card__time">We 19.08.2026 • 19:00</div>
    <div class="card__description">Jazz Club, Tallinn</div>
  </a>
  <a class="card" href="/en/tickets/BB2/riga-rock">
    <div class="card__time-title"><h3>Riga Rock</h3></div>
    <div class="card__time">Fr 21.08.2026 • 20:00</div>
    <div class="card__description">Rock Arena, Riga</div>
  </a>
  <a class="card" href="/en/tickets/CC3/folk-fest">
    <div class="card__time-title"><h3>Folk Fest</h3></div>
    <div class="card__time">Sa 22.08.2026 • 14:00</div>
    <div class="card__description">Folk Hall, Tallinn</div>
  </a>
</body></html>
"""

DETAIL_HTML = """
<html><body>
  <div class="event__description">A wonderful jazz evening with local musicians.</div>
</body></html>
"""

EMPTY_LISTING_HTML = "<html><body></body></html>"


def _mock_response(text: str, status: int = 200):
    resp = MagicMock(spec=httpx.Response)
    resp.text = text
    resp.status_code = status
    return resp


class TestFetchRaw:
    @pytest.mark.asyncio
    async def test_listing_parsed_cards_extracted(self):
        adapter = _adapter()
        listing_resp = _mock_response(LISTING_HTML)
        detail_resp = _mock_response(DETAIL_HTML)

        with patch("app.ingestion.sources.piletilevi._http_get") as mock_get:
            mock_get.side_effect = [
                listing_resp,  # single listing URL
                detail_resp,   # detail for Jazz Night (Tallinn)
                detail_resp,   # detail for Folk Fest (Tallinn)
            ]
            with patch("app.ingestion.sources.piletilevi.PILETILEVI_LISTING_URLS", ["/eng/tickets/"]):
                results = await adapter.fetch_raw()

        assert len(results) == 2  # Riga card filtered out
        titles = [r["title"] for r in results]
        assert "Jazz Night" in titles
        assert "Folk Fest" in titles
        assert "Riga Rock" not in titles

    @pytest.mark.asyncio
    async def test_non_tallinn_cards_filtered(self):
        adapter = _adapter()
        listing_resp = _mock_response(LISTING_HTML)
        detail_resp = _mock_response(DETAIL_HTML)

        with patch("app.ingestion.sources.piletilevi._http_get") as mock_get:
            mock_get.side_effect = [listing_resp, detail_resp, detail_resp]
            with patch("app.ingestion.sources.piletilevi.PILETILEVI_LISTING_URLS", ["/eng/tickets/"]):
                results = await adapter.fetch_raw()

        assert all(
            "Tallinn" in r["venue"] or not r["venue"]
            for r in results
        )

    @pytest.mark.asyncio
    async def test_deduplication_across_listing_urls(self):
        """Same href on two listing pages should only appear once."""
        adapter = _adapter()

        dupe_html = """
        <html><body>
          <a class="card" href="/en/tickets/AA1/jazz-night">
            <div class="card__time-title"><h3>Jazz Night</h3></div>
            <div class="card__time">We 19.08.2026 • 19:00</div>
            <div class="card__description">Jazz Club, Tallinn</div>
          </a>
        </body></html>
        """
        listing_resp = _mock_response(dupe_html)
        detail_resp = _mock_response(DETAIL_HTML)

        with patch("app.ingestion.sources.piletilevi._http_get") as mock_get:
            # Two listing URLs, same card on both
            mock_get.side_effect = [
                listing_resp,  # first listing URL
                listing_resp,  # second listing URL
                detail_resp,   # detail for deduplicated card
            ]
            with patch("app.ingestion.sources.piletilevi.PILETILEVI_LISTING_URLS", ["/eng/tickets/", "/eng/tickets/concerts/"]):
                results = await adapter.fetch_raw()

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_detail_description_merged(self):
        adapter = _adapter()
        listing_resp = _mock_response("""
        <html><body>
          <a class="card" href="/en/tickets/AA1/jazz-night">
            <div class="card__time-title"><h3>Jazz Night</h3></div>
            <div class="card__time">We 19.08.2026 • 19:00</div>
            <div class="card__description">Jazz Club, Tallinn</div>
          </a>
        </body></html>
        """)
        detail_resp = _mock_response(DETAIL_HTML)

        with patch("app.ingestion.sources.piletilevi._http_get") as mock_get:
            mock_get.side_effect = [listing_resp, detail_resp]
            with patch("app.ingestion.sources.piletilevi.PILETILEVI_LISTING_URLS", ["/eng/tickets/"]):
                results = await adapter.fetch_raw()

        assert len(results) == 1
        assert results[0]["description"] == "A wonderful jazz evening with local musicians."

    @pytest.mark.asyncio
    async def test_empty_listing_returns_empty_list(self):
        adapter = _adapter()
        with patch("app.ingestion.sources.piletilevi._http_get") as mock_get:
            mock_get.return_value = _mock_response(EMPTY_LISTING_HTML)
            with patch("app.ingestion.sources.piletilevi.PILETILEVI_LISTING_URLS", ["/eng/tickets/"]):
                results = await adapter.fetch_raw()

        assert results == []
