"""Tests for email/digest.py — HTML builder and date formatter."""
from datetime import date, datetime, timezone
from unittest.mock import MagicMock

from app.email.digest import (
    _format_feed_date,
    _format_event_time,
    build_digest_html,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(
    id: int = 1,
    title: str = "Test Event",
    starts_at: datetime | None = None,
    venue_name: str | None = "Test Venue",
    price_min: float | None = None,
    why_go: list[str] | None = None,
) -> MagicMock:
    if starts_at is None:
        starts_at = datetime(2026, 5, 20, 19, 0, tzinfo=timezone.utc)
    event = MagicMock()
    event.id = id
    event.title_orig = title
    event.starts_at = starts_at
    event.venue_name = venue_name
    event.price_min = price_min
    if why_go is not None:
        cl = MagicMock()
        cl.why_go_bullets = why_go
        event.classification = cl
    else:
        event.classification = None
    return event


# ---------------------------------------------------------------------------
# _format_feed_date
# ---------------------------------------------------------------------------

class TestFormatFeedDate:
    def test_en_format(self):
        d = date(2026, 5, 20)  # Wednesday
        result = _format_feed_date(d, "en")
        assert result == "Wednesday, May 20"

    def test_et_format(self):
        d = date(2026, 5, 20)  # Wednesday → kolmapäev
        result = _format_feed_date(d, "et")
        assert result == "kolmapäev, 20. mai"

    def test_ru_format(self):
        d = date(2026, 5, 20)  # Wednesday → среда
        result = _format_feed_date(d, "ru")
        assert result == "среда, 20 мая"

    def test_unknown_locale_falls_back_to_en(self):
        d = date(2026, 5, 20)
        result = _format_feed_date(d, "fr")
        assert result == "Wednesday, May 20"

    def test_saturday(self):
        d = date(2026, 5, 16)  # Saturday
        assert "Saturday" in _format_feed_date(d, "en")

    def test_sunday(self):
        d = date(2026, 5, 17)  # Sunday
        assert "Sunday" in _format_feed_date(d, "en")


# ---------------------------------------------------------------------------
# _format_event_time
# ---------------------------------------------------------------------------

class TestFormatEventTime:
    def test_includes_hhmm(self):
        starts_at = datetime(2026, 5, 20, 17, 0, tzinfo=timezone.utc)  # 20:00 EET
        result = _format_event_time(starts_at, "en")
        assert "20:00" in result

    def test_includes_day_name_en(self):
        starts_at = datetime(2026, 5, 20, 0, 0, tzinfo=timezone.utc)  # May 20 UTC = May 20 EET
        result = _format_event_time(starts_at, "en")
        assert "Wednesday" in result

    def test_et_locale(self):
        starts_at = datetime(2026, 5, 20, 17, 0, tzinfo=timezone.utc)
        result = _format_event_time(starts_at, "et")
        assert "kolmapäev" in result


# ---------------------------------------------------------------------------
# build_digest_html
# ---------------------------------------------------------------------------

class TestBuildDigestHtml:
    def test_returns_html_string(self):
        events = [_make_event()]
        html = build_digest_html(events, date(2026, 5, 20), "en", "https://eventradar.ee")
        assert html.startswith("<!DOCTYPE html>")

    def test_contains_event_title(self):
        events = [_make_event(title="Jazz Night in Tallinn")]
        html = build_digest_html(events, date(2026, 5, 20), "en", "https://eventradar.ee")
        assert "Jazz Night in Tallinn" in html

    def test_contains_why_go_bullets(self):
        events = [_make_event(why_go=["Great music", "Central venue", "Affordable price"])]
        html = build_digest_html(events, date(2026, 5, 20), "en", "https://eventradar.ee")
        assert "Great music" in html
        assert "Central venue" in html

    def test_at_most_3_bullets(self):
        bullets = ["A", "B", "C", "D", "E"]
        events = [_make_event(why_go=bullets)]
        html = build_digest_html(events, date(2026, 5, 20), "en", "https://eventradar.ee")
        # Only first 3 should appear
        assert "<li>A</li>" in html
        assert "<li>D</li>" not in html

    def test_free_event_en(self):
        events = [_make_event(price_min=0.0)]
        html = build_digest_html(events, date(2026, 5, 20), "en", "https://eventradar.ee")
        assert "Free" in html

    def test_free_event_et(self):
        events = [_make_event(price_min=0.0)]
        html = build_digest_html(events, date(2026, 5, 20), "et", "https://eventradar.ee")
        assert "Tasuta" in html

    def test_free_event_ru(self):
        events = [_make_event(price_min=0.0)]
        html = build_digest_html(events, date(2026, 5, 20), "ru", "https://eventradar.ee")
        assert "Бесплатно" in html

    def test_paid_event_shows_price(self):
        events = [_make_event(price_min=12.0)]
        html = build_digest_html(events, date(2026, 5, 20), "en", "https://eventradar.ee")
        assert "12" in html

    def test_et_subject_label(self):
        html = build_digest_html([], date(2026, 5, 20), "et", "https://eventradar.ee")
        assert "Sinu päeva viis" in html

    def test_ru_subject_label(self):
        html = build_digest_html([], date(2026, 5, 20), "ru", "https://eventradar.ee")
        assert "Пятёрка" in html

    def test_no_events_shows_placeholder(self):
        html = build_digest_html([], date(2026, 5, 20), "en", "https://eventradar.ee")
        assert "No events today" in html

    def test_frontend_url_used_in_event_link(self):
        events = [_make_event(id=42)]
        html = build_digest_html(events, date(2026, 5, 20), "en", "https://eventradar.ee")
        assert "https://eventradar.ee/events/42" in html

    def test_unsubscribe_link_present(self):
        html = build_digest_html([], date(2026, 5, 20), "en", "https://eventradar.ee")
        assert "https://eventradar.ee/settings" in html

    def test_multiple_events_all_rendered(self):
        events = [_make_event(i, title=f"Event {i}") for i in range(1, 6)]
        html = build_digest_html(events, date(2026, 5, 20), "en", "https://eventradar.ee")
        for i in range(1, 6):
            assert f"Event {i}" in html

    def test_venue_in_meta(self):
        events = [_make_event(venue_name="Kultuurikatel")]
        html = build_digest_html(events, date(2026, 5, 20), "en", "https://eventradar.ee")
        assert "Kultuurikatel" in html
