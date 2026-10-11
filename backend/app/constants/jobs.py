"""Scheduler: job IDs, labels, and the hour/minute each scheduled job runs."""

from app.constants.admin import (
    ADMIN_ACTION_CLASSIFY,
    ADMIN_ACTION_INGEST,
    ADMIN_ACTION_SEND_DIGESTS,
)

# Scheduler cadence (see docs/backend-ops.md "Scheduled Jobs" for the full cron schedule)
ORGANIZER_SYNC_HOUR = 3  # weekly Sunday 03:00 Europe/Tallinn
ORGANIZER_SYNC_MINUTE = 0
CLEANUP_HOUR = 3  # weekly Sunday 03:30 Europe/Tallinn, after organizer sync
CLEANUP_MINUTE = 30
INGEST_INTERVAL_HOURS = 1
LLM_PASS_INTERVAL_HOURS = 6  # dedup/classify/publish/geocode
REFETCH_HOUR = 4  # daily 04:30 Europe/Tallinn, before the 06:00 feed build
REFETCH_MINUTE = 30
FEED_BUILD_HOUR = 6  # daily 06:00 Europe/Tallinn
FEED_BUILD_MINUTE = 0
# Daily 05:00 Europe/Tallinn, between the 04:30 refetch and the 06:00 feed
# build — cheap DB-only sweep (#413), off-peak like every other cron entry.
EXPIRE_STALE_CLAIMS_HOUR = 5
EXPIRE_STALE_CLAIMS_MINUTE = 0

DIGEST_SEND_HOUR = 7  # 07:00 Europe/Tallinn, one hour after build_daily_feeds
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

# APScheduler job ids (app/main.py::_register_scheduled_jobs) — also reasoned
# about in docs/backend-ops.md and /admin/pipeline/run, so a typo in one of
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

# Scheduler job labels whose runtime string is load-bearing: the "hourly
# ingest" value is matched verbatim by an Axiom monitor (docs/observability.md
# #3b), so these keep their historical spelling rather than reusing JOB_ID_*.
JOB_LABEL_HOURLY_INGEST = "hourly ingest"
JOB_LABEL_DEDUP_PASS = "dedup pass"
JOB_LABEL_ORGANIZER_SYNC = "organizer sync"
JOB_LABEL_DEDUP_DRAIN = "dedup"
SCHEDULER_DAY_OF_WEEK_SUNDAY = "sun"
