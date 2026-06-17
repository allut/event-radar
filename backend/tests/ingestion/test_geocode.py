"""Tests for Nominatim geocoding (geocode_address, geocode_pending, normalize_address_for_geocoding)."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.ingestion.geocode import geocode_address, geocode_pending, normalize_address_for_geocoding


def _mock_response(json_data):
    resp = MagicMock(spec=httpx.Response)
    resp.json.return_value = json_data
    return resp


class TestNormalizeAddressForGeocoding:
    def test_tanav_stripped(self):
        result = normalize_address_for_geocoding("Telliskivi tänav 60a, 10412 Tallinn")
        assert "tänav" not in result
        assert "tn" not in result
        assert "Telliskivi 60a" in result

    def test_maantee_stripped(self):
        result = normalize_address_for_geocoding("Narva maantee 63, Tallinn")
        assert "maantee" not in result
        assert "mnt" not in result
        assert "Narva 63" in result

    def test_puiestee_stripped(self):
        result = normalize_address_for_geocoding("Estonia puiestee 4, Tallinn")
        assert "puiestee" not in result
        assert "pst" not in result
        assert "Estonia 4" in result

    def test_tee_preserved_not_stripped(self):
        """'tee' is an inseparable part of many Tallinn street names (Mustamäe tee)
        — stripping it would collapse to a district-centroid match, so it stays."""
        result = normalize_address_for_geocoding("Mustamäe tee 25, 10621 Tallinn")
        assert "Mustamäe tee 25" in result

    def test_leading_initial_stripped(self):
        result = normalize_address_for_geocoding("A. Weizenbergi 26, 10127 Tallinn")
        assert "Weizenbergi 26" in result
        assert "A." not in result

    def test_leading_initial_no_space_stripped(self):
        result = normalize_address_for_geocoding("L.Koidula 12a, Tallinn")
        assert "Koidula 12a" in result
        assert "L." not in result

    def test_unit_suffix_stripped_slash_9(self):
        result = normalize_address_for_geocoding("Telliskivi tänav 60a/9, 10412 Tallinn")
        assert "/9" not in result
        assert "60a" in result

    def test_unit_suffix_stripped_space_slash_space(self):
        result = normalize_address_for_geocoding("Telliskivi tänav 60a / 9, Tallinn")
        assert "/ 9" not in result

    def test_unit_suffix_stripped_slash_space(self):
        result = normalize_address_for_geocoding("Telliskivi tänav 60a/ 9, Tallinn")
        assert "/ 9" not in result

    def test_all_three_unit_variants_normalize_to_same_string(self):
        base = "Telliskivi tänav 60a, 10412 Tallinn, Harju maakond"
        v1 = normalize_address_for_geocoding("Telliskivi tänav 60a/9, 10412 Tallinn, Harju maakond")
        v2 = normalize_address_for_geocoding("Telliskivi tänav 60a/ 9, 10412 Tallinn, Harju maakond")
        v3 = normalize_address_for_geocoding("Telliskivi tänav 60a / 9, 10412 Tallinn, Harju maakond")
        expected = normalize_address_for_geocoding(base)
        assert v1 == expected
        assert v2 == expected
        assert v3 == expected

    def test_county_harju_maakond_stripped(self):
        result = normalize_address_for_geocoding("Narva mnt 63, Tallinn, Harju maakond")
        assert "maakond" not in result
        assert "Harju" not in result

    def test_county_harjumaa_stripped(self):
        result = normalize_address_for_geocoding("Telliskivi 60a, Tallinn, Harjumaa")
        assert "Harjumaa" not in result

    def test_floor_stripped(self):
        result = normalize_address_for_geocoding("Pärnu mnt 10, Tallinn, II korrus")
        assert "korrus" not in result

    def test_estonia_suffix_appended(self):
        result = normalize_address_for_geocoding("Narva mnt 63, Tallinn")
        assert result.endswith(", Estonia")

    def test_estonia_suffix_not_duplicated(self):
        result = normalize_address_for_geocoding("Narva mnt 63, Tallinn, Estonia")
        assert result.count("Estonia") == 1

    def test_case_insensitive_street_type(self):
        result = normalize_address_for_geocoding("Narva Maantee 63, Tallinn")
        assert "Maantee" not in result
        assert "Narva 63" in result


class TestGeocodeAddress:
    @pytest.mark.asyncio
    async def test_returns_lat_lng_from_first_result(self):
        with patch("app.ingestion.geocode.http_get") as mock_get:
            mock_get.return_value = _mock_response([{"lat": "59.437", "lon": "24.745"}])
            result = await geocode_address(MagicMock(), "Some Address, Tallinn")
        assert result == (59.437, 24.745)

    @pytest.mark.asyncio
    async def test_empty_results_returns_none_and_logs_warning(self, caplog):
        with patch("app.ingestion.geocode.http_get") as mock_get:
            mock_get.return_value = _mock_response([])
            with caplog.at_level(logging.WARNING, logger="app.ingestion.geocode"):
                result = await geocode_address(MagicMock(), "Nowhere tn 1, Estonia", original="Nowhere tänav 1")
        assert result is None
        assert "no match" in caplog.text

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
    async def test_format_variants_of_one_venue_cost_single_nominatim_call(self, mock_db, make_event):
        """Three address variants that normalize identically → one geocode call."""
        event1 = make_event(event_id=1)
        event1.venue_address = "Telliskivi tänav 60a/9, 10412 Tallinn, Harju maakond"
        event1.lat = None
        event1.lng = None

        event2 = make_event(event_id=2)
        event2.venue_address = "Telliskivi tänav 60a/ 9, 10412 Tallinn, Harju maakond"
        event2.lat = None
        event2.lng = None

        event3 = make_event(event_id=3)
        event3.venue_address = "Telliskivi tänav 60a / 9, 10412 Tallinn, Harju maakond"
        event3.lat = None
        event3.lng = None

        mock_db.scalars.return_value = MagicMock(
            all=MagicMock(return_value=[event1, event2, event3])
        )
        mock_db.execute.return_value = MagicMock(all=MagicMock(return_value=[]))

        with (
            patch(
                "app.ingestion.geocode.geocode_address",
                new=AsyncMock(return_value=(59.44, 24.72)),
            ) as mock_geo,
            patch("app.ingestion.geocode.asyncio.sleep", new=AsyncMock()),
        ):
            summary = await geocode_pending(mock_db)

        assert summary == {"pending": 3, "geocoded": 3, "failed": 0}
        mock_geo.assert_called_once()  # normalized key collision → 1 call for 3 events

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
