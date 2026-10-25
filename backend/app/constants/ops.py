"""Operations: DB pool, logging config and shipping, retention windows, alembic."""

import logging

# Hostnames treated as "local" by the dev/prod-DB startup sanity check
# (app/main.py's lifespan) — a DATABASE_URL host outside this set while
# APP_ENV=development suggests a misconfigured env var pointed at a real
# database, logged at ERROR rather than silently proceeding. "db" is the
# Postgres service name in .devcontainer/docker-compose.yml.
DEV_DB_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "db"})

# Recycle pooled DB connections older than this many seconds. Set below Neon's
# free-tier idle/auto-suspend window (~5 min) so we never hand out a connection
# the server has already dropped. Works together with pool_pre_ping.
DB_POOL_RECYCLE_SECONDS = 280

# uvicorn's logging.access record carries a positional args tuple
# (client_addr, method, path, http_version, status) — app/logging_config.py's
# _AccessPathSuppressFilter reads path/status off it. Named so a future
# uvicorn version's arg-count change is at least a visible constant, not a
# bare index.
UVICORN_ACCESS_STATUS_ARG_INDEX = 4
# Same args tuple, the path slot — app/logging_config.py's
# _AccessPathStripFilter strips the query string in place, so this index (and
# its :N / N: slice derivatives) must stay consistent with
# UVICORN_ACCESS_STATUS_ARG_INDEX above.
UVICORN_ACCESS_PATH_ARG_INDEX = 2

# app/db.py::assert_schema_at_head — the 0030/admin_actions incident: code
# shipped ahead of a DB still on an older migration, so every admin action
# 500'd instead of failing at boot. Same text logged at ERROR (production,
# then raised) or WARNING (development, boot continues) — see LOG_EVENT_SCHEMA_DRIFT.
ERROR_SCHEMA_DRIFT = (
    "Database schema drift: DB is at revision {db_revision!r}, code expects "
    "head {head_revision!r}. Run `alembic upgrade head`."
)

# Logging — configure_logging() in app.logging_config wires these into the root
# logger. Format/date strings render UTC ISO 8601 timestamps on every line (app,
# uvicorn, and SQL echo alike).
LOG_LEVEL_DEFAULT = "INFO"
LOG_FORMAT_TEXT = "%(asctime)s.%(msecs)03dZ %(levelname)-8s %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
LOG_DIR_NAME = "logs"
LOG_FILE_NAME = "app.log"
LOG_FILE_MAX_BYTES = 5 * 1024 * 1024  # 5 MB per file
LOG_FILE_BACKUP_COUNT = 5  # ~25 MB total dev history
LOG_SHIP_TIMEOUT_SECONDS = 5.0
LOG_SHIP_QUEUE_MAXSIZE = 10_000  # bounded; drop-newest if shipping stalls
LOG_SHIP_BATCH_SIZE = 100  # records per POST; a full buffer flushes immediately
LOG_SHIP_FLUSH_INTERVAL_SECONDS = 2.0  # a partial buffer is flushed at least this often
# Loggers configured by frameworks/libraries before configure_logging() runs —
# stripped of their own handlers and re-pointed at the root logger so every
# line (app, uvicorn, SQL echo) shares the same timestamped format.
SQLALCHEMY_ENGINE_LOGGER_NAME = "sqlalchemy.engine"
UVICORN_ACCESS_LOGGER = "uvicorn.access"
LOG_FRAMEWORK_LOGGER_NAMES: tuple[str, ...] = (
    "uvicorn",
    "uvicorn.error",
    UVICORN_ACCESS_LOGGER,
    SQLALCHEMY_ENGINE_LOGGER_NAME,
)
# HTTP client loggers pinned to WARNING: their per-request INFO/DEBUG lines are
# noise, and — critically — shipping one would make the ship POST itself emit a
# log that gets shipped, a self-amplifying loop. WARNING severs it at any root level.
LOG_QUIET_LOGGER_NAMES: tuple[str, ...] = (
    "httpx",
    "httpcore",
    # Two INFO lines per job run that duplicate the structured job_run line
    # from app/main.py::_scheduled. Its ERROR "Job ... raised an exception"
    # still ships.
    "apscheduler.executors.default",
)
# uvicorn.access paths never worth shipping to the log drain. Render's platform
# health check hits GET /health every few seconds; shipping each is pure noise.
# Suppressed on the shipping QueueHandler only — these lines still reach Render's
# own console logs. Extend this set to silence other high-frequency probe paths.
LOG_SHIP_SUPPRESS_ACCESS_PATHS: frozenset[str] = frozenset({"/health"})
# Standard LogRecord attribute names. JsonLogFormatter promotes every record
# attribute NOT in this set — i.e. anything a call site passed via `extra={...}` —
# to a top-level JSON key, so Axiom monitors can filter on structured fields
# (event/job/status/duration_ms) instead of regex-parsing the free-text message.
# Derived from a sample record so it tracks the running Python version (3.12 adds
# taskName); "message"/"asctime" are set during formatting, not on a fresh record.
LOG_RECORD_RESERVED_ATTRS: frozenset[str] = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime", "color_message"}

# app/db.py::assert_schema_at_head — the migrations directory name under
# backend/, pinned absolute so the alembic-head guard doesn't depend on cwd.
ALEMBIC_DIR_NAME = "alembic"

# Data retention — app/cleanup.py::cleanup_stale_data(), weekly Sun 03:30 EET.
# These prune satellite/audit tables only; `events` rows are never deleted.
MAGIC_LINK_RETENTION_DAYS = 7  # expired/used auth_magic_links rows
LLM_CALLS_RETENTION_DAYS = 90  # also the dedup/classification cache window
# Trade-off: a one-off forensic/backfill script reading raw_events.payload
# cannot recover a row pruned past this window — any future script needing
# raw payloads must run within 90 days of ingest, or this constant must be
# raised first.
RAW_EVENTS_RETENTION_DAYS = 90
INGESTION_RUNS_RETENTION_DAYS = 90
RAW_INBOUND_EMAILS_RETENTION_DAYS = 90
DAILY_FEEDS_RETENTION_DAYS = 30
# Unverified users/organizers — a row inserted on an unauthenticated
# POST .../request-link before the address is proven reachable (see
# docs/security.md "Auth", email verification gate). Retained this long in
# case a slow/late click on a still-valid link would otherwise orphan it, then pruned so an
# address nobody ever proved they own isn't retained indefinitely.
UNVERIFIED_ACCOUNT_RETENTION_DAYS = 30

# app/db.py::mask_db_url — redacts the password in a DB URL
# ("user:pass@host" -> "user:***@host") for safe logging.
MASK_DB_URL_PASSWORD_RE = r":[^@/]+@"
