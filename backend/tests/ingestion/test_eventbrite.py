"""Tests for EventbriteAdapter — normalize() and fetch_raw()."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.ingestion.sources.eventbrite import (
    EventbriteAdapter,
    _parse_eb_price,
    _to_float,
)
from app.ingestion.base import NormalizedEvent


def _make_source(api_key: str = "test_key") -> MagicMock:
    source = MagicMock()
    source.slug = "eventbrite"
    source.config = {"api_key": api_key}
    return source


def _adapter(api_key: str = "test_key") -> EventbriteAdapter:
    return EventbriteAdapter(_make_source(api_key=api_key))


def _minimal_raw() -> dict:
    return {
        "id": "EB001",
        "name": {"text": "Jazz Night"},
        "url": "https://www.eventbrite.com/e/EB001",
        "start": {"utc": "2026-07-01T20:00:00Z"},
        "end": {"utc": "2026-07-01T23:00:00Z"},
    }


# ---------------------------------------------------------------------------
# normalize() — unit tests (no I/O)
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_full_event(self):
        raw = {
            "id": "EB001",
            "name": {"text": "Jazz Night"},
            "url": "https://www.eventbrite.com/e/EB001",
            "start": {"utc": "2026-07-01T20:00:00Z"},
            "end": {"utc": "2026-07-01T23:00:00Z"},
            "venue": {
                "name": "Kultuurikatel",
                "latitude": "59.4328",
                "longitude": "24.7293",
                "address": {"localized_address_display": "Põhja pst 27a, Tallinn"},
            },
            "ticket_classes": [{"cost": {"value": 1500, "currency": "EUR"}}],
            "logo": {"url": "https://img.eventbrite.com/img.jpg"},
            "description": {"text": "A wonderful jazz evening."},
        }
        result = _adapter().normalize(raw)
        assert isinstance(result, NormalizedEvent)
        assert result.external_id == "EB001"
        assert result.title == "Jazz Night"
        assert result.starts_at is not None
        assert result.ends_at is not None
        assert result.venue_name == "Kultuurikatel"
        assert result.venue_address == "Põhja pst 27a, Tallinn"
        assert abs(result.lat - 59.4328) < 0.0001
        assert abs(result.lng - 24.7293) < 0.0001
        assert result.price_min == 15.0
        assert result.price_max == 15.0
        assert result.currency == "EUR"
        assert result.image_url == "https://img.eventbrite.com/img.jpg"
        assert result.url == "https://www.eventbrite.com/e/EB001"
        assert result.description == "A wonderful jazz evening."

    def test_missing_name_returns_none(self):
        raw = _minimal_raw()
        raw["name"] = {"text": ""}
        assert _adapter().normalize(raw) is None

    def test_no_name_key_returns_none(self):
        raw = _minimal_raw()
        del raw["name"]
        assert _adapter().normalize(raw) is None

    def test_missing_id_returns_none(self):
        raw = _minimal_raw()
        del raw["id"]
        assert _adapter().normalize(raw) is None

    def test_missing_start_returns_none(self):
        raw = _minimal_raw()
        del raw["start"]
        assert _adapter().normalize(raw) is None

    def test_invalid_start_returns_none(self):
        raw = _minimal_raw()
        raw["start"] = {"utc": "not-a-date"}
        assert _adapter().normalize(raw) is None

    def test_no_venue_is_ok(self):
        raw = _minimal_raw()
        result = _adapter().normalize(raw)
        assert isinstance(result, NormalizedEvent)
        assert result.venue_name is None
        assert result.lat is None
        assert result.lng is None

    def test_no_ticket_classes_gives_none_price(self):
        raw = _minimal_raw()
        result = _adapter().normalize(raw)
        assert result.price_min is None
        assert result.price_max is None

    def test_free_event(self):
        raw = {**_minimal_raw(), "is_free": True}
        result = _adapter().normalize(raw)
        assert result.price_min == 0.0
        assert result.price_max == 0.0
        assert result.currency == "EUR"

    def test_description_fallback_to_summary(self):
        raw = {**_minimal_raw(), "summary": "Short summary."}
        result = _adapter().normalize(raw)
        assert result.description == "Short summary."

    def test_description_prefers_description_text(self):
        raw = {**_minimal_raw(), "description": {"text": "Full desc."}, "summary": "Short."}
        result = _adapter().normalize(raw)
        assert result.description == "Full desc."

    def test_get_raw_external_id(self):
        adapter = _adapter()
        assert adapter.get_raw_external_id({"id": "EB999"}) == "EB999"
        assert adapter.get_raw_external_id({}) is None


# ---------------------------------------------------------------------------
# _to_float() helper
# ---------------------------------------------------------------------------


class TestToFloat:
    def test_string_number(self):
        assert _to_float("59.43") == pytest.approx(59.43)

    def test_integer(self):
        assert _to_float(24) == 24.0

    def test_none(self):
        assert _to_float(None) is None

    def test_empty_string(self):
        assert _to_float("") is None

    def test_non_numeric(self):
        assert _to_float("abc") is None


# ---------------------------------------------------------------------------
# _parse_eb_price() — unit tests
# ---------------------------------------------------------------------------


class TestParseEbPrice:
    def test_free_event(self):
        mn, mx, cur = _parse_eb_price({"is_free": True})
        assert mn == 0.0 and mx == 0.0 and cur == "EUR"

    def test_single_ticket_class(self):
        raw = {"ticket_classes": [{"cost": {"value": 2500, "currency": "EUR"}}]}
        mn, mx, cur = _parse_eb_price(raw)
        assert mn == 25.0 and mx == 25.0 and cur == "EUR"

    def test_multiple_classes_gives_min_max(self):
        raw = {"ticket_classes": [
            {"cost": {"value": 1000, "currency": "EUR"}},
            {"cost": {"value": 5000, "currency": "EUR"}},
        ]}
        mn, mx, cur = _parse_eb_price(raw)
        assert mn == 10.0 and mx == 50.0

    def test_no_ticket_classes_returns_none(self):
        mn, mx, cur = _parse_eb_price({})
        assert mn is None and mx is None

    def test_zero_cost_is_free(self):
        raw = {"ticket_classes": [{"cost": {"value": 0, "currency": "EUR"}}]}
        mn, mx, cur = _parse_eb_price(raw)
        assert mn == 0.0 and mx == 0.0

    def test_currency_defaults_to_eur_when_absent(self):
        raw = {"ticket_classes": [{"cost": {"value": 500}}]}
        _, _, cur = _parse_eb_price(raw)
        assert cur == "EUR"


# ---------------------------------------------------------------------------
# fetch_raw() — integration-style (mocked HTTP)
# ---------------------------------------------------------------------------


class TestFetchRaw:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_api_key(self):
        adapter = _adapter(api_key="")
        with patch("app.ingestion.sources.eventbrite.settings") as mock_settings:
            mock_settings.EVENTBRITE_API_KEY = ""
            result = await adapter.fetch_raw()
        assert result == []

    @pytest.mark.asyncio
    async def test_single_page_fetch(self):
        events = [_minimal_raw()]
        response_data = {
            "events": events,
            "pagination": {"has_more_items": False, "page_count": 1},
        }
        mock_response = MagicMock()
        mock_response.json.return_value = response_data
        mock_response.raise_for_status = MagicMock()

        with patch("app.ingestion.sources.eventbrite._http_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            result = await _adapter().fetch_raw()

        assert len(result) == 1
        assert result[0]["id"] == "EB001"

    @pytest.mark.asyncio
    async def test_multi_page_fetch(self):
        page1_events = [{"id": "A", "name": {"text": "A"}}]
        page2_events = [{"id": "B", "name": {"text": "B"}}]
        responses = [
            MagicMock(json=MagicMock(return_value={
                "events": page1_events,
                "pagination": {"has_more_items": True, "page_count": 2},
            })),
            MagicMock(json=MagicMock(return_value={
                "events": page2_events,
                "pagination": {"has_more_items": False, "page_count": 2},
            })),
        ]
        for r in responses:
            r.raise_for_status = MagicMock()

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            resp = responses[call_count]
            call_count += 1
            return resp

        with patch("app.ingestion.sources.eventbrite._http_get", side_effect=side_effect):
            result = await _adapter().fetch_raw()

        assert len(result) == 2
        assert {r["id"] for r in result} == {"A", "B"}

    @pytest.mark.asyncio
    async def test_http_error_propagates(self):
        with patch("app.ingestion.sources.eventbrite._http_get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = httpx.RequestError("connection refused")
            with pytest.raises(httpx.RequestError):
                await _adapter().fetch_raw()

    @pytest.mark.asyncio
    async def test_stops_when_no_more_items(self):
        """Pagination stops when has_more_items is False even on page 1."""
        response_data = {
            "events": [_minimal_raw()],
            "pagination": {"has_more_items": False, "page_count": 1},
        }
        mock_response = MagicMock()
        mock_response.json.return_value = response_data

        with patch("app.ingestion.sources.eventbrite._http_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response
            result = await _adapter().fetch_raw()

        assert mock_get.call_count == 1
        assert len(result) == 1
