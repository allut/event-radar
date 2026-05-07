"""Tests for FientaAdapter — normalize() and fetch_raw() with pagination."""
import http
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

import httpx

from app.config import settings
from app.constants import FIENTA_MAX_PAGES, TALLINN_TZ
from app.ingestion.sources.fienta import FientaAdapter
from app.ingestion.base import NormalizedEvent


def _make_source(organizer_ids=None, base_url=None):
    source = MagicMock()
    source.config = {"organizer_ids": organizer_ids or [42]}
    if base_url:
        source.config["base_url"] = base_url
    return source


def _adapter(organizer_ids=None, base_url=None):
    return FientaAdapter(_make_source(organizer_ids=organizer_ids, base_url=base_url))


# ---------------------------------------------------------------------------
# normalize() — unit tests (no I/O)
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_full_event(self):
        raw = {
            "id": "123",
            "name": "Jazz Night",
            "description": "Cool jazz",
            "starts_at": "2026-06-01T20:00:00+03:00",
            "ends_at": "2026-06-01T23:00:00+03:00",
            "venue": {"name": "Von Krahli", "address": "Rataskaevu 10"},
            "price": {"min": 10, "max": 20, "currency": "EUR"},
            "url": "https://fienta.com/jazz-night",
            "image_url": "https://cdn.fienta.com/img.jpg",
        }
        result = _adapter().normalize(raw)
        assert isinstance(result, NormalizedEvent)
        assert result.external_id == "123"
        assert result.title == "Jazz Night"
        assert result.price_min == 10.0
        assert result.price_max == 20.0
        assert result.currency == "EUR"
        assert result.venue_name == "Von Krahli"
        assert result.venue_address == "Rataskaevu 10"
        assert result.url == "https://fienta.com/jazz-night"
        assert result.starts_at.tzinfo is not None

    def test_free_event_price_zero_not_swallowed(self):
        """price=0 must produce price_min=0.0, not None."""
        raw = {
            "id": "7",
            "name": "Free Concert",
            "starts_at": "2026-07-10T18:00:00+03:00",
            "price": {"min": 0, "max": 0, "currency": "EUR"},
        }
        result = _adapter().normalize(raw)
        assert result is not None
        assert result.price_min == 0.0
        assert result.price_max == 0.0

    def test_minimal_event(self):
        raw = {"id": "99", "name": "Minimal", "starts_at": "2026-08-01T10:00:00+03:00"}
        result = _adapter().normalize(raw)
        assert result is not None
        assert result.external_id == "99"
        assert result.price_min is None
        assert result.currency is None

    def test_missing_title_returns_none(self):
        raw = {"id": "1", "starts_at": "2026-08-01T10:00:00+03:00"}
        assert _adapter().normalize(raw) is None

    def test_missing_external_id_returns_none(self):
        raw = {"name": "No ID", "starts_at": "2026-08-01T10:00:00+03:00"}
        assert _adapter().normalize(raw) is None

    def test_missing_starts_at_returns_none(self):
        raw = {"id": "5", "name": "No Date"}
        assert _adapter().normalize(raw) is None

    def test_naive_datetime_gets_tallinn_tz(self):
        raw = {"id": "10", "name": "Naive", "starts_at": "2026-09-15T19:00:00"}
        result = _adapter().normalize(raw)
        assert result is not None
        assert result.starts_at.tzinfo == TALLINN_TZ

    def test_price_min_from_top_level_fields(self):
        """min_price/max_price at root level when price field is absent."""
        raw = {
            "id": "20",
            "name": "Root Price",
            "starts_at": "2026-10-01T18:00:00+03:00",
            "min_price": 5,
            "max_price": 15,
            "currency": "EUR",
        }
        result = _adapter().normalize(raw)
        assert result is not None
        assert result.price_min == 5.0
        assert result.price_max == 15.0

    def test_title_fallback_to_title_field(self):
        raw = {"id": "30", "title": "Alt Title", "starts_at": "2026-11-01T20:00:00+03:00"}
        result = _adapter().normalize(raw)
        assert result is not None
        assert result.title == "Alt Title"

    def test_venue_as_string(self):
        raw = {
            "id": "40",
            "name": "String Venue",
            "starts_at": "2026-12-01T18:00:00+03:00",
            "venue": "KUMU",
        }
        result = _adapter().normalize(raw)
        assert result is not None
        assert result.venue_name == "KUMU"
        assert result.venue_address is None

    def test_price_field_as_integer_zero_falls_back_to_top_level(self):
        """'price': 0 (integer, not dict) must not be treated as empty dict."""
        raw = {
            "id": "50",
            "name": "Int Price",
            "starts_at": "2026-12-15T20:00:00+03:00",
            "price": 0,          # non-dict — should fall through to top-level fields
            "min_price": 5,
            "max_price": 10,
            "currency": "EUR",
        }
        result = _adapter().normalize(raw)
        assert result is not None
        assert result.price_min == 5.0
        assert result.price_max == 10.0


# ---------------------------------------------------------------------------
# fetch_raw() + pagination — async tests using httpx mock transport
# ---------------------------------------------------------------------------

def _mock_response(json_data, status_code=http.HTTPStatus.OK):
    return httpx.Response(status_code, json=json_data)


class TestFetchRaw:
    @pytest.mark.asyncio
    async def test_plain_list_response(self):
        """API returns a bare list — no pagination needed."""
        events = [{"id": "1", "name": "A"}, {"id": "2", "name": "B"}]

        async def handler(request):
            return _mock_response(events)

        adapter = _adapter(organizer_ids=[42])
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await adapter._fetch_organizer(client, settings.FIENTA_BASE_URL, 42)

        assert len(result) == 2
        assert result[0]["id"] == "1"

    @pytest.mark.asyncio
    async def test_data_envelope_single_page(self):
        """API wraps events in {data: [...], meta: {last_page: 1}}."""
        payload = {"data": [{"id": "10"}], "meta": {"current_page": 1, "last_page": 1}}

        async def handler(request):
            return _mock_response(payload)

        adapter = _adapter(organizer_ids=[1])
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await adapter._fetch_organizer(client, settings.FIENTA_BASE_URL, 1)

        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_meta_pagination_two_pages(self):
        """Meta-based pagination fetches page 2 when last_page=2."""
        pages = {
            1: {"data": [{"id": "1"}], "meta": {"current_page": 1, "last_page": 2}},
            2: {"data": [{"id": "2"}], "meta": {"current_page": 2, "last_page": 2}},
        }

        async def handler(request):
            page = int(request.url.params.get("page", "1"))
            return _mock_response(pages[page])

        adapter = _adapter(organizer_ids=[1])
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await adapter._fetch_organizer(client, settings.FIENTA_BASE_URL, 1)

        assert [e["id"] for e in result] == ["1", "2"]

    @pytest.mark.asyncio
    async def test_links_next_pagination(self):
        """Link-based pagination follows links.next until absent."""
        base = settings.FIENTA_BASE_URL
        page1 = {"data": [{"id": "A"}], "links": {"next": f"{base}?page=2"}}
        page2 = {"data": [{"id": "B"}], "links": {"next": None}}

        call_count = 0

        async def handler(request):
            nonlocal call_count
            call_count += 1
            if "page=2" in str(request.url):
                return _mock_response(page2)
            return _mock_response(page1)

        adapter = _adapter(organizer_ids=[1])
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await adapter._fetch_organizer(client, base, 1)

        assert [e["id"] for e in result] == ["A", "B"]
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_links_next_host_mismatch_stops_pagination(self):
        """links.next pointing to a different host must not be followed (SSRF guard)."""
        base = settings.FIENTA_BASE_URL
        page1 = {"data": [{"id": "A"}], "links": {"next": "https://evil.internal/steal"}}

        async def handler(request):
            if "evil" in str(request.url):
                raise AssertionError("SSRF: should not follow cross-host next URL")
            return _mock_response(page1)

        adapter = _adapter(organizer_ids=[1])
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result = await adapter._fetch_organizer(client, base, 1)

        assert [e["id"] for e in result] == ["A"]

    @pytest.mark.asyncio
    async def test_per_organizer_error_isolation(self):
        """A 404 on one organizer must not abort fetching others."""
        async def handler(request):
            org = request.url.params.get("organizer")
            if org == "99":
                return httpx.Response(http.HTTPStatus.NOT_FOUND)
            return _mock_response([{"id": "ok"}])

        transport = httpx.MockTransport(handler)
        _real = httpx.AsyncClient  # capture before patch replaces the name
        with patch(
            "app.ingestion.sources.fienta.httpx.AsyncClient",
            lambda **kw: _real(transport=transport),
        ):
            result = await _adapter(organizer_ids=[99, 42]).fetch_raw()

        assert len(result) == 1
        assert result[0]["id"] == "ok"

    @pytest.mark.asyncio
    async def test_multiple_organizers_aggregated(self):
        """Events from multiple organizers are all returned."""
        async def handler(request):
            org = request.url.params.get("organizer")
            return _mock_response([{"id": f"org{org}-ev1"}, {"id": f"org{org}-ev2"}])

        transport = httpx.MockTransport(handler)
        _real = httpx.AsyncClient
        with patch(
            "app.ingestion.sources.fienta.httpx.AsyncClient",
            lambda **kw: _real(transport=transport),
        ):
            result = await _adapter(organizer_ids=[1, 2, 3]).fetch_raw()

        assert len(result) == 6

    @pytest.mark.asyncio
    async def test_meta_pagination_ceiling(self):
        """Meta-based pagination stops at FIENTA_MAX_PAGES even if last_page is huge."""
        request_count = 0

        async def handler(request):
            nonlocal request_count
            request_count += 1
            page = int(request.url.params.get("page", "1"))
            return _mock_response({
                "data": [{"id": str(page)}],
                "meta": {"current_page": page, "last_page": 9999},
            })

        adapter = _adapter(organizer_ids=[1])
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await adapter._fetch_organizer(client, settings.FIENTA_BASE_URL, 1)

        assert request_count == FIENTA_MAX_PAGES

    @pytest.mark.asyncio
    async def test_links_pagination_ceiling(self):
        """Link-based pagination stops at FIENTA_MAX_PAGES total requests per organizer."""
        base = settings.FIENTA_BASE_URL
        request_count = 0

        async def handler(request):
            nonlocal request_count
            request_count += 1
            page = int(request.url.params.get("page", "1"))
            return _mock_response({
                "data": [{"id": str(page)}],
                "links": {"next": f"{base}?page={page + 1}"},
            })

        adapter = _adapter(organizer_ids=[1])
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await adapter._fetch_organizer(client, base, 1)

        assert request_count == FIENTA_MAX_PAGES
