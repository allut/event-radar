"""Tests for JsonLdAdapter — _extract_jsonld_events, normalize(), and fetch_raw()."""
import http
import json
import pytest
from unittest.mock import MagicMock

import httpx

from app.ingestion.sources.jsonld import JsonLdAdapter, _extract_jsonld_events
from app.ingestion.base import NormalizedEvent
from app.constants import TALLINN_TZ


def _make_source(url="https://example.com/events"):
    source = MagicMock()
    source.slug = "test-venue"
    source.config = {"url": url}
    return source


def _adapter(url="https://example.com/events"):
    return JsonLdAdapter(_make_source(url=url))


# ---------------------------------------------------------------------------
# _extract_jsonld_events — HTML parsing
# ---------------------------------------------------------------------------

class TestExtractJsonldEvents:
    def test_single_event_script(self):
        html = """<html><body>
        <script type="application/ld+json">
        {"@type": "Event", "name": "Jazz Night", "url": "https://ex.com/jazz"}
        </script></body></html>"""
        events = _extract_jsonld_events(html)
        assert len(events) == 1
        assert events[0]["name"] == "Jazz Night"

    def test_multiple_event_scripts(self):
        html = """<html><body>
        <script type="application/ld+json">{"@type": "Event", "name": "A", "url": "https://ex.com/a"}</script>
        <script type="application/ld+json">{"@type": "Event", "name": "B", "url": "https://ex.com/b"}</script>
        </body></html>"""
        events = _extract_jsonld_events(html)
        assert len(events) == 2

    def test_non_event_script_ignored(self):
        html = """<html><body>
        <script type="application/ld+json">{"@type": "Organization", "name": "Venue Inc"}</script>
        <script type="application/ld+json">{"@type": "Event", "name": "Show", "url": "https://ex.com/show"}</script>
        </body></html>"""
        events = _extract_jsonld_events(html)
        assert len(events) == 1
        assert events[0]["name"] == "Show"

    def test_music_event_subtype_included(self):
        html = """<html><body>
        <script type="application/ld+json">{"@type": "MusicEvent", "name": "Gig", "url": "https://ex.com/gig"}</script>
        </body></html>"""
        events = _extract_jsonld_events(html)
        assert len(events) == 1

    def test_list_of_events_in_single_script(self):
        html = """<html><body>
        <script type="application/ld+json">
        [
          {"@type": "Event", "name": "X", "url": "https://ex.com/x"},
          {"@type": "Event", "name": "Y", "url": "https://ex.com/y"}
        ]
        </script></body></html>"""
        events = _extract_jsonld_events(html)
        assert len(events) == 2

    def test_graph_wrapper_extracted(self):
        """Events nested under @graph must be collected."""
        html = """<html><body>
        <script type="application/ld+json">
        {"@context": "https://schema.org", "@graph": [
          {"@type": "Event", "name": "Graph Event", "url": "https://ex.com/g"}
        ]}
        </script></body></html>"""
        events = _extract_jsonld_events(html)
        assert len(events) == 1
        assert events[0]["name"] == "Graph Event"

    def test_invalid_json_script_skipped(self):
        html = """<html><body>
        <script type="application/ld+json">NOT JSON AT ALL</script>
        <script type="application/ld+json">{"@type": "Event", "name": "Valid", "url": "https://ex.com/v"}</script>
        </body></html>"""
        events = _extract_jsonld_events(html)
        assert len(events) == 1

    def test_no_scripts_returns_empty(self):
        assert _extract_jsonld_events("<html><body>Nothing here</body></html>") == []

    def test_type_as_list(self):
        """@type can be an array; first element is checked."""
        html = """<html><body>
        <script type="application/ld+json">
        {"@type": ["Event", "MusicEvent"], "name": "Mixed", "url": "https://ex.com/m"}
        </script></body></html>"""
        events = _extract_jsonld_events(html)
        assert len(events) == 1


# ---------------------------------------------------------------------------
# normalize() — unit tests
# ---------------------------------------------------------------------------

class TestNormalize:
    def _raw(self, **overrides):
        base = {
            "@type": "Event",
            "name": "Test Event",
            "url": "https://ex.com/test-event",
            "startDate": "2026-06-01T20:00:00+03:00",
        }
        base.update(overrides)
        return base

    def test_minimal_event(self):
        result = _adapter().normalize(self._raw())
        assert isinstance(result, NormalizedEvent)
        assert result.title == "Test Event"
        assert result.external_id == "https://ex.com/test-event"
        assert result.starts_at.tzinfo is not None

    def test_missing_name_returns_none(self):
        assert _adapter().normalize({"@type": "Event", "url": "https://ex.com/e", "startDate": "2026-01-01T10:00:00+03:00"}) is None

    def test_missing_url_and_id_returns_none(self):
        assert _adapter().normalize({"@type": "Event", "name": "No URL", "startDate": "2026-01-01T10:00:00+03:00"}) is None

    def test_missing_start_date_returns_none(self):
        assert _adapter().normalize({"@type": "Event", "name": "No Date", "url": "https://ex.com/e"}) is None

    def test_naive_datetime_gets_tallinn_tz(self):
        result = _adapter().normalize(self._raw(startDate="2026-09-15T19:00:00"))
        assert result is not None
        assert result.starts_at.tzinfo == TALLINN_TZ

    def test_end_date_parsed(self):
        result = _adapter().normalize(self._raw(endDate="2026-06-01T22:00:00+03:00"))
        assert result is not None
        assert result.ends_at is not None

    def test_location_place_dict(self):
        location = {
            "@type": "Place",
            "name": "KUMU Art Museum",
            "address": {"streetAddress": "Weizenbergi 34", "addressLocality": "Tallinn"},
        }
        result = _adapter().normalize(self._raw(location=location))
        assert result is not None
        assert result.venue_name == "KUMU Art Museum"
        assert result.venue_address == "Weizenbergi 34, Tallinn"

    def test_location_with_geo(self):
        location = {
            "@type": "Place",
            "name": "Park",
            "geo": {"latitude": 59.437, "longitude": 24.753},
        }
        result = _adapter().normalize(self._raw(location=location))
        assert result is not None
        assert result.lat == pytest.approx(59.437)
        assert result.lng == pytest.approx(24.753)

    def test_location_list_takes_first(self):
        locations = [
            {"@type": "Place", "name": "First Venue"},
            {"@type": "Place", "name": "Second Venue"},
        ]
        result = _adapter().normalize(self._raw(location=locations))
        assert result is not None
        assert result.venue_name == "First Venue"

    def test_offers_single_dict(self):
        result = _adapter().normalize(self._raw(offers={"@type": "Offer", "price": "15", "priceCurrency": "EUR"}))
        assert result is not None
        assert result.price_min == 15.0
        assert result.price_max == 15.0
        assert result.currency == "EUR"

    def test_offers_list_min_max(self):
        """Multiple offers — price_min/max derive from the range."""
        result = _adapter().normalize(self._raw(offers=[
            {"@type": "Offer", "price": "10", "priceCurrency": "EUR"},
            {"@type": "Offer", "price": "25", "priceCurrency": "EUR"},
        ]))
        assert result is not None
        assert result.price_min == 10.0
        assert result.price_max == 25.0

    def test_free_event_price_zero(self):
        result = _adapter().normalize(self._raw(offers={"@type": "Offer", "price": 0, "priceCurrency": "EUR"}))
        assert result is not None
        assert result.price_min == 0.0
        assert result.price_max == 0.0

    def test_no_offers_no_currency(self):
        result = _adapter().normalize(self._raw())
        assert result is not None
        assert result.price_min is None
        assert result.currency is None

    def test_image_as_string(self):
        result = _adapter().normalize(self._raw(image="https://ex.com/img.jpg"))
        assert result is not None
        assert result.image_url == "https://ex.com/img.jpg"

    def test_image_as_list(self):
        result = _adapter().normalize(self._raw(image=["https://ex.com/img1.jpg", "https://ex.com/img2.jpg"]))
        assert result is not None
        assert result.image_url == "https://ex.com/img1.jpg"

    def test_image_as_dict(self):
        result = _adapter().normalize(self._raw(image={"@type": "ImageObject", "url": "https://ex.com/img.jpg"}))
        assert result is not None
        assert result.image_url == "https://ex.com/img.jpg"

    def test_at_id_used_as_external_id_when_no_url(self):
        raw = {
            "@type": "Event",
            "@id": "https://ex.com/events/42",
            "name": "Id Event",
            "startDate": "2026-10-01T18:00:00+03:00",
        }
        result = _adapter().normalize(raw)
        assert result is not None
        assert result.external_id == "https://ex.com/events/42"


# ---------------------------------------------------------------------------
# fetch_raw() — async tests using httpx mock transport
# ---------------------------------------------------------------------------

def _html_with_events(*events: dict) -> str:
    scripts = "\n".join(
        f'<script type="application/ld+json">{json.dumps(e)}</script>'
        for e in events
    )
    return f"<html><body>{scripts}</body></html>"


class TestFetchRaw:
    @pytest.mark.asyncio
    async def test_returns_extracted_events(self):
        event = {"@type": "Event", "name": "Fetched Event", "url": "https://ex.com/e"}
        html = _html_with_events(event)

        async def handler(request):
            return httpx.Response(http.HTTPStatus.OK, html=html)

        adapter = JsonLdAdapter(_make_source("https://example.com/events"))
        # Patch the httpx.AsyncClient used inside fetch_raw
        from unittest.mock import patch
        _real = httpx.AsyncClient
        with patch(
            "app.ingestion.sources.jsonld.httpx.AsyncClient",
            lambda **kw: _real(transport=httpx.MockTransport(handler), follow_redirects=True),
        ):
            result = await adapter.fetch_raw()

        assert len(result) == 1
        assert result[0]["name"] == "Fetched Event"

    @pytest.mark.asyncio
    async def test_non_event_jsonld_excluded(self):
        """Script tags with non-Event @type must not be returned."""
        org = {"@type": "Organization", "name": "Organizer"}
        event = {"@type": "MusicEvent", "name": "Gig", "url": "https://ex.com/gig"}
        html = _html_with_events(org, event)

        async def handler(request):
            return httpx.Response(http.HTTPStatus.OK, html=html)

        adapter = JsonLdAdapter(_make_source("https://example.com/events"))
        from unittest.mock import patch
        _real = httpx.AsyncClient
        with patch(
            "app.ingestion.sources.jsonld.httpx.AsyncClient",
            lambda **kw: _real(transport=httpx.MockTransport(handler), follow_redirects=True),
        ):
            result = await adapter.fetch_raw()

        assert len(result) == 1
        assert result[0]["name"] == "Gig"

    @pytest.mark.asyncio
    async def test_http_error_propagates(self):
        """HTTP errors propagate so IngestionRun.error is recorded by base.py."""
        async def handler(request):
            return httpx.Response(http.HTTPStatus.NOT_FOUND)  # non-retryable — re-raises immediately

        adapter = JsonLdAdapter(_make_source("https://example.com/events"))
        from unittest.mock import patch
        _real = httpx.AsyncClient
        with patch(
            "app.ingestion.sources.jsonld.httpx.AsyncClient",
            lambda **kw: _real(transport=httpx.MockTransport(handler), follow_redirects=True),
        ):
            with pytest.raises(httpx.HTTPStatusError):
                await adapter.fetch_raw()

    @pytest.mark.asyncio
    async def test_empty_page_returns_empty_list(self):
        async def handler(request):
            return httpx.Response(http.HTTPStatus.OK, html="<html><body>No events</body></html>")

        adapter = JsonLdAdapter(_make_source("https://example.com/events"))
        from unittest.mock import patch
        _real = httpx.AsyncClient
        with patch(
            "app.ingestion.sources.jsonld.httpx.AsyncClient",
            lambda **kw: _real(transport=httpx.MockTransport(handler), follow_redirects=True),
        ):
            result = await adapter.fetch_raw()

        assert result == []
