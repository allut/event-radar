"""Tests for the ENABLE_SCHEDULER dev-only kill switch (app/main.py::_start_scheduler)."""

from unittest.mock import MagicMock, patch

from app.constants.core import APP_ENV_DEVELOPMENT
from app.main import _start_scheduler

_KNOWN_JOB_IDS = {
    "sync_fienta_organizers",
    "cleanup_stale_data",
    "ingest_all_sources",
    "dedup_pass",
    "classify_pending",
    "publish_pending",
    "geocode_pending",
    "backfill_publisher_ids",
    "refetch_event_details",
    "build_daily_feeds",
    "send_daily_digests",
    "expire_stale_claims",
    "flush_promotion_counters",
    "sweep_promotions",
}


def test_disabled_in_development_returns_none_and_warns():
    with (
        patch("app.main.settings") as mock_settings,
        patch("app.main.log") as mock_log,
        patch("app.main.AsyncIOScheduler") as mock_cls,
    ):
        mock_settings.ENABLE_SCHEDULER = False
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT
        result = _start_scheduler()
    assert result is None
    mock_cls.assert_not_called()
    mock_log.warning.assert_called_once()


def test_disabled_outside_development_ignored_and_starts():
    with (
        patch("app.main.settings") as mock_settings,
        patch("app.main.log") as mock_log,
        patch("app.main.AsyncIOScheduler") as mock_cls,
    ):
        mock_settings.ENABLE_SCHEDULER = False
        mock_settings.APP_ENV = "production"
        mock_scheduler = MagicMock()
        mock_cls.return_value = mock_scheduler
        result = _start_scheduler()
    assert result is mock_scheduler
    mock_scheduler.start.assert_called_once()
    mock_log.warning.assert_called_once()


def test_enabled_constructs_and_starts_scheduler():
    with (
        patch("app.main.settings") as mock_settings,
        patch("app.main.AsyncIOScheduler") as mock_cls,
    ):
        mock_settings.ENABLE_SCHEDULER = True
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT
        mock_scheduler = MagicMock()
        mock_cls.return_value = mock_scheduler
        result = _start_scheduler()
    mock_cls.assert_called_once_with(timezone="Europe/Tallinn")
    mock_scheduler.start.assert_called_once()
    assert result is mock_scheduler


def test_full_schedule_wired_when_enabled():
    with (
        patch("app.main.settings") as mock_settings,
        patch("app.main.AsyncIOScheduler") as mock_cls,
    ):
        mock_settings.ENABLE_SCHEDULER = True
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT
        mock_scheduler = MagicMock()
        mock_cls.return_value = mock_scheduler
        _start_scheduler()
    job_ids = {
        call.kwargs["id"] for call in mock_scheduler.add_job.call_args_list
    }
    assert job_ids == _KNOWN_JOB_IDS
