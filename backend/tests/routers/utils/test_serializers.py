"""Unit tests for app.routers.utils.serializers."""

import pytest

from app.routers.utils.serializers import (
    compute_preferred_taxonomy,
    load_user_reported_events,
    resolve_locale_param,
    serialize_event,
)


class TestResolveLocaleParam:
    def test_valid_locale_wins_over_fallback(self):
        assert resolve_locale_param("et", "en") == "et"

    def test_none_falls_back(self):
        assert resolve_locale_param(None, "en") == "en"

    def test_invalid_falls_back(self):
        assert resolve_locale_param("xx", "en") == "en"


class TestComputePreferredTaxonomy:
    def test_no_personas_returns_empty(self):
        assert compute_preferred_taxonomy([]) == ([], [])

    def test_union_across_personas_above_threshold(self):
        weights = [
            (1.0, {"categories": {"music": 0.9, "cinema": 0.2}, "vibes": {"trendy": 0.8}}),
            (0.4, {"categories": {"theater": 0.6}, "vibes": {"trendy": 0.1, "indie": 0.7}}),
        ]
        categories, vibes = compute_preferred_taxonomy(weights)
        assert categories == ["music", "theater"]
        assert vibes == ["indie", "trendy"]

    def test_missing_keys_treated_as_empty(self):
        assert compute_preferred_taxonomy([(1.0, {})]) == ([], [])


class TestLoadUserReportedEvents:
    @pytest.mark.asyncio
    async def test_empty_event_ids_short_circuits(self, mock_db):
        result = await load_user_reported_events(mock_db, user_id=1, event_ids=[])
        assert result == set()
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_open_report_event_ids(self, mock_db):
        from unittest.mock import MagicMock

        row = MagicMock()
        row.event_id = 10
        exec_result = MagicMock()
        exec_result.all.return_value = [row]
        mock_db.execute.return_value = exec_result

        result = await load_user_reported_events(mock_db, user_id=1, event_ids=[10, 20])
        assert result == {10}


class TestSerializeEventVenueResolution:
    def test_serializes_joined_venue_fields_when_linked(self, make_event, make_venue):
        venue = make_venue(
            name="Telliskivi Creative City",
            address="Telliskivi 60a",
            lat=59.44,
            lng=24.74,
        )
        event = make_event(
            venue_id=1, venue=venue, venue_name=None, venue_address=None, lat=None, lng=None
        )
        result = serialize_event(event)
        assert result["venue_name"] == "Telliskivi Creative City"
        assert result["venue_address"] == "Telliskivi 60a"
        assert result["lat"] == 59.44
        assert result["lng"] == 24.74

    def test_serializes_legacy_columns_when_unlinked(self, make_event):
        event = make_event(
            venue_id=None,
            venue=None,
            venue_name="Free-typed Venue",
            venue_address="Free-typed Street 1",
        )
        result = serialize_event(event)
        assert result["venue_name"] == "Free-typed Venue"
        assert result["venue_address"] == "Free-typed Street 1"


class TestSerializeEventReportedField:
    def test_defaults_to_false(self, make_event):
        result = serialize_event(make_event(10))
        assert result["reported"] is False

    def test_true_when_event_id_in_set(self, make_event):
        result = serialize_event(make_event(10), reported_event_ids={10})
        assert result["reported"] is True

    def test_false_when_event_id_not_in_set(self, make_event):
        result = serialize_event(make_event(10), reported_event_ids={99})
        assert result["reported"] is False
