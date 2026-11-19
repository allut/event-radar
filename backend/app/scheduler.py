import logging
import time
from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]

from app.claims.lifecycle import expire_stale_claims
from app.cleanup import cleanup_stale_data
from app.config import settings
from app.constants.core import APP_ENV_DEVELOPMENT, MS_PER_SECOND, TALLINN_TZ_NAME
from app.constants.jobs import (
    CLEANUP_HOUR,
    CLEANUP_MINUTE,
    DIGEST_SEND_HOUR,
    DIGEST_SEND_MINUTE,
    EXPIRE_STALE_CLAIMS_HOUR,
    EXPIRE_STALE_CLAIMS_MINUTE,
    FEED_BUILD_HOUR,
    FEED_BUILD_MINUTE,
    INGEST_INTERVAL_HOURS,
    JOB_ID_BACKFILL_PUBLISHER_IDS,
    JOB_ID_BUILD_DAILY_FEEDS,
    JOB_ID_CLASSIFY_PENDING,
    JOB_ID_CLEANUP_STALE_DATA,
    JOB_ID_DEDUP_PASS,
    JOB_ID_EXPIRE_STALE_CLAIMS,
    JOB_ID_FLUSH_PROMOTION_COUNTERS,
    JOB_ID_SWEEP_PROMOTIONS,
    JOB_ID_GEOCODE_PENDING,
    JOB_ID_INGEST_ALL_SOURCES,
    JOB_ID_PUBLISH_PENDING,
    JOB_ID_REFETCH_EVENT_DETAILS,
    JOB_ID_SEND_DAILY_DIGESTS,
    JOB_ID_SYNC_FIENTA_ORGANIZERS,
    JOB_LABEL_DEDUP_PASS,
    JOB_LABEL_HOURLY_INGEST,
    JOB_LABEL_ORGANIZER_SYNC,
    LLM_PASS_INTERVAL_HOURS,
    ORGANIZER_SYNC_HOUR,
    ORGANIZER_SYNC_MINUTE,
    REFETCH_HOUR,
    REFETCH_MINUTE,
    SCHEDULER_DAY_OF_WEEK_SUNDAY,
)
from app.constants.log_events import (
    LOG_EVENT_JOB_RUN,
    LOG_STATUS_ERROR,
    LOG_STATUS_OK,
)
from app.constants.promotions import PROMOTION_COUNTER_FLUSH_SECONDS, PROMOTION_SWEEP_SECONDS
from app.db import run_in_session
from app.email.digest import send_daily_digests
from app.ingestion.jobs import (
    backfill_publisher_ids_job,
    classify_pending_drained,
    dedup_pass_drained,
    geocode_pending_job,
    ingest_all_enabled,
    publish_pending_job,
    refetch_event_details_job,
)
from app.ingestion.organizer_sync import sync_fienta_organizers
from app.promotions.counters import flush as flush_promotion_counters
from app.promotions.sweep import sweep_promotions
from app.ranking.daily_feed import build_daily_feeds

log = logging.getLogger(__name__)


def _scheduled(
    label: str, run: Callable[[], Awaitable[object]]
) -> Callable[[], Awaitable[None]]:
    """Wrap a job for APScheduler: log the summary, swallow + log failures.

    Scheduled jobs must never raise (the scheduler would only log a bare
    traceback); admin-triggered runs of the same jobs go through
    routers.utils.admin.run_admin_job (which converts failures to 500s) or, for the
    /admin/pipeline job triggers (issue #159), stream_admin_job (which
    streams a status="error" NDJSON line instead, since headers are already
    sent by the time a streamed job can fail).
    """

    async def _job() -> None:
        start = time.monotonic()
        try:
            summary = await run()
            log.info(
                "%s completed: %s",
                label,
                summary,
                extra={
                    "event": LOG_EVENT_JOB_RUN,
                    "job": label,
                    "status": LOG_STATUS_OK,
                    "duration_ms": round((time.monotonic() - start) * MS_PER_SECOND),
                },
            )
        except Exception:
            log.exception(
                "%s failed",
                label,
                extra={
                    "event": LOG_EVENT_JOB_RUN,
                    "job": label,
                    "status": LOG_STATUS_ERROR,
                    "duration_ms": round((time.monotonic() - start) * MS_PER_SECOND),
                },
            )

    return _job


def _in_session(
    func: Callable[..., Awaitable[dict]], *, commit: bool
) -> Callable[[], Awaitable[dict]]:
    """Bind a DB-scoped job function to the shared ``run_in_session`` runner
    (app/db.py) so _scheduled's wrapper can call it with no arguments."""

    async def _run() -> dict:
        return await run_in_session(func, commit=commit)

    return _run


_run_organizer_sync = _scheduled(
    JOB_LABEL_ORGANIZER_SYNC, _in_session(sync_fienta_organizers, commit=True)
)
_run_cleanup = _scheduled(
    JOB_ID_CLEANUP_STALE_DATA, _in_session(cleanup_stale_data, commit=True)
)
_run_ingest_all = _scheduled(JOB_LABEL_HOURLY_INGEST, ingest_all_enabled)
_run_dedup_pass = _scheduled(JOB_LABEL_DEDUP_PASS, dedup_pass_drained)
_run_classify_pending = _scheduled(JOB_ID_CLASSIFY_PENDING, classify_pending_drained)
_run_publish_pending = _scheduled(JOB_ID_PUBLISH_PENDING, publish_pending_job)
_run_geocode_pending = _scheduled(JOB_ID_GEOCODE_PENDING, geocode_pending_job)
_run_backfill_publisher_ids = _scheduled(
    JOB_ID_BACKFILL_PUBLISHER_IDS, backfill_publisher_ids_job
)
_run_refetch_details = _scheduled(
    JOB_ID_REFETCH_EVENT_DETAILS, refetch_event_details_job
)
# build_daily_feeds and send_daily_digests commit internally / send only.
_run_build_daily_feeds = _scheduled(
    JOB_ID_BUILD_DAILY_FEEDS, _in_session(build_daily_feeds, commit=False)
)
_run_send_daily_digests = _scheduled(
    JOB_ID_SEND_DAILY_DIGESTS, _in_session(send_daily_digests, commit=False)
)
# expire_stale_claims commits internally (#421 — its expiry-notification
# fan-out must only see durably expired rows, mirrors build_daily_feeds above).
_run_expire_stale_claims = _scheduled(
    JOB_ID_EXPIRE_STALE_CLAIMS, _in_session(expire_stale_claims, commit=False)
)
# Promotion delivery counters (#606) flush as one bulk upsert.
_run_flush_promotion_counters = _scheduled(
    JOB_ID_FLUSH_PROMOTION_COUNTERS, _in_session(flush_promotion_counters, commit=True)
)
# Automatic Promotion void/end sweep (#602) commits internally, then emails.
_run_sweep_promotions = _scheduled(
    JOB_ID_SWEEP_PROMOTIONS, _in_session(sweep_promotions, commit=False)
)


def _register_scheduled_jobs(scheduler: AsyncIOScheduler) -> None:
    """Wire the full cron schedule."""
    # Organizer discovery — weekly Sunday at ORGANIZER_SYNC_HOUR (never hour 3: it repeats on fall-back day, #633)
    scheduler.add_job(
        _run_organizer_sync,
        trigger="cron",
        day_of_week=SCHEDULER_DAY_OF_WEEK_SUNDAY,
        hour=ORGANIZER_SYNC_HOUR,
        minute=ORGANIZER_SYNC_MINUTE,
        id=JOB_ID_SYNC_FIENTA_ORGANIZERS,
        replace_existing=True,
    )

    # Data retention cleanup — weekly Sunday at CLEANUP_HOUR (after organizer sync, off-peak)
    scheduler.add_job(
        _run_cleanup,
        trigger="cron",
        day_of_week=SCHEDULER_DAY_OF_WEEK_SUNDAY,
        hour=CLEANUP_HOUR,
        minute=CLEANUP_MINUTE,
        id=JOB_ID_CLEANUP_STALE_DATA,
        replace_existing=True,
    )

    # Hourly ingestion of all enabled sources
    scheduler.add_job(
        _run_ingest_all,
        trigger="interval",
        hours=INGEST_INTERVAL_HOURS,
        id=JOB_ID_INGEST_ALL_SOURCES,
        replace_existing=True,
    )

    # Every LLM_PASS_INTERVAL_HOURS: dedup pass + classify pending
    scheduler.add_job(
        _run_dedup_pass,
        trigger="interval",
        hours=LLM_PASS_INTERVAL_HOURS,
        id=JOB_ID_DEDUP_PASS,
        replace_existing=True,
    )
    scheduler.add_job(
        _run_classify_pending,
        trigger="interval",
        hours=LLM_PASS_INTERVAL_HOURS,
        id=JOB_ID_CLASSIFY_PENDING,
        replace_existing=True,
    )
    scheduler.add_job(
        _run_publish_pending,
        trigger="interval",
        hours=LLM_PASS_INTERVAL_HOURS,
        id=JOB_ID_PUBLISH_PENDING,
        replace_existing=True,
    )
    scheduler.add_job(
        _run_geocode_pending,
        trigger="interval",
        hours=LLM_PASS_INTERVAL_HOURS,
        id=JOB_ID_GEOCODE_PENDING,
        replace_existing=True,
    )
    scheduler.add_job(
        _run_backfill_publisher_ids,
        trigger="interval",
        hours=LLM_PASS_INTERVAL_HOURS,
        id=JOB_ID_BACKFILL_PUBLISHER_IDS,
        replace_existing=True,
    )
    # Daily at REFETCH_HOUR: re-fetch every future event's detail page and reconcile
    # venue/address/coords/price against the source (after hourly ingest, before
    # the feed build). A coord NULLed here on an address change is repaired
    # by the next geocode_pending interval pass — coords aren't a publish gate.
    scheduler.add_job(
        _run_refetch_details,
        trigger="cron",
        hour=REFETCH_HOUR,
        minute=REFETCH_MINUTE,
        id=JOB_ID_REFETCH_EVENT_DETAILS,
        replace_existing=True,
    )
    # Daily at FEED_BUILD_HOUR: build personalized feeds for all users
    scheduler.add_job(
        _run_build_daily_feeds,
        trigger="cron",
        hour=FEED_BUILD_HOUR,
        minute=FEED_BUILD_MINUTE,
        id=JOB_ID_BUILD_DAILY_FEEDS,
        replace_existing=True,
    )
    # Daily at DIGEST_SEND_HOUR: send digest emails to opted-in users (after feeds are built)
    scheduler.add_job(
        _run_send_daily_digests,
        trigger="cron",
        hour=DIGEST_SEND_HOUR,
        minute=DIGEST_SEND_MINUTE,
        id=JOB_ID_SEND_DAILY_DIGESTS,
        replace_existing=True,
    )
    # Every minute: flush the in-process Promotion delivery counters (#606).
    scheduler.add_job(
        _run_flush_promotion_counters,
        trigger="interval",
        seconds=PROMOTION_COUNTER_FLUSH_SECONDS,
        id=JOB_ID_FLUSH_PROMOTION_COUNTERS,
        replace_existing=True,
    )
    # Every minute: void unpaid Promotions at their start date, end paid ones
    # whose event was cancelled or whose claim was revoked (#602).
    scheduler.add_job(
        _run_sweep_promotions,
        trigger="interval",
        seconds=PROMOTION_SWEEP_SECONDS,
        id=JOB_ID_SWEEP_PROMOTIONS,
        replace_existing=True,
    )
    # Daily at EXPIRE_STALE_CLAIMS_HOUR: expire a pending automated-mechanism claim
    # abandoned for CLAIM_EXPIRY_DAYS (#413) — between the refetch and the feed build.
    scheduler.add_job(
        _run_expire_stale_claims,
        trigger="cron",
        hour=EXPIRE_STALE_CLAIMS_HOUR,
        minute=EXPIRE_STALE_CLAIMS_MINUTE,
        id=JOB_ID_EXPIRE_STALE_CLAIMS,
        replace_existing=True,
    )


def start_scheduler() -> AsyncIOScheduler | None:
    """Construct, wire and start the embedded scheduler, or return None when the
    development-only ENABLE_SCHEDULER kill switch is off.

    Off is for throwaway environments such as local development: the
    schedule drives real HTTP scrapes of live third-party sites, real LLM calls,
    and real digest email, and `uvicorn --reload` left running overnight arms all
    of it. Every job here also has a manual POST /admin/* trigger, so nothing
    becomes unreachable; and with no persistent jobstore there is no missed-run
    backlog to catch up on afterwards.

    Outside development the flag is ignored and the scheduler starts anyway — a
    stray env var must never be able to stop the pipeline in production. Same
    double-gate reasoning as auth/utils.py::require_configured_secret.
    """
    if not settings.ENABLE_SCHEDULER:
        if settings.APP_ENV == APP_ENV_DEVELOPMENT:
            log.warning(
                "ENABLE_SCHEDULER=false — the embedded scheduler is NOT running. "
                "No ingest, dedup, classify, publish, geocode, refetch, feed "
                "build, digest or cleanup will fire on a schedule; trigger them "
                "manually via POST /admin/*."
            )
            return None
        log.warning(
            "ENABLE_SCHEDULER=false ignored outside development (APP_ENV=%r) — "
            "starting the scheduler anyway",
            settings.APP_ENV,
        )

    scheduler = AsyncIOScheduler(timezone=TALLINN_TZ_NAME)
    _register_scheduled_jobs(scheduler)
    scheduler.start()
    return scheduler
