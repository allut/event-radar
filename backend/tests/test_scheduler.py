"""Tests for the ENABLE_SCHEDULER dev-only kill switch (app/scheduler.py::start_scheduler)."""

import re
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.constants.core import APP_ENV_DEVELOPMENT, TALLINN_TZ, TALLINN_TZ_NAME
from app.constants.jobs import (
    CLEANUP_HOUR,
    JOB_ID_CLEANUP_STALE_DATA,
    JOB_ID_SYNC_FIENTA_ORGANIZERS,
    ORGANIZER_SYNC_HOUR,
)
from app.scheduler import _register_scheduled_jobs, start_scheduler

# Local hour that repeats on fall-back day and vanishes on spring-forward day.
_TALLINN_DST_TRANSITION_HOUR = 3
_DST_CHANGE_DAYS = ((2026, 10, 25), (2027, 3, 28))

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
        patch("app.scheduler.settings") as mock_settings,
        patch("app.scheduler.log") as mock_log,
        patch("app.scheduler.AsyncIOScheduler") as mock_cls,
    ):
        mock_settings.ENABLE_SCHEDULER = False
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT
        result = start_scheduler()
    assert result is None
    mock_cls.assert_not_called()
    mock_log.warning.assert_called_once()


def test_disabled_outside_development_ignored_and_starts():
    with (
        patch("app.scheduler.settings") as mock_settings,
        patch("app.scheduler.log") as mock_log,
        patch("app.scheduler.AsyncIOScheduler") as mock_cls,
    ):
        mock_settings.ENABLE_SCHEDULER = False
        mock_settings.APP_ENV = "production"
        mock_scheduler = MagicMock()
        mock_cls.return_value = mock_scheduler
        result = start_scheduler()
    assert result is mock_scheduler
    mock_scheduler.start.assert_called_once()
    mock_log.warning.assert_called_once()


def test_enabled_constructs_and_starts_scheduler():
    with (
        patch("app.scheduler.settings") as mock_settings,
        patch("app.scheduler.AsyncIOScheduler") as mock_cls,
    ):
        mock_settings.ENABLE_SCHEDULER = True
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT
        mock_scheduler = MagicMock()
        mock_cls.return_value = mock_scheduler
        result = start_scheduler()
    mock_cls.assert_called_once_with(timezone="Europe/Tallinn")
    mock_scheduler.start.assert_called_once()
    assert result is mock_scheduler


def test_full_schedule_wired_when_enabled():
    with (
        patch("app.scheduler.settings") as mock_settings,
        patch("app.scheduler.AsyncIOScheduler") as mock_cls,
    ):
        mock_settings.ENABLE_SCHEDULER = True
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT
        mock_scheduler = MagicMock()
        mock_cls.return_value = mock_scheduler
        start_scheduler()
    job_ids = {
        call.kwargs["id"] for call in mock_scheduler.add_job.call_args_list
    }
    assert job_ids == _KNOWN_JOB_IDS


def _cron_jobs() -> dict[str, CronTrigger]:
    scheduler = AsyncIOScheduler(timezone=TALLINN_TZ_NAME)
    _register_scheduled_jobs(scheduler)
    return {
        job.id: job.trigger
        for job in scheduler.get_jobs()
        if isinstance(job.trigger, CronTrigger)
    }


def _hour_field(trigger: CronTrigger) -> str:
    return str(next(f for f in trigger.fields if f.name == "hour"))


def _fires_on_day(trigger: CronTrigger, day: tuple[int, int, int]) -> list[datetime]:
    day_start = datetime(*day, tzinfo=TALLINN_TZ)
    day_end = day_start + timedelta(days=1)
    fires = []
    now = (day_start - timedelta(hours=1)).astimezone(timezone.utc)
    while (nxt := trigger.get_next_fire_time(None, now)) is not None:
        if nxt >= day_end:
            break
        if nxt >= day_start:
            fires.append(nxt)
        now = nxt + timedelta(seconds=1)
    return fires


def test_no_cron_job_fires_in_dst_transition_hour_or_twice():
    cron_jobs = _cron_jobs()
    assert cron_jobs
    for job_id, trigger in cron_jobs.items():
        for day in _DST_CHANGE_DAYS:
            local = [f.astimezone(TALLINN_TZ) for f in _fires_on_day(trigger, day)]
            assert all(f.hour != _TALLINN_DST_TRANSITION_HOUR for f in local), job_id
            wall = [f.replace(tzinfo=None) for f in local]
            assert len(wall) == len(set(wall)), job_id


def test_weekly_jobs_fire_once_on_dst_change_days():
    cron_jobs = _cron_jobs()
    for job_id, hour in (
        (JOB_ID_SYNC_FIENTA_ORGANIZERS, ORGANIZER_SYNC_HOUR),
        (JOB_ID_CLEANUP_STALE_DATA, CLEANUP_HOUR),
    ):
        for day in _DST_CHANGE_DAYS:
            fires = _fires_on_day(cron_jobs[job_id], day)
            assert len(fires) == 1, (job_id, day, fires)
            assert fires[0].astimezone(TALLINN_TZ).hour == hour


_BACKEND_OPS_DOC = Path(__file__).resolve().parents[2] / "docs" / "backend-ops.md"
_CADENCE_ROW = re.compile(r"^\| (?:Daily|Sun) (\d{2}):(\d{2}) \| `(\w+)` \|$", re.M)


def test_cadence_table_matches_registered_cron_triggers():
    rows = _CADENCE_ROW.findall(_BACKEND_OPS_DOC.read_text(encoding="utf-8"))
    cron_jobs = _cron_jobs()
    assert {job_id for _, _, job_id in rows} == set(cron_jobs)
    for hour, minute, job_id in rows:
        fields = {f.name: str(f) for f in cron_jobs[job_id].fields}
        assert (fields["hour"], fields["minute"]) == (str(int(hour)), str(int(minute))), job_id
