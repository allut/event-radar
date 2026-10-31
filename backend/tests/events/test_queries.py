"""Unit tests for app.events.queries and app.events.venue."""

from datetime import datetime, timezone


from app.events.queries import (
    collapse_series_duplicates,
    event_ended_filter,
    event_not_ended_filter,
    event_series_key,
    normalized_title,
)
from app.events.venue import (
    resolve_venue_address,
    resolve_venue_coords,
    resolve_venue_name,
)


class TestNormalizedTitle:
    def test_lowercases(self):
        assert normalized_title("Van GOGH") == "van gogh"

    def test_collapses_internal_whitespace(self):
        assert normalized_title("  Van   Gogh\tImmersive ") == "van gogh immersive"

    def test_idempotent(self):
        once = normalized_title("Jazz   Night")
        assert normalized_title(once) == once


class TestEventSeriesKey:
    def test_title_and_venue_normalized(self):
        # Both halves lowercase + collapse internal whitespace + strip.
        assert event_series_key("Van GOGH", "Vaba  Lava ") == ("van gogh", "vaba lava")

    def test_venue_whitespace_drift_shares_key(self):
        # Minor internal-whitespace drift between passes must still match.
        assert event_series_key("Van Gogh", "Vaba  Lava") == event_series_key(
            "Van Gogh", "Vaba Lava"
        )

    def test_none_venue_becomes_empty(self):
        assert event_series_key("Van Gogh", None) == ("van gogh", "")

    def test_same_series_across_days_shares_key(self):
        # Same title + venue, different starts_at (not an input) → identical key.
        assert event_series_key("Van Gogh", "Vaba Lava") == event_series_key(
            "van gogh", "Vaba Lava"
        )

    def test_different_venue_distinct_key(self):
        assert event_series_key("Jazz Night", "Von Krahli") != event_series_key(
            "Jazz Night", "Fotografiska"
        )


class TestEventNotEndedFilter:
    """Compiled-SQL checks — the predicate has no Python-side evaluation path,
    so correctness is verified against the literal-bound SQL it produces."""

    def test_compiles_to_sargable_coalesce_form(self):
        now = datetime(2026, 6, 25, tzinfo=timezone.utc)
        compiled = str(
            event_not_ended_filter(now).compile(
                compile_kwargs={"literal_binds": True}
            )
        )
        # Live if ends_at hasn't passed yet, falling back to starts_at when
        # ends_at is unset — written via coalesce() so it's sargable against
        # ix_events_live_until ON events (coalesce(ends_at, starts_at)),
        # unlike the equivalent OR form.
        assert "coalesce(events.ends_at, events.starts_at) >=" in compiled
        assert "2026-06-25" in compiled


class TestEventEndedFilter:
    """event_ended_filter is the complement of event_not_ended_filter, also
    written via coalesce() so it hits the same expression index. Unlike the
    old OR form, coalesce(ends_at, starts_at) is never NULL (starts_at is
    NOT NULL), so a plain ``<`` comparison has no three-valued-logic gap —
    no need to build the negation by hand."""

    def test_compiles_to_sargable_coalesce_form(self):
        now = datetime(2026, 6, 25, tzinfo=timezone.utc)
        compiled = str(
            event_ended_filter(now).compile(compile_kwargs={"literal_binds": True})
        )
        assert "NOT" not in compiled.upper()
        assert "coalesce(events.ends_at, events.starts_at) <" in compiled
        assert "2026-06-25" in compiled


class TestResolveVenue:
    """#177: joined Venue fields win over Event.venue_name/venue_address/
    lat/lng when venue_id is set; legacy free-typed columns are used
    otherwise (Event.venue_name/venue_address are left NULL at write time
    once venue_id is set — #176)."""

    def test_name_prefers_joined_venue_when_linked(self, make_event, make_venue):
        venue = make_venue(name="Telliskivi Creative City", name_en="Telliskivi Loomelinnak")
        event = make_event(venue_id=1, venue=venue, venue_name=None)
        assert resolve_venue_name(event, "et") == "Telliskivi Creative City"
        assert resolve_venue_name(event, "en") == "Telliskivi Loomelinnak"
        assert resolve_venue_name(event, "ru") == "Telliskivi Creative City"  # falls back to base

    def test_name_falls_back_to_event_column_when_unlinked(self, make_event):
        event = make_event(venue_id=None, venue=None, venue_name="Free-typed Venue")
        assert resolve_venue_name(event, "en") == "Free-typed Venue"

    def test_address_prefers_joined_venue_when_linked(self, make_event, make_venue):
        venue = make_venue(address="Telliskivi 60a")
        event = make_event(venue_id=1, venue=venue, venue_address=None)
        assert resolve_venue_address(event) == "Telliskivi 60a"

    def test_address_falls_back_to_event_column_when_unlinked(self, make_event):
        event = make_event(venue_id=None, venue=None, venue_address="Free-typed Street 1")
        assert resolve_venue_address(event) == "Free-typed Street 1"

    def test_coords_prefer_venue_geocode_when_linked_and_present(self, make_event, make_venue):
        venue = make_venue(lat=59.44, lng=24.74)
        event = make_event(venue_id=1, venue=venue, lat=None, lng=None)
        assert resolve_venue_coords(event) == (59.44, 24.74)

    def test_coords_fall_back_to_event_when_venue_ungeocoded(self, make_event, make_venue):
        venue = make_venue(lat=None, lng=None)
        event = make_event(venue_id=1, venue=venue, lat=58.0, lng=25.0)
        assert resolve_venue_coords(event) == (58.0, 25.0)

    def test_coords_fall_back_to_event_when_unlinked(self, make_event):
        event = make_event(venue_id=None, venue=None, lat=58.0, lng=25.0)
        assert resolve_venue_coords(event) == (58.0, 25.0)


class TestCollapseSeriesDuplicatesVenueLinked:
    """#176/#177: venue-linked events leave Event.venue_name NULL, so the
    series key must resolve through the linked Venue — reading the raw
    column collapses two genuinely different venue-linked events sharing a
    title into one series."""

    def test_same_title_different_linked_venues_stay_distinct(self, make_event, make_venue):
        venue_a = make_venue(venue_id=1, name="Telliskivi Creative City")
        venue_b = make_venue(venue_id=2, name="Fotografiska")
        event_a = make_event(
            event_id=1, title="Jazz Night", venue_id=1, venue=venue_a, venue_name=None
        )
        event_b = make_event(
            event_id=2, title="Jazz Night", venue_id=2, venue=venue_b, venue_name=None
        )
        collapsed, series_key_by_event_id = collapse_series_duplicates([event_a, event_b])
        assert len(collapsed) == 2
        assert series_key_by_event_id[1] != series_key_by_event_id[2]
