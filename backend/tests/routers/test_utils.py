"""Unit tests for app.routers.utils helpers."""
from datetime import datetime, timezone

from app.routers.utils import (
    event_not_ended_filter,
    event_series_key,
    mask_email,
    normalized_title,
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

    def test_compiles_to_ends_at_or_starts_at_fallback(self):
        now = datetime(2026, 6, 25, tzinfo=timezone.utc)
        compiled = str(
            event_not_ended_filter(now).compile(
                compile_kwargs={"literal_binds": True}
            )
        )
        # Live if ends_at hasn't passed yet...
        assert "events.ends_at >=" in compiled
        # ...or, when ends_at is unset, live if starts_at hasn't passed yet.
        assert "events.ends_at IS NULL" in compiled
        assert "events.starts_at >=" in compiled
        assert "2026-06-25" in compiled


class TestMaskEmail:
    def test_keeps_visible_prefix_and_domain(self):
        assert mask_email("aleksei.lutkov@gmail.com") == "al***@gmail.com"

    def test_short_local_part(self):
        assert mask_email("a@b.com") == "a***@b.com"

    def test_no_at_sign_returns_placeholder(self):
        assert mask_email("not-an-email") == "***"

    def test_never_includes_full_local_part(self):
        masked = mask_email("verylongusername@example.com")
        assert "verylongusername" not in masked
        assert masked.endswith("@example.com")
