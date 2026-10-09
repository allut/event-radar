"""Dedup reads venue data through the venue resolvers, not the Event columns
(venue-linked events leave venue_name/venue_address/lat/lng NULL)."""

from app.dedup.llm_tiebreaker import _build_prompt
from app.dedup.rules import _event_quality_rank
from app.events.venue import resolve_venue_name_from_row
from tests.conftest import build_event, build_venue


def _linked_event(event_id: int = 1):
    venue = build_venue(name="Kultuurikatel", name_en="Cultural Boiler")
    return build_event(
        event_id=event_id,
        venue_name=None,
        venue_address=None,
        lat=None,
        lng=None,
        venue_id=venue.id,
        venue=venue,
    )


def test_prompt_uses_linked_venue_name():
    prompt = _build_prompt(_linked_event(1), build_event(event_id=2))
    assert "Cultural Boiler" in prompt


def test_quality_rank_counts_linked_venue_address_and_coords():
    rank = _event_quality_rank(_linked_event(), {1: 0})
    assert rank[1] is True
    assert rank[2] is True


def test_quality_rank_unlinked_without_address_is_incomplete():
    event = build_event(venue_address=None, lat=None, lng=None)
    rank = _event_quality_rank(event, {event.id: 0})
    assert rank[1] is False
    assert rank[2] is False


class TestResolveVenueNameFromRow:
    def test_no_venue_columns_falls_back_to_bare(self):
        assert resolve_venue_name_from_row("Bare", None, None) == "Bare"

    def test_prefers_english_name(self):
        assert resolve_venue_name_from_row(None, "Base", "English") == "English"

    def test_falls_back_to_base_name(self):
        assert resolve_venue_name_from_row(None, "Base", None) == "Base"
