"""Unit tests for app.routers.utils helpers."""
from datetime import datetime, timezone

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
    serialize_event,
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


class TestEventEndedFilter:
    """event_ended_filter must NOT be ``not_(event_not_ended_filter(...))`` —
    negating that expression hits SQL three-valued logic: for an ended event
    with ``ends_at IS NULL``, ``event_not_ended_filter`` evaluates to NULL
    (via ``ends_at >= now``), and ``NOT NULL`` is also NULL, which a WHERE
    clause treats as non-matching. event_ended_filter must build the
    complement directly using ``<`` comparisons so it has no such gap."""

    def test_compiles_without_negating_a_nullable_comparison(self):
        now = datetime(2026, 6, 25, tzinfo=timezone.utc)
        compiled = str(
            event_ended_filter(now).compile(compile_kwargs={"literal_binds": True})
        )
        assert "NOT" not in compiled.upper()
        assert "events.ends_at <" in compiled
        assert "events.ends_at IS NULL" in compiled
        assert "events.starts_at <" in compiled
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
