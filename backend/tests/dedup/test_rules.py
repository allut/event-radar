"""Tests for app.dedup.rules — rule-based deduplication pre-filter."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.constants import DEDUP_LOOKBACK_DAYS, TALLINN_TZ, TITLE_RATIO_THRESHOLD, TIME_WINDOW_HOURS
from app.dedup.rules import (
    cluster_events,
    is_candidate_pair,
    _venue_compatible,
)


def _event(
    eid: int,
    title: str,
    starts_at: datetime,
    venue_name: str | None = None,
    status: str = "draft",
) -> MagicMock:
    e = MagicMock()
    e.id = eid
    e.title_orig = title
    e.starts_at = starts_at
    e.venue_name = venue_name
    e.status = status
    return e


_BASE = datetime(2026, 7, 1, 20, 0, 0, tzinfo=TALLINN_TZ)


# ---------------------------------------------------------------------------
# _venue_compatible
# ---------------------------------------------------------------------------


class TestVenueCompatible:
    def test_both_none(self):
        assert _venue_compatible(None, None) is True

    def test_one_none(self):
        assert _venue_compatible("Von Krahli", None) is True
        assert _venue_compatible(None, "Von Krahli") is True

    def test_same_venue(self):
        assert _venue_compatible("Von Krahli", "Von Krahli") is True

    def test_similar_venue_fuzzy(self):
        # Slight variation (abbreviation / extra word) should still match
        assert _venue_compatible("Telliskivi Creative City", "Telliskivi") is True

    def test_different_venues(self):
        assert _venue_compatible("Von Krahli", "Fotografiska") is False

    def test_empty_string_venue_not_treated_as_none(self):
        # "" is not None — two events with different non-null venues must NOT be
        # auto-compatible just because a source wrote venue_name=""
        assert _venue_compatible("Von Krahli", "") is False
        assert _venue_compatible("", "Fotografiska") is False


# ---------------------------------------------------------------------------
# is_candidate_pair
# ---------------------------------------------------------------------------


class TestIsCandidatePair:
    def test_identical_titles_same_time(self):
        a = _event(1, "Jazz Night", _BASE)
        b = _event(2, "Jazz Night", _BASE)
        assert is_candidate_pair(a, b) is True

    def test_identical_titles_11h_apart(self):
        a = _event(1, "Jazz Night", _BASE)
        b = _event(2, "Jazz Night", _BASE + timedelta(hours=11))
        assert is_candidate_pair(a, b) is True

    def test_identical_titles_12h_exactly_boundary(self):
        # Exactly 12h — still within window (strictly less than is not required by plan)
        a = _event(1, "Jazz Night", _BASE)
        b = _event(2, "Jazz Night", _BASE + timedelta(hours=TIME_WINDOW_HOURS))
        assert is_candidate_pair(a, b) is True

    def test_identical_titles_13h_apart(self):
        a = _event(1, "Jazz Night", _BASE)
        b = _event(2, "Jazz Night", _BASE + timedelta(hours=13))
        assert is_candidate_pair(a, b) is False

    def test_title_below_threshold(self):
        a = _event(1, "Jazz Night at Von Krahli", _BASE)
        b = _event(2, "Completely Different Circus Show", _BASE)
        assert is_candidate_pair(a, b) is False

    def test_title_above_threshold_different_venues(self):
        a = _event(1, "Jazz Night", _BASE, venue_name="Von Krahli")
        b = _event(2, "Jazz Night", _BASE, venue_name="Fotografiska")
        assert is_candidate_pair(a, b) is False

    def test_title_match_venue_none(self):
        a = _event(1, "Jazz Night", _BASE, venue_name=None)
        b = _event(2, "Jazz Night", _BASE, venue_name="Von Krahli")
        assert is_candidate_pair(a, b) is True

    def test_case_insensitive_title(self):
        a = _event(1, "JAZZ NIGHT", _BASE)
        b = _event(2, "jazz night", _BASE)
        assert is_candidate_pair(a, b) is True

    def test_minor_title_variation(self):
        # Typical cross-source duplicate: "TMW Jazz Night" vs "TMW Jazz Night — Tickets"
        a = _event(1, "TMW Jazz Night", _BASE)
        b = _event(2, "TMW Jazz Night - Tallinn Music Week", _BASE)
        assert is_candidate_pair(a, b) is True


# ---------------------------------------------------------------------------
# cluster_events
# ---------------------------------------------------------------------------


class TestClusterEvents:
    def test_empty(self):
        assert cluster_events([]) == {}

    def test_single_event(self):
        assert cluster_events([_event(1, "Solo Show", _BASE)]) == {}

    def test_two_duplicates(self):
        a = _event(1, "Jazz Night", _BASE)
        b = _event(2, "Jazz Night", _BASE)
        result = cluster_events([a, b])
        assert result == {1: 1, 2: 1}

    def test_two_non_duplicates(self):
        a = _event(1, "Jazz Night", _BASE)
        b = _event(2, "Totally Different Show", _BASE)
        assert cluster_events([a, b]) == {}

    def test_three_events_two_duplicates(self):
        a = _event(1, "Jazz Night", _BASE)
        b = _event(2, "Jazz Night", _BASE)
        c = _event(3, "Circus Act", _BASE)
        result = cluster_events([a, b, c])
        assert result == {1: 1, 2: 1}
        assert 3 not in result

    def test_three_way_duplicate(self):
        a = _event(1, "Jazz Night", _BASE)
        b = _event(2, "Jazz Night", _BASE)
        c = _event(3, "Jazz Night", _BASE)
        result = cluster_events([a, b, c])
        assert result[1] == 1
        assert result[2] == 1
        assert result[3] == 1

    def test_group_id_is_min_event_id(self):
        # IDs not in sorted order — group root must still be min
        a = _event(10, "Jazz Night", _BASE)
        b = _event(5, "Jazz Night", _BASE)
        c = _event(7, "Jazz Night", _BASE)
        result = cluster_events([a, b, c])
        assert all(gid == 5 for gid in result.values())

    def test_two_separate_duplicate_groups(self):
        a = _event(1, "Jazz Night", _BASE)
        b = _event(2, "Jazz Night", _BASE)
        c = _event(3, "Salsa Dancing", _BASE + timedelta(days=1))
        d = _event(4, "Salsa Dancing", _BASE + timedelta(days=1))
        result = cluster_events([a, b, c, d])
        assert result[1] == 1
        assert result[2] == 1
        assert result[3] == 3
        assert result[4] == 3

    def test_time_gap_prevents_grouping(self):
        a = _event(1, "Jazz Night", _BASE)
        b = _event(2, "Jazz Night", _BASE + timedelta(hours=25))
        assert cluster_events([a, b]) == {}

    def test_venue_mismatch_prevents_grouping(self):
        a = _event(1, "Jazz Night", _BASE, venue_name="Von Krahli")
        b = _event(2, "Jazz Night", _BASE, venue_name="Fotografiska")
        assert cluster_events([a, b]) == {}


# ---------------------------------------------------------------------------
# Lookback constant sanity
# ---------------------------------------------------------------------------


class TestLookbackConstant:
    def test_lookback_days_reasonable(self):
        # Must be positive and not excessively large (>365 defeats the purpose)
        assert 7 <= DEDUP_LOOKBACK_DAYS <= 365
