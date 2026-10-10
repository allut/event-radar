"""Tests for email/digest.py — HTML builder and date formatter."""
import re
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.email.digest import (
    _format_feed_date,
    _format_event_time,
    build_digest_html,
    send_daily_digests,
)
from app.email.styles import _THEME_CLASS_RULES
from app.i18n import TRANSLATIONS, t, ti


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

class TestDigestRunScopedCaches:
    def test_block_cache_renders_each_event_locale_once(self, make_event):
        event = make_event()
        cache: dict = {}
        with patch(
            "app.email.digest._build_event_block", return_value="<card/>"
        ) as build:
            for _ in range(3):
                build_digest_html(
                    [event], date(2026, 5, 20), "en", "https://eventradar.ee",
                    block_cache=cache,
                )
            build_digest_html(
                [event], date(2026, 5, 20), "et", "https://eventradar.ee",
                block_cache=cache,
            )
        assert build.call_count == 2  # one per (event, locale)
        assert set(cache) == {(event.id, "en"), (event.id, "et")}

    @pytest.mark.asyncio
    async def test_load_digest_data_skips_events_already_cached(
        self, mock_db, make_event
    ):
        from app.email.digest import _load_digest_data

        cached = make_event(event_id=1)
        fresh = make_event(event_id=2)
        feeds = MagicMock()
        feeds.all.return_value = [
            MagicMock(user_id=10, event_ids=[1, 2]),
        ]
        fresh_rows = MagicMock()
        fresh_rows.all.return_value = [fresh]
        mock_db.scalars.side_effect = [feeds, fresh_rows]
        cache = {1: cached}

        _, event_map = await _load_digest_data(
            mock_db, date(2026, 5, 20), [10], cache
        )

        assert event_map == {1: cached, 2: fresh}
        compiled = str(
            mock_db.scalars.call_args_list[1].args[0].compile(
                compile_kwargs={"literal_binds": True}
            )
        )
        assert "events.id IN (2)" in compiled  # only the missing id is queried


class TestBuildDigestHtml:
    def test_returns_html_string(self, make_event):
        events = [make_event()]
        html = build_digest_html(events, date(2026, 5, 20), "en", "https://eventradar.ee")
        assert html.startswith("<!DOCTYPE html>")

    def test_contains_event_title(self, make_event):
        events = [make_event(title="Jazz Night in Tallinn")]
        html = build_digest_html(events, date(2026, 5, 20), "en", "https://eventradar.ee")
        assert "Jazz Night in Tallinn" in html

    def test_contains_why_go_bullets(self, make_event):
        events = [make_event(why_go=["Great music", "Central venue", "Affordable price"])]
        html = build_digest_html(events, date(2026, 5, 20), "en", "https://eventradar.ee")
        assert "Great music" in html
        assert "Central venue" in html

    def test_never_shows_listed_by_credit(self, make_event):
        """The "Listed by X" credit is public-event-page-only (#419) — the
        digest must never render it, even for a claimed event with an
        organizer display name set."""
        event = make_event(title="Jazz Night in Tallinn")
        event.claim_status = "claimed"
        event.listed_by = "Tallinn Jazz Club"
        html = build_digest_html([event], date(2026, 5, 20), "en", "https://eventradar.ee")
        assert "Tallinn Jazz Club" not in html
        assert "Listed by" not in html

    def test_at_most_3_bullets(self, make_event):
        bullets = ["A", "B", "C", "D", "E"]
        events = [make_event(why_go=bullets)]
        html = build_digest_html(events, date(2026, 5, 20), "en", "https://eventradar.ee")
        # Only first 3 should appear
        assert "&#9670;</span>A</p>" in html
        assert "&#9670;</span>D</p>" not in html

    def test_free_event_en(self, make_event):
        events = [make_event(price_min=0.0)]
        html = build_digest_html(events, date(2026, 5, 20), "en", "https://eventradar.ee")
        assert "Free" in html

    def test_free_event_et(self, make_event):
        events = [make_event(price_min=0.0)]
        html = build_digest_html(events, date(2026, 5, 20), "et", "https://eventradar.ee")
        assert "Tasuta" in html

    def test_free_event_ru(self, make_event):
        events = [make_event(price_min=0.0)]
        html = build_digest_html(events, date(2026, 5, 20), "ru", "https://eventradar.ee")
        assert "Бесплатно" in html

    def test_paid_event_shows_price(self, make_event):
        events = [make_event(price_min=12.0)]
        html = build_digest_html(events, date(2026, 5, 20), "en", "https://eventradar.ee")
        assert "12" in html

    def test_et_subject_label(self):
        html = build_digest_html([], date(2026, 5, 20), "et", "https://eventradar.ee")
        assert "Sinu päeva 5" in html

    def test_ru_subject_label(self):
        html = build_digest_html([], date(2026, 5, 20), "ru", "https://eventradar.ee")
        assert "Пятёрка" in html

    def test_no_events_shows_placeholder(self):
        html = build_digest_html([], date(2026, 5, 20), "en", "https://eventradar.ee")
        assert "No events today" in html

    def test_no_events_placeholder_is_theme_styled(self):
        html = build_digest_html([], date(2026, 5, 20), "en", "https://eventradar.ee")
        assert re.search(r'class="e-body-text"[^>]*>No events today', html)

    def test_frontend_url_used_in_event_link(self, make_event):
        events = [make_event(event_id=42)]
        html = build_digest_html(events, date(2026, 5, 20), "en", "https://eventradar.ee")
        assert "https://eventradar.ee/en/events/42" in html

    @pytest.mark.parametrize(
        ("locale", "prefix"), [("et", ""), ("en", "/en"), ("ru", "/ru")]
    )
    def test_links_carry_locale_prefix(self, make_event, locale, prefix):
        # #499 — every frontend link opens the recipient's locale; ET is bare.
        events = [make_event(event_id=42)]
        html = build_digest_html(events, date(2026, 5, 20), locale, "https://eventradar.ee")
        assert f'href="https://eventradar.ee{prefix}/events/42"' in html
        assert f'href="https://eventradar.ee{prefix or "/"}"' in html
        assert f'href="https://eventradar.ee{prefix}/settings"' in html

    def test_light_base_client_adaptive(self):
        html = build_digest_html([], date(2026, 5, 20), "en", "https://eventradar.ee")
        assert "#fdfcfa" in html
        assert 'content="light dark"' in html

    def test_unsubscribe_link_present(self):
        html = build_digest_html([], date(2026, 5, 20), "en", "https://eventradar.ee")
        assert "https://eventradar.ee/en/settings" in html

    def test_explicit_unsubscribe_url_overrides_default(self):
        html = build_digest_html(
            [], date(2026, 5, 20), "en", "https://eventradar.ee",
            "https://eventradar.ee/unsubscribe?token=abc123",
        )
        assert "https://eventradar.ee/unsubscribe?token=abc123" in html
        assert "https://eventradar.ee/en/settings" not in html

    def test_multiple_events_all_rendered(self, make_event):
        events = [make_event(event_id=i, title=f"Event {i}") for i in range(1, 6)]
        html = build_digest_html(events, date(2026, 5, 20), "en", "https://eventradar.ee")
        for i in range(1, 6):
            assert f"Event {i}" in html

    def test_venue_in_meta(self, make_event):
        events = [make_event(venue_name="Kultuurikatel")]
        html = build_digest_html(events, date(2026, 5, 20), "en", "https://eventradar.ee")
        assert "Kultuurikatel" in html

    def test_venue_prefers_joined_venue_when_linked(self, make_event, make_venue):
        """#177: the digest must prefer the joined Venue over Event's own
        (write-time-NULL) venue_name once venue_id is set."""
        venue = make_venue(name="Telliskivi Creative City", name_en="Telliskivi Loomelinnak")
        events = [make_event(venue_id=1, venue=venue, venue_name=None)]
        html = build_digest_html(events, date(2026, 5, 20), "en", "https://eventradar.ee")
        assert "Telliskivi Loomelinnak" in html

    def test_no_events_et_locale(self):
        html = build_digest_html([], date(2026, 5, 20), "et", "https://eventradar.ee")
        assert "Täna pole üritusi" in html

    def test_no_events_ru_locale(self):
        html = build_digest_html([], date(2026, 5, 20), "ru", "https://eventradar.ee")
        assert "Сегодня нет событий" in html

    def test_why_go_localized_used_when_present(self, make_event):
        events = [make_event(
            why_go=["EN fallback"],
            why_go_localized={"et": ["ET bullet 1", "ET bullet 2", "ET bullet 3"], "en": ["EN bullet"]},
        )]
        html = build_digest_html(events, date(2026, 5, 20), "et", "https://eventradar.ee")
        assert "ET bullet 1" in html
        assert "EN fallback" not in html

    def test_why_go_localized_falls_back_to_en(self, make_event):
        events = [make_event(
            why_go=["raw fallback"],
            why_go_localized={"en": ["EN bullet 1", "EN bullet 2", "EN bullet 3"]},
        )]
        html = build_digest_html(events, date(2026, 5, 20), "et", "https://eventradar.ee")
        assert "EN bullet 1" in html
        assert "raw fallback" not in html

    def test_why_go_localized_falls_back_to_bullets(self, make_event):
        events = [make_event(
            why_go=["bullets fallback"],
            why_go_localized={},
        )]
        html = build_digest_html(events, date(2026, 5, 20), "et", "https://eventradar.ee")
        assert "bullets fallback" in html

    def test_event_image_rendered_when_present(self, make_event):
        events = [make_event(image_url="https://example.com/photo.jpg")]
        html = build_digest_html(events, date(2026, 5, 20), "en", "https://eventradar.ee")
        assert '<img src="https://example.com/photo.jpg"' in html

    def test_branded_band_rendered_when_no_image(self, make_event):
        events = [make_event(image_url=None)]
        html = build_digest_html(events, date(2026, 5, 20), "en", "https://eventradar.ee")
        assert "&#9670;" in html
        assert "MUSIC" in html  # default classification category from make_event
        assert html.count("<img") == 1  # only the header brand mark, no event image

    def test_header_carries_brand_mark_on_given_base(self, make_event):
        html = build_digest_html([make_event()], date(2026, 5, 20), "en", "https://eventradar.ee")
        assert '<img src="https://eventradar.ee/email-mark.png"' in html

    def test_feed_button_links_to_frontend_root(self, make_event):
        html = build_digest_html([make_event()], date(2026, 5, 20), "en", "https://eventradar.ee")
        assert 'href="https://eventradar.ee/en"' in html
        assert "Open your feed" in html

    def test_tickets_link_present_when_event_url_set(self, make_event):
        events = [make_event()]
        html = build_digest_html(events, date(2026, 5, 20), "en", "https://eventradar.ee")
        assert 'href="https://example.com"' in html
        assert "Get tickets" in html

    def test_price_pill_rendered_for_paid_event(self, make_event):
        events = [make_event(price_min=12.0)]
        html = build_digest_html(events, date(2026, 5, 20), "en", "https://eventradar.ee")
        assert "From €12" in html


# ---------------------------------------------------------------------------
# digest.subject_template
# ---------------------------------------------------------------------------

class TestDigestEmailSubjects:
    def test_all_locales_present(self):
        for locale in ("en", "et", "ru"):
            assert "digest.subject_template" in TRANSLATIONS[locale]

    def test_subject_contains_date_placeholder(self):
        for locale in ("en", "et", "ru"):
            assert "{date}" in TRANSLATIONS[locale]["digest.subject_template"]

    def test_en_subject_format(self):
        assert ti("digest.subject_template", "en", date="Wednesday, May 20") == "Your Daily 5 — Wednesday, May 20"

    def test_et_subject_format(self):
        assert ti("digest.subject_template", "et", date="kolmapäev, 20. mai") == "Sinu päeva 5 — kolmapäev, 20. mai"

    def test_ru_subject_format(self):
        assert ti("digest.subject_template", "ru", date="среда, 20 мая") == "Ваша Пятёрка дня — среда, 20 мая"


class TestDigestI18nConstants:
    DIGEST_KEYS = (
        "digest.subject_label",
        "digest.price_free",
        "digest.price_from",
        "digest.unsubscribe",
        "digest.no_events",
    )

    def test_all_digest_keys_present_per_locale(self):
        for locale in ("en", "et", "ru"):
            for key in self.DIGEST_KEYS:
                assert key in TRANSLATIONS[locale], f"locale {locale} missing key {key}"

    def test_price_from_has_amount_placeholder(self):
        for locale in ("en", "et", "ru"):
            assert "{amount}" in TRANSLATIONS[locale]["digest.price_from"]

    def test_price_from_format(self):
        assert ti("digest.price_from", "en", amount="12") == "From €12"
        assert ti("digest.price_from", "et", amount="12") == "Alates €12"
        assert ti("digest.price_from", "ru", amount="12") == "От €12"

    def test_paid_event_et_locale(self, make_event):
        events = [make_event(price_min=15.0)]
        html = build_digest_html(events, date(2026, 5, 20), "et", "https://eventradar.ee")
        assert "Alates" in html

    def test_t_falls_back_to_en_for_unknown_locale(self):
        assert t("digest.subject_label", "xx") == TRANSLATIONS["en"]["digest.subject_label"]

    def test_t_returns_key_for_unknown_key(self):
        assert t("nonexistent.key", "en") == "nonexistent.key"

    def test_paid_event_ru_locale(self, make_event):
        events = [make_event(price_min=15.0)]
        html = build_digest_html(events, date(2026, 5, 20), "ru", "https://eventradar.ee")
        assert "От" in html

    def test_unsubscribe_et_locale(self):
        html = build_digest_html([], date(2026, 5, 20), "et", "https://eventradar.ee")
        assert "Tühista tellimus" in html

    def test_unsubscribe_ru_locale(self):
        html = build_digest_html([], date(2026, 5, 20), "ru", "https://eventradar.ee")
        assert "Отписаться" in html


# ---------------------------------------------------------------------------
# send_daily_digests — dry_run behaviour
# ---------------------------------------------------------------------------


def _make_db_with_user_and_feed(
    db: AsyncMock, user_id: int = 1, event_ids: list[int] | None = None
) -> AsyncMock:
    """Wire the given mock DB session for a single opted-in user with a feed."""
    if event_ids is None:
        event_ids = [10]

    user = MagicMock()
    user.id = user_id
    user.email = "test@example.com"
    user.locale = "en"
    user.email_digest_opt_in = True
    user.email_verified = True

    feed = MagicMock()
    feed.user_id = user_id
    feed.event_ids = event_ids

    event = MagicMock()
    event.id = event_ids[0]

    # db.scalars(...) is awaited; the awaited result must be a sync MagicMock
    # whose .all() returns a plain list — not an AsyncMock (which makes .all() async).
    def _sync_result(rows):
        r = MagicMock()
        r.all.return_value = rows
        return r

    # First call → opted-in user ids, second call → the page's User rows,
    # third call → feeds, fourth call → events.
    db.scalars = AsyncMock(
        side_effect=[
            _sync_result([user_id]),
            _sync_result([user]),
            _sync_result([feed]),
            _sync_result([event]),
        ]
    )
    return db


class TestSendDailyDigestsDryRun:
    @pytest.mark.asyncio
    async def test_dry_run_does_not_call_send_digest_email(self, mock_db):
        db = _make_db_with_user_and_feed(mock_db)
        with (
            patch("app.email.digest.datetime") as mock_dt,
            patch("app.email.digest.send_digest_email", new_callable=AsyncMock) as mock_send,
        ):
            mock_dt.now.return_value.date.return_value = date(2026, 6, 9)
            result = await send_daily_digests(db, dry_run=True)

        mock_send.assert_not_awaited()
        assert result["dry_run"] is True
        assert result["sent"] == 1

    @pytest.mark.asyncio
    async def test_user_query_filters_on_email_verified(self, mock_db):
        db = _make_db_with_user_and_feed(mock_db)
        with (
            patch("app.email.digest.datetime") as mock_dt,
            patch("app.email.digest.send_digest_email", new_callable=AsyncMock),
        ):
            mock_dt.now.return_value.date.return_value = date(2026, 6, 9)
            await send_daily_digests(db, dry_run=True)

        stmt = db.scalars.call_args_list[0].args[0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "email_verified" in compiled
        assert "email_digest_opt_in" in compiled

    @pytest.mark.asyncio
    async def test_event_query_excludes_explicit_events(self, mock_db):
        db = _make_db_with_user_and_feed(mock_db)
        with (
            patch("app.email.digest.datetime") as mock_dt,
            patch("app.email.digest.send_digest_email", new_callable=AsyncMock),
        ):
            mock_dt.now.return_value.date.return_value = date(2026, 6, 9)
            await send_daily_digests(db, dry_run=True)

        stmt = db.scalars.call_args_list[3].args[0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "is_explicit" in compiled
        assert "is_non_event" in compiled
        assert "false" in compiled.lower()

    @pytest.mark.asyncio
    async def test_dry_run_false_calls_send_digest_email(self, mock_db):
        db = _make_db_with_user_and_feed(mock_db)
        with (
            patch("app.email.digest.datetime") as mock_dt,
            patch("app.email.digest.send_digest_email", new_callable=AsyncMock) as mock_send,
        ):
            mock_dt.now.return_value.date.return_value = date(2026, 6, 9)
            result = await send_daily_digests(db, dry_run=False)

        mock_send.assert_awaited_once()
        assert result["dry_run"] is False

    @pytest.mark.asyncio
    async def test_dry_run_key_present_in_early_return_no_users(self, mock_db):
        no_users = MagicMock()
        no_users.all.return_value = []

        db = mock_db
        db.scalars = AsyncMock(return_value=no_users)

        with patch("app.email.digest.datetime") as mock_dt:
            mock_dt.now.return_value.date.return_value = date(2026, 6, 9)
            result = await send_daily_digests(db, dry_run=True)

        assert "dry_run" in result
        assert result["dry_run"] is True

    @pytest.mark.asyncio
    async def test_dry_run_key_present_in_early_return_no_feeds(self, mock_db):
        user = MagicMock()
        user.id = 1
        user.email_digest_opt_in = True

        feed = MagicMock()
        feed.user_id = 1
        feed.event_ids = []

        def _sync_result(rows):
            r = MagicMock()
            r.all.return_value = rows
            return r

        db = mock_db
        db.scalars = AsyncMock(
            side_effect=[_sync_result([user.id]), _sync_result([user]), _sync_result([feed])]
        )

        with patch("app.email.digest.datetime") as mock_dt:
            mock_dt.now.return_value.date.return_value = date(2026, 6, 9)
            result = await send_daily_digests(db, dry_run=False)

        assert "dry_run" in result
        assert result["dry_run"] is False


class TestThemeClassHooksPresent:
    """Drift guard: every _THEME_CLASS_RULES key must be wired into markup
    somewhere across the email builders — catches a class added to the CSS
    table but never hooked in, or renamed on one side only. No single
    builder uses every hook (e-body-text/e-muted are magic-link/report-only,
    e-card/e-band/... are digest-only), so this checks the union."""

    def test_every_theme_class_rendered_across_builders(self, make_event):
        from app.email.magic_link import build_magic_link_html
        from app.email.report_reporter import build_report_outcome_html

        events = [make_event(price_min=12.0, why_go=["Great show"])]
        digest_html = build_digest_html(
            events, date(2026, 5, 20), "en", "https://eventradar.ee"
        )
        magic_link_html = build_magic_link_html(
            "https://example.com/verify?token=x", 15, "en"
        )
        report_html = build_report_outcome_html(
            make_event(10, title="Concert"), "Fine.", "en"
        )
        combined = digest_html + magic_link_html + report_html

        for cls in _THEME_CLASS_RULES:
            assert re.search(
                rf'class="[^"]*\b{re.escape(cls)}\b[^"]*"', combined
            ), cls
