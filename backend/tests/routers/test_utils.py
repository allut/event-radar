"""Unit tests for app.routers.utils helpers."""
import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.constants.core import APP_ENV_DEVELOPMENT
from app.routers.utils import (
    compute_preferred_taxonomy,
    fold_legacy_category,
    load_user_reported_events,
    prepend_organizer_categories,
    recent_unused_link_exists,
    replace_organizer_categories,
    resolve_locale_param,
    serialize_event,
    stream_admin_job,
    validate_categories,
)
from app.events.cancellation import resolve_open_reports, send_report_resolution_emails
from app.claims.target_resolution import bulk_resolve_publisher_events
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
from app.auth.utils import mask_email, require_configured_secret


class TestPrependOrganizerCategories:
    """Used by organizer_claim_edits.py (#416's prepend-only claim-edit categories)."""

    @pytest.mark.asyncio
    async def test_creates_classification_when_none_exists(self, mock_db):
        mock_db.scalar.return_value = None
        mock_db.add = MagicMock()

        await prepend_organizer_categories(mock_db, 10, ["music", "family"])

        mock_db.add.assert_called_once()
        added = mock_db.add.call_args[0][0]
        assert added.event_id == 10
        assert added.categories == ["music", "family"]

    @pytest.mark.asyncio
    async def test_prepends_several_in_order(self, mock_db):
        classification = MagicMock()
        classification.categories = ["theater"]
        mock_db.scalar.return_value = classification

        await prepend_organizer_categories(mock_db, 10, ["music", "family"])

        assert classification.categories == ["music", "family", "theater"]

    @pytest.mark.asyncio
    async def test_dedupes_against_existing(self, mock_db):
        classification = MagicMock()
        classification.categories = ["music", "theater"]
        mock_db.scalar.return_value = classification

        await prepend_organizer_categories(mock_db, 10, ["family", "music"])

        assert classification.categories == ["family", "music", "theater"]

    @pytest.mark.asyncio
    async def test_all_present_leaves_order_untouched(self, mock_db):
        classification = MagicMock()
        classification.categories = ["music", "theater"]
        mock_db.scalar.return_value = classification

        await prepend_organizer_categories(mock_db, 10, ["theater"])

        assert classification.categories == ["music", "theater"]


class TestPrependOrganizerCategoriesCap:
    @pytest.mark.asyncio
    async def test_over_total_cap_rejected_and_untouched(self, mock_db):
        classification = MagicMock()
        classification.categories = ["music", "theater"]
        mock_db.scalar.return_value = classification

        with pytest.raises(HTTPException) as exc:
            await prepend_organizer_categories(
                mock_db, 10, ["family", "comedy"], max_total=3
            )

        assert exc.value.status_code == 422
        assert classification.categories == ["music", "theater"]

    @pytest.mark.asyncio
    async def test_exactly_at_cap_allowed(self, mock_db):
        classification = MagicMock()
        classification.categories = ["music", "theater"]
        mock_db.scalar.return_value = classification

        await prepend_organizer_categories(mock_db, 10, ["family"], max_total=3)

        assert classification.categories == ["family", "music", "theater"]

    @pytest.mark.asyncio
    async def test_already_present_picks_do_not_count(self, mock_db):
        classification = MagicMock()
        classification.categories = ["music", "theater", "family"]
        mock_db.scalar.return_value = classification

        await prepend_organizer_categories(mock_db, 10, ["music"], max_total=3)

        assert classification.categories == ["music", "theater", "family"]

    @pytest.mark.asyncio
    async def test_event_over_cap_cannot_gain(self, mock_db):
        classification = MagicMock()
        classification.categories = ["a", "b", "c", "d"]
        mock_db.scalar.return_value = classification

        with pytest.raises(HTTPException):
            await prepend_organizer_categories(mock_db, 10, ["music"], max_total=3)


class TestReplaceOrganizerCategories:
    """Used by organizer_events.py (own-submission create + edit)."""

    @pytest.mark.asyncio
    async def test_creates_classification_when_none_exists(self, mock_db):
        mock_db.scalar.return_value = None
        mock_db.add = MagicMock()

        await replace_organizer_categories(mock_db, 10, ["music", "family"])

        added = mock_db.add.call_args[0][0]
        assert added.event_id == 10
        assert added.categories == ["music", "family"]

    @pytest.mark.asyncio
    async def test_replaces_llm_set(self, mock_db):
        classification = MagicMock()
        classification.categories = ["theater", "comedy"]
        mock_db.scalar.return_value = classification

        await replace_organizer_categories(mock_db, 10, ["music", "family"])

        assert classification.categories == ["music", "family"]


class TestValidateCategories:
    def test_none_passes_through(self):
        assert validate_categories(None) is None

    def test_dedupes_keeping_order(self):
        assert validate_categories(["music", "family", "music"]) == ["music", "family"]

    def test_invalid_slug_rejected(self):
        with pytest.raises(ValueError, match="invalid category"):
            validate_categories(["music", "nope"])

    def test_over_cap_rejected(self):
        with pytest.raises(ValueError, match="at most"):
            validate_categories(["music", "family", "theater", "comedy"])

    def test_duplicates_do_not_count_toward_cap(self):
        assert validate_categories(["music", "music", "family", "theater"]) == [
            "music",
            "family",
            "theater",
        ]


class TestFoldLegacyCategory:
    def test_folds_into_categories(self):
        assert fold_legacy_category({"title": "x", "category": "music"}) == {
            "title": "x",
            "categories": ["music"],
        }

    def test_explicit_categories_win(self):
        assert fold_legacy_category({"category": "music", "categories": ["family"]}) == {
            "categories": ["family"]
        }

    def test_null_legacy_dropped(self):
        assert fold_legacy_category({"category": None}) == {}

    def test_non_dict_untouched(self):
        assert fold_legacy_category("x") == "x"


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


class TestBulkResolvePublisherEvents:
    """Shared by admin.py::admin_list_claims and
    app.claims.lifecycle._send_claim_expiry_emails (#421) — two fixed
    queries regardless of how many publisher_ids are passed, freshest
    EventSource (highest id) wins per publisher."""

    @pytest.mark.asyncio
    async def test_empty_input_short_circuits_with_no_queries(self, mock_db):
        result = await bulk_resolve_publisher_events(mock_db, set())

        assert result == {}
        mock_db.scalars.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_freshest_event_source_wins_per_publisher(self, mock_db, make_event):
        event = make_event(event_id=2)
        # DISTINCT ON (publisher_id) ORDER BY id DESC — one (publisher_id,
        # event_id) row per publisher, the freshest listing's.
        mock_db.execute = AsyncMock(
            return_value=MagicMock(all=MagicMock(return_value=[(99, 2)]))
        )
        mock_db.scalars = AsyncMock(
            side_effect=[MagicMock(all=MagicMock(return_value=[event]))]
        )

        result = await bulk_resolve_publisher_events(mock_db, {99})

        assert result == {99: event}

    @pytest.mark.asyncio
    async def test_no_matching_event_sources_returns_empty(self, mock_db):
        mock_db.execute = AsyncMock(
            return_value=MagicMock(all=MagicMock(return_value=[]))
        )

        result = await bulk_resolve_publisher_events(mock_db, {99})

        assert result == {}


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
            "app.events.cancellation.send_report_outcome_email", new=AsyncMock()
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
            "app.events.cancellation.send_report_outcome_email", new=AsyncMock()
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
            "app.events.cancellation.send_report_outcome_email", new=AsyncMock()
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
                "app.events.cancellation.send_report_outcome_email",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
            caplog.at_level(logging.ERROR),
        ):
            await send_report_resolution_emails(mock_db, event, [report], "Reviewed.")

        assert any(
            "Failed to send report outcome email" in r.getMessage()
            for r in caplog.records
        )

    @pytest.mark.asyncio
    async def test_one_uncaught_failure_does_not_abort_the_batch(
        self, mock_db, make_event, make_report, make_user
    ):
        """A failure _send_one's own try/except doesn't catch (anything
        broader than Exception, e.g. a BaseException) must not cancel the
        other in-flight sends — asyncio.gather(..., return_exceptions=True)
        is what guarantees that."""
        from unittest.mock import AsyncMock, MagicMock, patch

        class _SimulatedFatalError(BaseException):
            pass

        event = make_event(42)
        report_a = make_report(report_id=1, user_id=1, event_id=42, status="resolved")
        report_b = make_report(report_id=2, user_id=2, event_id=42, status="resolved")
        user_a = make_user(user_id=1)
        user_b = make_user(user_id=2)
        user_b.email = "other@example.com"

        mock_db.scalars.return_value = MagicMock(
            all=MagicMock(return_value=[user_a, user_b])
        )

        async def _raise_for_a(email: str, *args: object, **kwargs: object) -> None:
            if email == user_a.email:
                raise _SimulatedFatalError("boom")

        with patch(
            "app.events.cancellation.send_report_outcome_email",
            new=AsyncMock(side_effect=_raise_for_a),
        ) as mock_send:
            await send_report_resolution_emails(
                mock_db, event, [report_a, report_b], "Reviewed."
            )

        assert mock_send.await_count == 2


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


class TestRecentUnusedLinkExists:
    @pytest.mark.asyncio
    async def test_extra_predicate_is_applied_to_the_query(self, mock_db):
        """Google sign-in's confirmation-link cooldown (organizer_auth.py)
        must only match a pending link for the *same* sub — not any unused
        link for the organizer — or it can silently suppress the
        confirmation email while reporting it as sent."""
        from app.models.models import OrganizerMagicLink

        mock_db.scalar = AsyncMock(return_value=None)

        await recent_unused_link_exists(
            mock_db,
            OrganizerMagicLink,
            OrganizerMagicLink.organizer_id,
            5,
            900,
            extra_predicate=OrganizerMagicLink.pending_google_sub == "sub-123",
        )

        stmt = mock_db.scalar.call_args.args[0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "pending_google_sub" in compiled
        assert "sub-123" in compiled

    @pytest.mark.asyncio
    async def test_no_extra_predicate_omits_it_from_the_query(self, mock_db):
        """Existing callers (plain magic-link resend cooldown) must keep
        matching on the fk alone — the new parameter is additive."""
        from app.models.models import OrganizerMagicLink

        mock_db.scalar = AsyncMock(return_value=None)

        await recent_unused_link_exists(
            mock_db, OrganizerMagicLink, OrganizerMagicLink.organizer_id, 5, 900
        )

        stmt = mock_db.scalar.call_args.args[0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        where_clause = compiled.split("WHERE", 1)[1]
        assert "pending_google_sub" not in where_clause


class TestOrganizerSharedHelpers:
    def test_validate_time_ordering(self):
        from app.routers.utils import validate_time_ordering

        early = datetime(2026, 6, 1, 18, tzinfo=timezone.utc)
        late = datetime(2026, 6, 1, 20, tzinfo=timezone.utc)
        validate_time_ordering(early, late)
        validate_time_ordering(early, None)
        validate_time_ordering(None, early)
        with pytest.raises(ValueError, match="ends_at must not be before starts_at"):
            validate_time_ordering(late, early)

    def test_localized_dict_drops_blank_and_absent_locales(self):
        from app.routers.utils import localized_dict

        assert localized_dict("et", "en", None) == {"et": "et", "en": "en"}
        assert localized_dict("et", "  ", "") == {"et": "et"}
        assert localized_dict(None, None, None) is None

    def test_merged_localized_keeps_existing_and_overrides_set_fields(self):
        from types import SimpleNamespace

        from app.routers.utils import merged_localized

        body = SimpleNamespace(title_en="New EN", title_ru=None)
        existing = {"et": "old", "en": "Old EN", "ru": "Old RU"}

        # only en is in fields_set: ru keeps its existing value
        assert merged_localized(existing, "Uus", body, {"title_en"}, "title") == {
            "et": "Uus",
            "en": "New EN",
            "ru": "Old RU",
        }
        # ru explicitly cleared (None in fields_set) drops the locale
        assert merged_localized(existing, "Uus", body, {"title_ru"}, "title") == {
            "et": "Uus",
            "en": "Old EN",
        }

    def test_merged_localized_applies_sanitizer_to_request_values_only(self):
        from types import SimpleNamespace

        from app.routers.utils import merged_localized

        body = SimpleNamespace(description_en="<b>x</b>", description_ru=None)
        result = merged_localized(
            {"ru": "<i>kept</i>"},
            "et",
            body,
            {"description_en"},
            "description",
            sanitize=str.upper,
        )
        assert result == {"et": "et", "en": "<B>X</B>", "ru": "<i>kept</i>"}

    def test_apply_price_edit_fills_default_currency_for_price_only_patch(self, make_event):
        from types import SimpleNamespace

        from app._generated.shared_constants import DEFAULT_CURRENCY
        from app.routers.utils import apply_price_edit

        event = make_event(price_min=None)
        event.price_max = None
        event.currency = None
        body = SimpleNamespace(price_min=5.0, price_max=None, currency=None)

        apply_price_edit(event, body, {"price_min"})

        assert event.price_min == 5.0
        assert event.currency == DEFAULT_CURRENCY

    def test_apply_price_edit_zero_price_still_counts_as_priced(self, make_event):
        """Numeric-truthiness rule: a free (0) price is a price."""
        from types import SimpleNamespace

        from app._generated.shared_constants import DEFAULT_CURRENCY
        from app.routers.utils import apply_price_edit

        event = make_event(price_min=None)
        event.price_max = None
        event.currency = None
        body = SimpleNamespace(price_min=0.0, price_max=None, currency=None)

        apply_price_edit(event, body, {"price_min"})

        assert event.currency == DEFAULT_CURRENCY

    def test_apply_moderation_flags_sets_flags_and_reports_change(self, make_event):
        from app.routers.utils import apply_moderation_flags

        event = make_event(title="Nice concert")
        event.is_explicit = False
        event.is_non_event = False
        with patch("app.routers.utils.content_flags", return_value=(True, False)):
            assert apply_moderation_flags(event, "Hall", "extra") is True

        assert event.is_explicit is True
        assert event.is_non_event is False

    def test_apply_moderation_flags_clean_event_returns_false(self, make_event):
        from app.routers.utils import apply_moderation_flags

        event = make_event(title="Nice concert")
        event.is_explicit = False
        event.is_non_event = False
        assert apply_moderation_flags(event, "Hall") is False
        assert event.is_explicit is False

    def test_apply_moderation_flags_scans_localized_text(self, make_event):
        """OWASP audit M-5: explicit text hidden only in EN/RU fields is caught."""
        from app.routers.utils import apply_moderation_flags

        event = make_event(title="Nice concert")
        event.is_explicit = False
        event.is_non_event = False
        event.title_localized = {"en": "Nice concert", "ru": "xxx porn night"}
        event.description_localized = None
        event.important_info_localized = None
        event.important_info = None
        assert apply_moderation_flags(event, "Hall") is True
        assert event.is_explicit is True
