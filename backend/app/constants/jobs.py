"""Scheduler: job IDs, labels, and the hour/minute each scheduled job runs."""

from app.constants.admin import (
    ADMIN_ACTION_CLASSIFY,
    ADMIN_ACTION_INGEST,
    ADMIN_ACTION_SEND_DIGESTS,
)

# Scheduler cadence
ORGANIZER_SYNC_HOUR = 2  # weekly on Sunday; never hour 3 (it repeats on fall-back day, #633)
ORGANIZER_SYNC_MINUTE = 0
CLEANUP_HOUR = 2  # weekly on Sunday, after ORGANIZER_SYNC_HOUR:ORGANIZER_SYNC_MINUTE
CLEANUP_MINUTE = 30
INGEST_INTERVAL_HOURS = 1
LLM_PASS_INTERVAL_HOURS = 6  # dedup/classify/publish/geocode
REFETCH_HOUR = 4  # daily, before FEED_BUILD_HOUR
REFETCH_MINUTE = 30
FEED_BUILD_HOUR = 6  # daily
FEED_BUILD_MINUTE = 0
# Daily, between REFETCH_HOUR and FEED_BUILD_HOUR — cheap DB-only sweep (#413),
# off-peak like every other cron entry.
EXPIRE_STALE_CLAIMS_HOUR = 5
EXPIRE_STALE_CLAIMS_MINUTE = 0

DIGEST_SEND_HOUR = 7  # daily, after FEED_BUILD_HOUR's build_daily_feeds
DIGEST_SEND_MINUTE = 0

# Sub-stages that are also standalone triggers with their own single-flight
# guard (issue #160) — held for pipeline/run's whole duration too, or a
# standalone ingest/classify/send-digests click mid-pipeline would run
# concurrently with the pipeline's own execution of that same stage.
PIPELINE_RUN_OVERLAPPING_LOCK_KEYS = (
    ADMIN_ACTION_INGEST,
    ADMIN_ACTION_CLASSIFY,
    ADMIN_ACTION_SEND_DIGESTS,
)

# APScheduler job ids (app/scheduler.py::_register_scheduled_jobs) — also reasoned
# about in /admin/pipeline/run, so a typo in one of
# the two call sites that share a string (the log label passed to _scheduled
# and the id= kwarg on scheduler.add_job) would silently misregister a job.
JOB_ID_SYNC_FIENTA_ORGANIZERS = "sync_fienta_organizers"
JOB_ID_CLEANUP_STALE_DATA = "cleanup_stale_data"
JOB_ID_INGEST_ALL_SOURCES = "ingest_all_sources"
JOB_ID_DEDUP_PASS = "dedup_pass"
JOB_ID_CLASSIFY_PENDING = "classify_pending"
JOB_ID_PUBLISH_PENDING = "publish_pending"
JOB_ID_GEOCODE_PENDING = "geocode_pending"
JOB_ID_BACKFILL_PUBLISHER_IDS = "backfill_publisher_ids"
JOB_ID_REFETCH_EVENT_DETAILS = "refetch_event_details"
JOB_ID_BUILD_DAILY_FEEDS = "build_daily_feeds"
JOB_ID_SEND_DAILY_DIGESTS = "send_daily_digests"
JOB_ID_EXPIRE_STALE_CLAIMS = "expire_stale_claims"
JOB_ID_FLUSH_PROMOTION_COUNTERS = "flush_promotion_counters"
JOB_ID_SWEEP_PROMOTIONS = "sweep_promotions"

# Per-minute jobs whose successful job_run lines are not shipped to the log
# drain (73% of volume, ~1 ms per run, issue #637). Error runs still ship, so
# the "Scheduled job failed" monitor is unaffected. Console logs keep them.
LOG_SHIP_SUPPRESS_OK_JOBS: frozenset[str] = frozenset(
    {JOB_ID_FLUSH_PROMOTION_COUNTERS, JOB_ID_SWEEP_PROMOTIONS}
)

# Scheduler job labels whose runtime string is load-bearing: the "hourly
# ingest" value is matched verbatim by the Stale ingest log query, so these keep their historical spelling rather than reusing JOB_ID_*.
JOB_LABEL_HOURLY_INGEST = "hourly ingest"
JOB_LABEL_DEDUP_PASS = "dedup pass"
JOB_LABEL_ORGANIZER_SYNC = "organizer sync"
JOB_LABEL_DEDUP_DRAIN = "dedup"
SCHEDULER_DAY_OF_WEEK_SUNDAY = "sun"
