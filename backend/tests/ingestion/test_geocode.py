"""Tests for Nominatim geocoding (geocode_address, geocode_pending)."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.ingestion.geocode import geocode_address, geocode_pending


def _mock_response(json_data):
    resp = MagicMock(spec=httpx.Response)
    resp.json.return_value = json_data
    return resp


class TestGeocodeAddress:
    @pytest.mark.asyncio
    async def test_returns_lat_lng_from_first_result(self):
        with patch("app.ingestion.geocode.http_get") as mock_get:
            mock_get.return_value = _mock_response([{"lat": "59.437", "lon": "24.745"}])
            result = await geocode_address(MagicMock(), "Some Address, Tallinn")
        assert result == (59.437, 24.745)

    @pytest.mark.asyncio
    async def test_empty_results_returns_none(self):
        with patch("app.ingestion.geocode.http_get") as mock_get:
            mock_get.return_value = _mock_response([])
            result = await geocode_address(MagicMock(), "Nowhere")
        assert result is None

    @pytest.mark.asyncio
    async def test_non_json_response_returns_none(self):
        resp = MagicMock(spec=httpx.Response)
        resp.json.side_effect = ValueError("Expecting value: line 1 column 1")
        with patch("app.ingestion.geocode.http_get") as mock_get:
            mock_get.return_value = resp
            result = await geocode_address(MagicMock(), "Some Address, Tallinn")
        assert result is None


class TestGeocodePending:
    @pytest.mark.asyncio
    async def test_no_pending_events_returns_zero_summary(self, mock_db):
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
        summary = await geocode_pending(mock_db)
        assert summary == {"pending": 0, "geocoded": 0, "failed": 0}

    @pytest.mark.asyncio
    async def test_geocodes_events_and_reuses_cached_address(self, mock_db, make_event):
        event1 = make_event(event_id=1)
        event1.venue_address = "Address A"
        event1.lat = None
        event1.lng = None

        event2 = make_event(event_id=2)
        event2.venue_address = "Address B"
        event2.lat = None
        event2.lng = None

        mock_db.scalars.return_value = MagicMock(
            all=MagicMock(return_value=[event1, event2])
        )
        # "Address B" was already geocoded on a different event -> seeds the cache
        mock_db.execute.return_value = MagicMock(
            all=MagicMock(return_value=[("Address B", 59.1, 24.1)])
        )

        with (
            patch(
                "app.ingestion.geocode.geocode_address",
                new=AsyncMock(return_value=(59.5, 24.5)),
            ) as mock_geo,
            patch("app.ingestion.geocode.asyncio.sleep", new=AsyncMock()),
        ):
            summary = await geocode_pending(mock_db)

        assert summary == {"pending": 2, "geocoded": 2, "failed": 0}
        assert (event1.lat, event1.lng) == (59.5, 24.5)
        assert (event2.lat, event2.lng) == (59.1, 24.1)
        mock_geo.assert_called_once()  # only "Address A" needed a Nominatim call

    @pytest.mark.asyncio
    async def test_failed_geocode_counts_as_failed_and_leaves_coords_unset(
        self, mock_db, make_event
    ):
        event1 = make_event(event_id=1)
        event1.venue_address = "Unknown Place"
        event1.lat = None
        event1.lng = None

        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[event1]))
        mock_db.execute.return_value = MagicMock(all=MagicMock(return_value=[]))

        with (
            patch(
                "app.ingestion.geocode.geocode_address", new=AsyncMock(return_value=None)
            ),
            patch("app.ingestion.geocode.asyncio.sleep", new=AsyncMock()),
        ):
            summary = await geocode_pending(mock_db)

        assert summary == {"pending": 1, "geocoded": 0, "failed": 1}
        assert event1.lat is None
        assert event1.lng is None
