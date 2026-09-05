"""Unit tests for app.routers.utils helpers."""
import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.constants import APP_ENV_DEVELOPMENT
from app.routers.utils import (
    compute_preferred_taxonomy,
    event_ended_filter,
    event_not_ended_filter,
    event_series_key,
    load_user_reported_events,
    mask_email,
    normalized_title,
    require_configured_secret,
    resolve_locale_param,
    resolve_open_reports,
    resolve_venue_address,
    resolve_venue_coords,
    resolve_venue_name,
    send_report_resolution_emails,
    serialize_event,
    stream_admin_job,
)


class TestRequireConfiguredSecret:
    """M1: a dev-shaped APP_ENV alone must never be sufficient to fail open —
    ALLOW_INSECURE_DEV must also be explicitly true."""

    def test_configured_secret_returns_true_regardless_of_env(self):
        assert require_configured_secret(
            "s3cret",
            feature="Admin",
            setting_name="ADMIN_PASSWORD",
            app_env="production",
            allow_insecure_dev=False,
        ) is True

    def test_unset_secret_in_production_raises_503(self):
        with pytest.raises(HTTPException) as exc_info:
            require_configured_secret(
                "",
                feature="Admin",
                setting_name="ADMIN_PASSWORD",
                app_env="production",
                allow_insecure_dev=True,
            )
        assert exc_info.value.status_code == 503

    def test_unset_secret_in_dev_without_allow_insecure_dev_raises_503(self):
        """The core M1 regression guard: APP_ENV=development alone is not enough."""
        with pytest.raises(HTTPException) as exc_info:
            require_configured_secret(
                None,
                feature="Admin",
                setting_name="ADMIN_PASSWORD",
                app_env=APP_ENV_DEVELOPMENT,
                allow_insecure_dev=False,
            )
        assert exc_info.value.status_code == 503

    def test_unset_secret_in_dev_with_allow_insecure_dev_returns_false(self):
        result = require_configured_secret(
            "",
            feature="Admin",
            setting_name="ADMIN_PASSWORD",
            app_env=APP_ENV_DEVELOPMENT,
            allow_insecure_dev=True,
        )
        assert result is False

    def test_allow_insecure_dev_true_but_wrong_env_still_raises(self):
        with pytest.raises(HTTPException) as exc_info:
            require_configured_secret(
                "",
                feature="Admin",
                setting_name="ADMIN_PASSWORD",
                app_env="production",
                allow_insecure_dev=True,
            )
        assert exc_info.value.status_code == 503


class TestNormalizedTitle:
    def test_lowercases(self):
        assert normalized_title("Van GOGH") == "van gogh"

    def test_collapses_internal_whitespace(self):
        assert normalized_title("  Van   Gogh\tImmersive ") == "van gogh immersive"

    def test_idempotent(self):
        once = normalized_title("Jazz   Night")
        assert normalized_title(once) == once


class TestResolveLocaleParam:
    def test_valid_locale_wins_over_fallback(self):
        assert resolve_locale_param("et", "en") == "et"

    def test_none_falls_back(self):
        assert resolve_locale_param(None, "en") == "en"

    def test_invalid_falls_back(self):
        assert resolve_locale_param("xx", "en") == "en"


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


class TestResolveOpenReports:
    """resolve_open_reports() only mutates EventReport rows — it must not
    itself send any email (issue #127's send_report_resolution_emails is a
    separate, explicitly post-commit step; see its own tests below)."""

    @pytest.mark.asyncio
    async def test_does_not_send_email(self, mock_db, make_event, make_report):
        from unittest.mock import AsyncMock, patch

        event = make_event(42)
        report = make_report(report_id=1, user_id=1, event_id=42, status="open")
        mock_db.execute.return_value.scalars.return_value.all.return_value = [report]

        with patch(
            "app.routers.utils.send_report_outcome_email", new=AsyncMock()
        ) as mock_send:
            resolved = await resolve_open_reports(mock_db, event, "Reviewed.")

        assert len(resolved) == 1
        mock_send.assert_not_awaited()


class TestSendReportResolutionEmails:
    """send_report_resolution_emails() fires one reporter-outcome email per
    resolved report (issue #127) — fan-out to multiple reporters, and a
    per-report swallow-and-log on send failure so one bad address can't
    block the rest. Callers invoke this AFTER their own db.commit()."""

    @pytest.mark.asyncio
    async def test_fans_out_one_email_per_reporter(
        self, mock_db, make_event, make_report, make_user
    ):
        from unittest.mock import AsyncMock, MagicMock, patch

        event = make_event(42)
        report_a = make_report(report_id=1, user_id=1, event_id=42, status="open")
        report_b = make_report(report_id=2, user_id=2, event_id=42, status="open")
        report_a.status = report_b.status = "resolved"
        user_a = make_user(user_id=1)
        user_b = make_user(user_id=2)
        user_b.email = "other@example.com"

        mock_db.scalars.return_value = MagicMock(
            all=MagicMock(return_value=[user_a, user_b])
        )

        with patch(
            "app.routers.utils.send_report_outcome_email", new=AsyncMock()
        ) as mock_send:
            await send_report_resolution_emails(
                mock_db, event, [report_a, report_b], "Reviewed."
            )

        assert mock_send.await_count == 2
        sent_to = {call.args[0] for call in mock_send.await_args_list}
        assert sent_to == {user_a.email, "other@example.com"}

    @pytest.mark.asyncio
    async def test_no_reports_short_circuits(self, mock_db, make_event):
        from unittest.mock import AsyncMock, patch

        with patch(
            "app.routers.utils.send_report_outcome_email", new=AsyncMock()
        ) as mock_send:
            await send_report_resolution_emails(mock_db, make_event(42), [], "note")

        mock_send.assert_not_awaited()
        mock_db.scalars.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_failure_is_swallowed_and_logged(
        self, mock_db, make_event, make_report, make_user, caplog
    ):
        import logging
        from unittest.mock import AsyncMock, MagicMock, patch

        event = make_event(42)
        report = make_report(report_id=1, user_id=1, event_id=42, status="resolved")
        user = make_user(user_id=1)

        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[user]))

        with (
            patch(
                "app.routers.utils.send_report_outcome_email",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
            caplog.at_level(logging.ERROR),
        ):
            await send_report_resolution_emails(mock_db, event, [report], "Reviewed.")

        assert any(
            "Failed to send report outcome email" in r.getMessage()
            for r in caplog.records
        )


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


class TestStreamAdminJob:
    """Regression coverage for issue #159: Starlette's StreamingResponse
    cancels its streaming generator on a client disconnect (task-group race
    against listen_for_disconnect on uvicorn's pinned ASGI spec_version
    "2.3"). stream_admin_job must not let that cancellation reach the
    job coroutine itself: the job has to keep running to completion (and
    still get logged) even after the consumer stops reading."""

    @pytest.mark.asyncio
    async def test_job_completes_and_logs_after_generator_is_cancelled(self):
        job_done = asyncio.Event()

        async def slow_job() -> dict:
            await asyncio.sleep(0.05)
            job_done.set()
            return {"ok": True}

        with patch("app.routers.utils.log_admin_action") as mock_log:
            gen = stream_admin_job("Test", "test", "test_action", "target", slow_job())
            first = asyncio.ensure_future(gen.__anext__())
            await asyncio.sleep(0.01)  # let the runner task start; job is still sleeping
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            await gen.aclose()  # what Starlette does to the generator on disconnect

            await asyncio.wait_for(job_done.wait(), timeout=1)
            await asyncio.sleep(0.02)  # let the runner's log_admin_action call land

        mock_log.assert_called_once_with(None, "test_action", "target", {"ok": True})

    @pytest.mark.asyncio
    async def test_normal_completion_streams_one_ok_line(self):
        async def job() -> dict:
            return {"processed": 3}

        with patch("app.routers.utils.log_admin_action") as mock_log:
            lines = [line async for line in stream_admin_job("Test", "test", "test_action", "target", job())]

        assert len(lines) == 1
        assert json.loads(lines[0]) == {"stage": "test", "status": "ok", "result": {"processed": 3}, "error": None}
        mock_log.assert_called_once_with(None, "test_action", "target", {"processed": 3})
