"""Tests for FientaAdapter — normalize() and fetch_raw() with pagination."""
import http
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.config import settings
from app.constants import FIENTA_MAX_PAGES, TALLINN_TZ
from app.ingestion.sources.fienta import FientaAdapter
from app.ingestion.base import NormalizedEvent

# Minimal HTML wrapping a JSON-LD script for detail-page stubs
_DETAIL_HTML = (
    "<html><body>"
    '<script type="application/ld+json">'
    '{{"@type":"Event",'
    '"location":{{"@type":"Place","name":"{venue_name}",'
    '"geo":{{"@type":"GeoCoordinates","latitude":{lat},"longitude":{lng}}},'
    '"address":{{"streetAddress":"{street}","addressLocality":"Tallinn"}}}},'
    '"offers":[{{"@type":"Offer","price":"{price_min}","priceCurrency":"EUR"}},'
    '{{"@type":"Offer","price":"{price_max}","priceCurrency":"EUR"}}]}}'
    "</script>"
    "</body></html>"
)


def _detail_html(
    venue_name="TestVenue",
    lat=59.437,
    lng=24.753,
    street="Pärnu mnt 5",
    price_min="10",
    price_max="40",
):
    return _DETAIL_HTML.format(
        venue_name=venue_name,
        lat=lat,
        lng=lng,
        street=street,
        price_min=price_min,
        price_max=price_max,
    )


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
            "url": "https://fienta.com/jazz-night",
            "image_url": "https://cdn.fienta.com/img.jpg",
            "price_from_string": "From 12 EUR",
        }
        result = _adapter().normalize(raw)
        assert isinstance(result, NormalizedEvent)
        assert result.external_id == "123"
        assert result.title == "Jazz Night"
        assert result.price_hint is None
        assert (result.price_min, result.price_max, result.currency) == (
            12.0,
            None,
            "EUR",
        )
        assert result.venue_name == "Von Krahli"
        assert result.venue_address == "Rataskaevu 10"
        assert result.url == "https://fienta.com/jazz-night"
        assert result.starts_at.tzinfo is not None

    def test_minimal_event(self):
        raw = {"id": "99", "name": "Minimal", "starts_at": "2026-08-01T10:00:00+03:00"}
        result = _adapter().normalize(raw)
        assert result is not None
        assert result.external_id == "99"
        assert result.price_min is None
        assert result.currency is None
        assert result.price_hint is None

    def test_price_from_string_open_ended(self):
        raw = {
            "id": "5",
            "name": "Gig",
            "starts_at": "2026-08-01T10:00:00+03:00",
            "price_from_string": "From 28 EUR",
        }
        result = _adapter().normalize(raw)
        assert result is not None
        assert (result.price_min, result.price_max, result.currency) == (
            28.0,
            None,
            "EUR",
        )
        assert result.price_hint is None

    def test_price_from_string_free(self):
        raw = {
            "id": "6",
            "name": "Free Show",
            "starts_at": "2026-08-01T10:00:00+03:00",
            "price_from_string": "Free",
        }
        result = _adapter().normalize(raw)
        assert result is not None
        assert (result.price_min, result.price_max, result.currency) == (
            0.0,
            0.0,
            None,
        )

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

    def test_string_venue_with_top_level_address(self):
        raw = {
            "id": "41",
            "name": "Outdoor Show",
            "starts_at": "2026-12-02T18:00:00+03:00",
            "venue": "Outdoor Stage",
            "address": "Valge tänav 1, 10127 Tallinn, Harju maakond",
        }
        result = _adapter().normalize(raw)
        assert result is not None
        assert result.venue_name == "Outdoor Stage"
        assert result.venue_address == "Valge tänav 1, 10127 Tallinn, Harju maakond"

    def test_string_venue_with_non_string_top_level_address_ignored(self):
        raw = {
            "id": "42",
            "name": "Outdoor Show",
            "starts_at": "2026-12-02T18:00:00+03:00",
            "venue": "Outdoor Stage",
            "address": {"street": "Valge tänav 1"},
        }
        result = _adapter().normalize(raw)
        assert result is not None
        assert result.venue_name == "Outdoor Stage"
        assert result.venue_address is None

    def test_price_hint_ignored_price_from_listing(self):
        """Fienta no longer maps the detail-page price_hint; price comes from the
        listing price_from_string, and price_hint is left None."""
        raw = {
            "id": "60",
            "name": "Priced",
            "starts_at": "2026-12-20T19:00:00+03:00",
            "price_hint": "5 - 10 EUR",  # legacy field — must be ignored now
            "price_from_string": "10 EUR",
        }
        result = _adapter().normalize(raw)
        assert result is not None
        assert result.price_hint is None
        assert (result.price_min, result.price_max, result.currency) == (
            10.0,
            10.0,
            "EUR",
        )

    # -------------------------------------------------------------------
    # Detail merge tests
    # -------------------------------------------------------------------

    def _raw_with_detail(self, detail: dict, **overrides):
        raw = {
            "id": "200",
            "name": "Merged Event",
            "starts_at": "2026-10-01T20:00:00+03:00",
            "venue": {"name": "Listing Venue", "address": "Narva mnt 7, 10117 Tallinn, Harju maakond"},
            "price_from_string": "From 28 EUR",
            "url": "https://fienta.com/ev200",
        }
        raw.update(overrides)
        raw["_detail"] = detail
        return raw

    def test_detail_coords_filled_when_in_estonia(self):
        raw = self._raw_with_detail({"lat": 59.437, "lng": 24.753, "venue_name": None, "venue_address": None, "price_min": None, "price_max": None, "currency": None})
        result = _adapter().normalize(raw)
        assert result is not None
        assert result.lat == pytest.approx(59.437)
        assert result.lng == pytest.approx(24.753)

    def test_detail_coords_rejected_outside_estonia(self):
        raw = self._raw_with_detail({"lat": 60.169, "lng": 24.935, "venue_name": None, "venue_address": None, "price_min": None, "price_max": None, "currency": None})
        result = _adapter().normalize(raw)
        assert result is not None
        assert result.lat is None
        assert result.lng is None

    def test_detail_price_max_fills_open_ended_listing(self):
        raw = self._raw_with_detail({
            "lat": None, "lng": None, "venue_name": None, "venue_address": None,
            "price_min": 28.0, "price_max": 75.0, "currency": "EUR",
        })
        result = _adapter().normalize(raw)
        assert result is not None
        assert result.price_min == 28.0
        assert result.price_max == 75.0
        assert result.currency == "EUR"

    def test_detail_price_min_overrides_listing_free(self):
        raw = self._raw_with_detail(
            {
                "lat": None, "lng": None, "venue_name": None, "venue_address": None,
                "price_min": 10.0, "price_max": 40.0, "currency": "EUR",
            },
            price_from_string="Free",
        )
        result = _adapter().normalize(raw)
        assert result is not None
        assert result.price_min == 10.0
        assert result.price_max == 40.0

    def test_listing_price_fills_when_detail_has_no_price(self):
        raw = self._raw_with_detail({
            "lat": None, "lng": None, "venue_name": None, "venue_address": None,
            "price_min": None, "price_max": None, "currency": None,
        })
        result = _adapter().normalize(raw)
        assert result is not None
        assert result.price_min == 28.0
        assert result.price_max is None
        assert result.currency == "EUR"

    def test_venue_name_listing_wins_over_detail(self):
        raw = self._raw_with_detail({
            "lat": None, "lng": None, "venue_name": "Detail Venue", "venue_address": None,
            "price_min": None, "price_max": None, "currency": None,
        })
        result = _adapter().normalize(raw)
        assert result is not None
        assert result.venue_name == "Listing Venue"

    def test_venue_name_detail_fills_when_listing_empty(self):
        raw = self._raw_with_detail(
            {
                "lat": None, "lng": None, "venue_name": "Detail Venue", "venue_address": None,
                "price_min": None, "price_max": None, "currency": None,
            },
            venue={"name": None, "address": "Narva mnt 7, 10117 Tallinn, Harju maakond"},
        )
        result = _adapter().normalize(raw)
        assert result is not None
        assert result.venue_name == "Detail Venue"

    def test_listing_address_with_postal_code_wins(self):
        raw = self._raw_with_detail({
            "lat": None, "lng": None, "venue_name": None,
            "venue_address": "Pärnu mnt 5, Tallinn",  # no postal code
            "price_min": None, "price_max": None, "currency": None,
        })
        result = _adapter().normalize(raw)
        assert result is not None
        # listing address has postal code (10117) → wins
        assert "10117" in (result.venue_address or "")

    def test_detail_address_used_when_listing_lacks_postal_code(self):
        raw = self._raw_with_detail(
            {
                "lat": None, "lng": None, "venue_name": None,
                "venue_address": "Pärnu mnt 5, 10119 Tallinn",  # has postal code
                "price_min": None, "price_max": None, "currency": None,
            },
            venue={"name": "Venue", "address": "Vanaturu kael 3"},  # no postal code
        )
        result = _adapter().normalize(raw)
        assert result is not None
        assert "10119" in (result.venue_address or "")

    def test_normalize_without_detail_unchanged(self):
        raw = {
            "id": "300",
            "name": "No Detail",
            "starts_at": "2026-11-01T18:00:00+03:00",
            "venue": {"name": "Classic Venue", "address": "Viru 4, 10140 Tallinn, Harju maakond"},
            "price_from_string": "15 EUR",
        }
        result = _adapter().normalize(raw)
        assert result is not None
        assert result.lat is None
        assert result.lng is None
        assert result.price_min == 15.0
        assert result.price_max == 15.0
        assert result.currency == "EUR"

    def test_is_target_city_on_merged_address(self):
        raw = self._raw_with_detail(
            {
                "lat": None, "lng": None, "venue_name": None,
                "venue_address": "Ülikooli 18, 51003 Tartu, Tartumaa",
                "price_min": None, "price_max": None, "currency": None,
            },
            venue={"name": "Venue", "address": "Vanaturu kael 3"},  # no postal code, kept
        )
        # listing has no postal code → detail addr wins → Tartu → filtered
        result = _adapter().normalize(raw)
        assert result is None

    # -------------------------------------------------------------------
    # City filter tests
    # -------------------------------------------------------------------

    def _event_with_address(self, address):
        return {
            "id": "99",
            "name": "Test Event",
            "starts_at": "2026-08-01T10:00:00+03:00",
            "venue": {"name": "Venue", "address": address},
        }

    def test_tallinn_address_kept(self):
        raw = self._event_with_address("Narva maantee 63, 10152 Tallinn, Harju maakond")
        assert _adapter().normalize(raw) is not None

    def test_tartu_address_dropped(self):
        raw = self._event_with_address("Ülikooli 18, 51003 Tartu, Tartumaa")
        assert _adapter().normalize(raw) is None

    def test_parnu_address_dropped(self):
        raw = self._event_with_address("Rüütli 40, 80010 Pärnu, Pärnumaa")
        assert _adapter().normalize(raw) is None

    def test_riga_address_dropped(self):
        raw = self._event_with_address("Brīvības 55, 1010 Riga, Latvia")
        assert _adapter().normalize(raw) is None

    def test_riga_macron_address_dropped(self):
        """Latvian diacritic form — 'Rīga' (macron-i) must also be filtered."""
        raw = self._event_with_address("Brīvības 55, 1010 Rīga, Latvija")
        assert _adapter().normalize(raw) is None

    def test_vilnius_address_dropped(self):
        raw = self._event_with_address("Gedimino pr. 9, 01103 Vilnius, Lithuania")
        assert _adapter().normalize(raw) is None

    def test_non_listed_foreign_city_dropped(self):
        """Allowlist: a city never enumerated in the old denylist still drops."""
        raw = self._event_with_address("Marszałkowska 1, 00-661 Warszawa, Poland")
        assert _adapter().normalize(raw) is None

    def test_city_less_address_kept(self):
        """No postal code → city undetectable → kept (likely Tallinn)."""
        raw = self._event_with_address("Vanaturu kael 3")
        assert _adapter().normalize(raw) is not None

    def test_no_venue_address_kept(self):
        """No address at all → city-less → kept."""
        raw = {"id": "98", "name": "Mystery Venue", "starts_at": "2026-08-01T10:00:00+03:00"}
        assert _adapter().normalize(raw) is not None


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
    async def test_meta_pagination_missing_current_page_warns_and_continues(self, caplog):
        """Missing meta.current_page falls back to the local page counter and warns."""
        pages = {
            1: {"data": [{"id": "1"}], "meta": {"last_page": 2}},
            2: {"data": [{"id": "2"}], "meta": {"last_page": 2}},
        }

        async def handler(request):
            page = int(request.url.params.get("page", "1"))
            return _mock_response(pages[page])

        adapter = _adapter(organizer_ids=[1])
        with caplog.at_level(logging.WARNING):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                result = await adapter._fetch_organizer(client, settings.FIENTA_BASE_URL, 1)

        assert [e["id"] for e in result] == ["1", "2"]
        assert "current_page missing" in caplog.text

    @pytest.mark.asyncio
    async def test_meta_pagination_missing_last_page_stops(self, caplog):
        """Missing meta.last_page stops pagination immediately, without warning."""
        payload = {"data": [{"id": "1"}], "meta": {}}

        async def handler(request):
            return _mock_response(payload)

        adapter = _adapter(organizer_ids=[1])
        with caplog.at_level(logging.WARNING):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                result = await adapter._fetch_organizer(client, settings.FIENTA_BASE_URL, 1)

        assert [e["id"] for e in result] == ["1"]
        assert caplog.text == ""

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
            result = await _adapter(organizer_ids=[99, 42]).fetch_raw(set())

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
            result = await _adapter(organizer_ids=[1, 2, 3]).fetch_raw(set())

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


# ---------------------------------------------------------------------------
# fetch_raw() — detail fetch behavior
# ---------------------------------------------------------------------------

class TestFetchRawDetailFetch:
    @pytest.mark.asyncio
    async def test_detail_fetched_for_new_events(self):
        """New external_ids trigger detail fetches; _detail is attached to the raw item."""
        base = settings.FIENTA_BASE_URL
        listing = [{"id": "1", "name": "New", "url": f"{base}/event/1"}]
        detail_content = _detail_html(price_min="10", price_max="40")

        async def handler(request):
            if "/event/1" in str(request.url):
                return httpx.Response(200, text=detail_content)
            return _mock_response(listing)

        transport = httpx.MockTransport(handler)
        _real = httpx.AsyncClient
        with patch(
            "app.ingestion.sources.fienta.httpx.AsyncClient",
            lambda **kw: _real(transport=transport),
        ):
            result = await _adapter(organizer_ids=[42]).fetch_raw(set())  # no known IDs

        assert len(result) == 1
        assert "_detail" in result[0]
        assert result[0]["_detail"]["price_min"] == 10.0
        assert result[0]["_detail"]["price_max"] == 40.0

    @pytest.mark.asyncio
    async def test_detail_skipped_for_known_events(self):
        """Already-stored external_ids must not trigger detail fetches."""
        base = settings.FIENTA_BASE_URL
        listing = [{"id": "99", "name": "Known", "url": f"{base}/event/99"}]

        detail_fetched = False

        async def handler(request):
            nonlocal detail_fetched
            if "/event/99" in str(request.url):
                detail_fetched = True
                return httpx.Response(200, text=_detail_html())
            return _mock_response(listing)

        transport = httpx.MockTransport(handler)
        _real = httpx.AsyncClient
        with patch(
            "app.ingestion.sources.fienta.httpx.AsyncClient",
            lambda **kw: _real(transport=transport),
        ):
            await _adapter(organizer_ids=[42]).fetch_raw({"99"})  # already stored

        assert not detail_fetched

    @pytest.mark.asyncio
    async def test_detail_fetch_failure_degrades_gracefully(self):
        """A 500 on the detail page must not abort the listing result."""
        base = settings.FIENTA_BASE_URL
        listing = [{"id": "5", "name": "Fragile", "url": f"{base}/event/5"}]

        async def handler(request):
            if "/event/5" in str(request.url):
                return httpx.Response(500)
            return _mock_response(listing)

        transport = httpx.MockTransport(handler)
        _real = httpx.AsyncClient
        with patch(
            "app.ingestion.sources.fienta.httpx.AsyncClient",
            lambda **kw: _real(transport=transport),
        ):
            result = await _adapter(organizer_ids=[42]).fetch_raw(set())

        assert len(result) == 1
        assert "_detail" not in result[0]

    @pytest.mark.asyncio
    async def test_cross_host_detail_url_not_fetched(self):
        """A detail URL on a different host must not be fetched (SSRF guard)."""
        listing = [{"id": "7", "name": "Evil", "url": "https://evil.internal/event/7"}]

        evil_fetched = False

        async def handler(request):
            nonlocal evil_fetched
            if "evil" in str(request.url):
                evil_fetched = True
                return httpx.Response(200, text=_detail_html())
            return _mock_response(listing)

        transport = httpx.MockTransport(handler)
        _real = httpx.AsyncClient
        with patch(
            "app.ingestion.sources.fienta.httpx.AsyncClient",
            lambda **kw: _real(transport=transport),
        ):
            await _adapter(organizer_ids=[42]).fetch_raw(set())

        assert not evil_fetched

    @pytest.mark.asyncio
    async def test_detail_302_redirect_is_followed(self):
        """A 302 to a localized detail path must be followed, not dropped (regression)."""
        base = settings.FIENTA_BASE_URL
        listing = [{"id": "1", "name": "Localized", "url": f"{base}/event/1"}]
        detail_content = _detail_html(price_min="15", price_max="15")

        async def handler(request):
            if str(request.url) == f"{base}/event/1":
                return httpx.Response(
                    302, headers={"Location": f"{base}/et/event/1"}
                )
            if str(request.url) == f"{base}/et/event/1":
                return httpx.Response(200, text=detail_content)
            return _mock_response(listing)

        transport = httpx.MockTransport(handler)
        _real = httpx.AsyncClient
        with patch(
            "app.ingestion.sources.fienta.httpx.AsyncClient",
            lambda **kw: _real(
                transport=transport,
                follow_redirects=kw.get("follow_redirects", False),
                event_hooks=kw.get("event_hooks"),
            ),
        ):
            result = await _adapter(organizer_ids=[42]).fetch_raw(set())

        assert "_detail" in result[0]
        assert result[0]["_detail"]["price_min"] == 15.0

    @pytest.mark.asyncio
    async def test_cross_host_redirect_is_blocked(self):
        """A redirect to a different host must be rejected (SSRF guard), even
        though follow_redirects=True is set on the client."""
        base = settings.FIENTA_BASE_URL
        listing = [{"id": "1", "name": "Evil redirect", "url": f"{base}/event/1"}]

        async def handler(request):
            if str(request.url) == f"{base}/event/1":
                return httpx.Response(
                    302, headers={"Location": "https://evil.example.com/steal"}
                )
            return _mock_response(listing)

        transport = httpx.MockTransport(handler)
        _real = httpx.AsyncClient
        with patch(
            "app.ingestion.sources.fienta.httpx.AsyncClient",
            lambda **kw: _real(
                transport=transport,
                follow_redirects=kw.get("follow_redirects", False),
                event_hooks=kw.get("event_hooks"),
            ),
        ):
            result = await _adapter(organizer_ids=[42]).fetch_raw(set())

        # The guard raises inside the redirect-following loop; gather()
        # swallows it (return_exceptions=True), so the listing event survives
        # without enrichment rather than being sent to evil.example.com.
        assert "_detail" not in result[0]


# ---------------------------------------------------------------------------
# fetch_raw() — rate limiting + 429 retry behavior
# ---------------------------------------------------------------------------

class TestFetchRawRateLimiting:
    @pytest.mark.asyncio
    async def test_429_then_200_listing_not_dropped(self):
        """A transient 429 (with Retry-After: 0, so the retry wait is instant)
        must not drop the organizer — it should succeed on retry."""
        call_count = 0

        async def handler(request):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(429, headers={"Retry-After": "0"})
            return _mock_response([{"id": "ok"}])

        transport = httpx.MockTransport(handler)
        _real = httpx.AsyncClient
        with patch(
            "app.ingestion.sources.fienta.httpx.AsyncClient",
            lambda **kw: _real(transport=transport),
        ):
            result = await _adapter(organizer_ids=[42]).fetch_raw(set())

        assert len(result) == 1
        assert result[0]["id"] == "ok"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_limiter_acquire_called_per_listing_request(self):
        """Each listing request must go through the shared AsyncRateLimiter."""
        async def handler(request):
            return _mock_response([{"id": "1"}, {"id": "2"}])

        transport = httpx.MockTransport(handler)
        _real = httpx.AsyncClient
        with (
            patch(
                "app.ingestion.sources.fienta.httpx.AsyncClient",
                lambda **kw: _real(transport=transport),
            ),
            patch(
                "app.ingestion.sources.fienta.AsyncRateLimiter.acquire",
                new_callable=AsyncMock,
            ) as mock_acquire,
        ):
            # skip detail fetches, isolate listing calls
            await _adapter(organizer_ids=[1, 2]).fetch_raw({"1", "2"})

        assert mock_acquire.await_count == 2  # one listing request per organizer
