import logging
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from fastapi import FastAPI, Request, Response, status
from starlette.middleware.base import RequestResponseEndpoint
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.datastructures import Headers, MutableHeaders
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config import settings
from app._generated.shared_constants import APP_VERSION
from app.constants.core import APP_ENV_DEVELOPMENT, MS_PER_SECOND, TALLINN_TZ_NAME
from app.constants.http import (
    ASGI_MESSAGE_TYPE_REQUEST,
    ASGI_MESSAGE_TYPE_RESPONSE_BODY,
    ASGI_MESSAGE_TYPE_RESPONSE_START,
    ASGI_SCOPE_TYPE_HTTP,
    HEADER_HOST,
    HEADER_ORIGIN,
)
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
    LOG_EVENT_HOST_REJECTED,
    LOG_EVENT_JOB_RUN,
    LOG_STATUS_ERROR,
    LOG_STATUS_OK,
)
from app.constants.ops import DEV_DB_LOCAL_HOSTS
from app.constants.security import (
    CORS_ALLOWED_HEADERS,
    CORS_ALLOWED_METHODS,
    CSRF_UNSAFE_METHODS,
    DEV_CORS_ORIGINS_DEFAULT,
    ERROR_CSRF_ORIGIN_MISMATCH,
    HOST_CHECK_EXEMPT_PATHS,
    HSTS_HEADER_NAME,
    HSTS_HEADER_VALUE,
    MAX_REQUEST_BODY_BYTES,
    SECURITY_HEADERS,
    TRUSTED_HOST_REJECT_BODY,
)
from app.claims.lifecycle import expire_stale_claims
from app.cleanup import cleanup_stale_data
from app.db import AsyncSessionLocal, assert_schema_at_head, engine
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
from app.logging_config import configure_logging, shutdown_log_shipping
from app.ranking.score import build_daily_feeds
from app.rate_limit import client_key, limiter, rate_limit_exceeded_handler
from app.routers.admin import router as admin_router
from app.routers.admin_auth import router as admin_auth_router
from app.routers.admin_claims import router as admin_claims_router
from app.routers.admin_events import router as admin_events_router
from app.routers.admin_jobs import router as admin_jobs_router
from app.routers.admin_overview import router as admin_overview_router
from app.routers.admin_promotion_requests import router as admin_promotion_requests_router
from app.routers.admin_promotions import router as admin_promotions_router
from app.routers.admin_reports import router as admin_reports_router
from app.routers.admin_submissions import router as admin_submissions_router
from app.routers.auth import router as auth_router
from app.routers.browse import router as browse_router
from app.routers.contact import router as contact_router
from app.routers.events import router as events_router
from app.routers.feed import router as feed_router
from app.routers.feedback import router as feedback_router
from app.routers.onboarding import router as onboarding_router
from app.routers.organizer_auth import router as organizer_auth_router
from app.routers.organizer_claim_edits import router as organizer_claim_edits_router
from app.routers.organizer_claims import router as organizer_claims_router
from app.routers.organizer_contact import router as organizer_contact_router
from app.routers.organizer_events import router as organizer_events_router
from app.routers.organizer_profile import router as organizer_profile_router
from app.routers.organizer_promotions import router as organizer_promotions_router
from app.routers.organizer_venues import router as organizer_venues_router
from app.routers.public import router as public_router
from app.routers.reports import router as reports_router
from app.routers.settings import router as settings_router
from app.email.consent import reset_consent_for_wording_change
from app.routers.unsubscribe import router as unsubscribe_router
from app.db import run_in_session
from app.constants.promotions import PROMOTION_COUNTER_FLUSH_SECONDS, PROMOTION_SWEEP_SECONDS
from app.promotions.counters import flush as flush_promotion_counters
from app.promotions.sweep import sweep_promotions
from app.routers.organizer_promotion_checkout import router as organizer_promotion_checkout_router
from app.routers.stripe_webhook import router as stripe_webhook_router
from app.routers.webhooks import router as webhooks_router
from app.seeds import seed_personas, seed_publishers, seed_sources

# uvicorn configures its own logging during Config.load(), before importing this
# module — calling configure_logging() here runs last and wins, so every logger
# (app, uvicorn, SQL echo) shares one timestamped format.
configure_logging()

log = logging.getLogger(__name__)


def _scheduled(
    label: str, run: Callable[[], Awaitable[object]]
) -> Callable[[], Awaitable[None]]:
    """Wrap a job for APScheduler: log the summary, swallow + log failures.

    Scheduled jobs must never raise (the scheduler would only log a bare
    traceback); admin-triggered runs of the same jobs go through
    routers.utils.run_admin_job (which converts failures to 500s) or, for the
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
    (routers/utils.py) so _scheduled's wrapper can call it with no arguments."""

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
    """Wire the full cron schedule (see docs/backend-ops.md "Scheduled Jobs" for the cadence)."""
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


class CsrfOriginCheckMiddleware:
    """Reject a mutating request whose Origin header doesn't match a trusted
    origin, with 403.

    Second CSRF layer behind SameSite=Strict now that #26 has moved session
    auth to a cookie — a foreign page's fetch/form submission carries the
    cookie automatically, which a Bearer header never did.

    A request with no Origin header is let through — browsers omit it on
    simple/no-CORS navigations for some methods, and server-to-server callers
    (the Resend inbound-mail webhook, RFC 8058 one-click unsubscribe POSTs
    from mail clients) never send one either. Non-mutating methods (GET,
    HEAD, OPTIONS, ...) are never checked.
    """

    def __init__(self, app: ASGIApp, trusted_origins: frozenset[str]) -> None:
        self.app = app
        self.trusted_origins = trusted_origins

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            {"detail": ERROR_CSRF_ORIGIN_MISMATCH},
            status_code=status.HTTP_403_FORBIDDEN,
        )
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != ASGI_SCOPE_TYPE_HTTP
            or scope["method"] not in CSRF_UNSAFE_METHODS
        ):
            await self.app(scope, receive, send)
            return

        origin = Headers(scope=scope).get(HEADER_ORIGIN)
        if origin is not None and origin not in self.trusted_origins:
            await self._reject(scope, receive, send)
            return

        await self.app(scope, receive, send)


class HostCheckMiddleware:
    """TrustedHostMiddleware with path exemptions — Render's health probe hits
    this process over the private network, so its Host header is the
    instance's internal address, not BACKEND_URL's hostname. That IP rotates
    per deploy and Starlette's allowed_hosts takes no CIDR, so the probe path
    is exempted instead."""

    def __init__(
        self, app: ASGIApp, allowed_hosts: list[str], exempt_paths: frozenset[str]
    ) -> None:
        self._app = app
        self._guarded = TrustedHostMiddleware(app, allowed_hosts=allowed_hosts)
        self._exempt_paths = exempt_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == ASGI_SCOPE_TYPE_HTTP
            and scope.get("path") in self._exempt_paths
        ):
            await self._app(scope, receive, send)
            return

        saw_400 = False
        rejected = False
        # This middleware is registered outside (wraps around) the
        # add_security_headers layer, so TrustedHostMiddleware's own 400
        # response — built and sent directly, without ever calling
        # self.app — never passes through that layer (L-1 in the OWASP
        # audit). A pass-through response (self.app called, valid host)
        # already carries the headers by the time it reaches here, since
        # add_security_headers sits further in; MutableHeaders.__setitem__
        # replaces rather than duplicates an existing value, so setting them
        # unconditionally on every 400 is safe either way. The response.start
        # message is held back until response.body arrives (TrustedHost's
        # rejection is always exactly these two messages) so the body can
        # still be inspected for the log line below before headers are sent.
        pending_start: Message | None = None

        async def _send(message: Message) -> None:
            nonlocal saw_400, rejected, pending_start
            if message["type"] == ASGI_MESSAGE_TYPE_RESPONSE_START:
                saw_400 = message["status"] == status.HTTP_400_BAD_REQUEST
                if saw_400:
                    pending_start = message
                    return
            elif message["type"] == ASGI_MESSAGE_TYPE_RESPONSE_BODY:
                if saw_400 and pending_start is not None:
                    if TRUSTED_HOST_REJECT_BODY in message.get("body", b""):
                        rejected = True
                    headers = MutableHeaders(raw=pending_start["headers"])
                    for name, value in SECURITY_HEADERS.items():
                        headers[name] = value
                    await send(pending_start)
                    pending_start = None
                saw_400 = False
            await send(message)

        await self._guarded(scope, receive, _send)
        if rejected:
            log.warning(
                "Host header rejected: host=%r path=%r client=%r",
                Headers(scope=scope).get(HEADER_HOST),
                scope.get("path"),
                client_key(Request(scope)),
                extra={"event": LOG_EVENT_HOST_REJECTED},
            )


class _BodyTooLarge(Exception):
    """Internal sentinel — never escapes MaxBodySizeMiddleware.__call__."""


class MaxBodySizeMiddleware:
    """Reject a request body over MAX_REQUEST_BODY_BYTES with 413.

    Nothing else in the stack caps request size — IMAGE_UPLOAD_MAX_BYTES only
    bounds what the upload handler reads after Starlette has already received
    and spooled the full multipart body. A ``Content-Length`` request is
    rejected up front, before the body is read at all; a chunked request (no
    ``Content-Length``) is rejected mid-stream once the running total crosses
    the limit, via the wrapped ``receive`` callable.

    This sends the 413 response itself (an ASGI ``Response.__call__``) rather
    than raising ``HTTPException`` — Starlette places every ``add_middleware``
    entry *outside* its internal ``ExceptionMiddleware`` (which is innermost,
    right next to the router), so an ``HTTPException`` raised from here would
    never reach it and would surface as a generic 500 from
    ``ServerErrorMiddleware`` instead of the intended 413.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        # This middleware is registered outside (wraps around) the
        # add_security_headers layer, so a response built here never passes
        # through it — set the headers directly, or this 413 ships without
        # CSP/nosniff/etc. (L-1 in the OWASP audit).
        response = JSONResponse(
            {"detail": f"Request body exceeds {self.max_bytes} bytes."},
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            headers=SECURITY_HEADERS,
        )
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != ASGI_SCOPE_TYPE_HTTP:
            await self.app(scope, receive, send)
            return

        content_length = Headers(scope=scope).get("content-length")
        if content_length is not None:
            try:
                too_large = int(content_length) > self.max_bytes
            except ValueError:
                too_large = False
            if too_large:
                await self._reject(scope, receive, send)
                return

        seen = 0

        async def limited_receive() -> Message:
            nonlocal seen
            message = await receive()
            if message["type"] == ASGI_MESSAGE_TYPE_REQUEST:
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    raise _BodyTooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLarge:
            await self._reject(scope, receive, send)


def _check_dev_database_host() -> None:
    """Log an ERROR if APP_ENV=development but DATABASE_URL points at a
    non-local host — likely a stray/never-overridden env var pointed at a
    real (staging/prod) database, which combined with ALLOW_INSECURE_DEV
    would leave that real database's admin surface unprotected (see M1,
    require_configured_secret)."""
    if settings.APP_ENV != APP_ENV_DEVELOPMENT:
        return
    host = urlsplit(settings.DATABASE_URL).hostname
    if host and host not in DEV_DB_LOCAL_HOSTS:
        log.error(
            "APP_ENV=development but DATABASE_URL host=%r is not local — "
            "this looks like a misconfigured environment pointed at a real database",
            host,
        )


def _resolve_allowed_hosts() -> list[str]:
    """Host allowlist for HostCheckMiddleware: Render's auto-injected public
    hostname plus BACKEND_URL's. Local/dev hostnames are dropped — outside
    development they mean the env var was never set, and installing the
    middleware on that allowlist 400s all public traffic (the 0.1.6 outage).
    An empty result means the caller skips the middleware entirely: Host
    validation is cache-poisoning hardening only, so degrading it beats
    taking the API down."""
    candidates = [
        settings.RENDER_EXTERNAL_HOSTNAME.strip().lower(),
        (urlsplit(settings.BACKEND_URL).hostname or "").lower(),
    ]
    hosts: list[str] = []
    for host in candidates:
        if host and host not in DEV_DB_LOCAL_HOSTS and host not in hosts:
            hosts.append(host)
    if not hosts:
        log.error(
            "Host allowlist could not be resolved (RENDER_EXTERNAL_HOSTNAME=%r, "
            "BACKEND_URL=%r both empty/local) — HostCheckMiddleware will NOT be "
            "installed; Host-header validation is disabled",
            settings.RENDER_EXTERNAL_HOSTNAME,
            settings.BACKEND_URL,
        )
    return hosts


def _start_scheduler() -> AsyncIOScheduler | None:
    """Construct, wire and start the embedded scheduler, or return None when the
    development-only ENABLE_SCHEDULER kill switch is off.

    Off is for throwaway environments (the dev container defaults to it): the
    schedule drives real HTTP scrapes of live third-party sites, real LLM calls,
    and real digest email, and `uvicorn --reload` left running overnight arms all
    of it. Every job here also has a manual POST /admin/* trigger, so nothing
    becomes unreachable; and with no persistent jobstore there is no missed-run
    backlog to catch up on afterwards.

    Outside development the flag is ignored and the scheduler starts anyway — a
    stray env var must never be able to stop the pipeline in production. Same
    double-gate reasoning as routers/utils.py::require_configured_secret.
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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    _check_dev_database_host()
    await assert_schema_at_head()
    async with AsyncSessionLocal() as db:
        await seed_sources(db)
        await seed_personas(db)
        await seed_publishers(db)
        # A material consent-wording bump resets stale consenters to off.
        await reset_consent_for_wording_change(db)
        await db.commit()

    scheduler = _start_scheduler()
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        try:
            await run_in_session(flush_promotion_counters, commit=True)
        except Exception:
            log.exception("promotion counter flush on shutdown failed")
        await engine.dispose()
        shutdown_log_shipping()


# Swagger UI / ReDoc load their JS/CSS from a CDN, which the restrictive
# default-src 'none' CSP (SECURITY_HEADERS, set on every response below) blocks —
# rather than carve out CDN exceptions in the policy, disable the docs routes
# outside development. docs/security.md already frames this as "a pure JSON API with no
# first-party HTML/script surface"; this makes that statement true everywhere.
_docs_enabled = settings.APP_ENV == APP_ENV_DEVELOPMENT
app = FastAPI(
    title="Event Radar API",
    version=APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
    # Swagger is served from :8000 but the session cookie is Path=/api and
    # belongs to the Vite dev server's origin (localhost:5173) — pointing
    # "Try it out" at this relative /api path instead of the bare backend
    # origin routes its requests through the Vite proxy (see vite.config.ts),
    # so the browser attaches the cookie automatically. See #28.
    servers=[{"url": "/api"}] if _docs_enabled else None,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    # Auth is now a Set-Cookie session (see #26 / docs/adr/0001), but
    # allow_credentials stays False deliberately: the cookie is scoped to this
    # API's own origin and only ever travels through the same-origin `/api`
    # proxy the SPA is served behind, never via a cross-origin
    # browser fetch/XHR — so credentialed CORS would only widen the attack
    # surface for no functional gain, regardless of what CORS_ORIGINS lists.
    allow_credentials=False,
    allow_methods=CORS_ALLOWED_METHODS,
    allow_headers=CORS_ALLOWED_HEADERS,
)

# CORS_ORIGINS now serves double duty — CORS (above) and CSRF trust (below).
# Widening it for one purpose widens the other too; a value added here to let a
# new frontend deployment through CORS also becomes a trusted CSRF origin.
#
# CORS_ORIGINS is sync: false in render.yaml, so an operator who forgets to set
# it in the Render dashboard silently keeps its dev default
# (settings.CORS_ORIGINS' literal default below) — SameSite=Strict means that
# default can't actually carry the session cookie cross-origin, but a
# permanently-trusted localhost CSRF origin in production is still the wrong
# shape for a config mistake to take. Dropped outside development so a
# forgotten CORS_ORIGINS degrades to "no CSRF-trusted origins" (fail closed)
# rather than "trust two hardcoded localhost ports" (fail open).
_csrf_trusted_origins = frozenset(settings.CORS_ORIGINS) | {settings.FRONTEND_URL}
if settings.APP_ENV != APP_ENV_DEVELOPMENT:
    _csrf_trusted_origins -= DEV_CORS_ORIGINS_DEFAULT
app.add_middleware(
    CsrfOriginCheckMiddleware,
    trusted_origins=_csrf_trusted_origins,
)


@app.middleware("http")
async def add_security_headers(
    request: Request, call_next: RequestResponseEndpoint
) -> Response:
    """Set CSP/nosniff/frame-ancestors/referrer-policy on every response — defense
    in depth against XSS and clickjacking. HSTS is added only in production, since
    it's only safe to advertise over HTTPS (Render terminates TLS in front of us;
    local dev runs over plain http://localhost)."""
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers[name] = value
    if settings.APP_ENV != APP_ENV_DEVELOPMENT:
        response.headers[HSTS_HEADER_NAME] = HSTS_HEADER_VALUE
    return response


# Starlette's add_middleware() prepends to user_middleware, so the LAST middleware
# registered ends up OUTERMOST (run first on the way in). This must be outermost —
# added after every other add_middleware()/@app.middleware() call above — so that
# scope["client"] is rewritten from the trusted X-Forwarded-For header *before*
# SlowAPIMiddleware (and the @limiter.limit decorators' get_remote_address calls)
# ever see request.client. Render terminates TLS and proxies every request through
# its routing layer, so request.client.host would otherwise be the proxy's address
# for every inbound connection, collapsing all clients into a single rate-limit
# bucket. trusted_hosts="*" is safe here: Render's web services are reachable only
# through its proxy, so any connection reaching this process is by definition from
# that trusted hop.
#
# DEPLOYMENT INVARIANT this depends on: trusted_hosts="*" means ANY peer that can
# open a TCP connection to this process gets its X-Forwarded-For header trusted
# verbatim (rate-limit bucketing and logged client IPs become spoofable by that
# peer). Render doesn't publish a stable proxy egress CIDR to pin trusted_hosts to
# instead, so this is safe only as long as the process is never reachable off of
# Render's proxy — e.g. it would break silently if the service were ever exposed
# directly (a public port, a misconfigured internal network, a non-Render host),
# or fronted by another CDN/proxy in addition to Render's. Re-derive this trade-off
# if the deployment topology changes.
#
# Registered before (i.e. wraps *inside*) ProxyHeadersMiddleware so a rejected
# oversized request still gets logged/rate-limited against its real client
# address rather than the raw proxy connection.
app.add_middleware(MaxBodySizeMiddleware, max_bytes=MAX_REQUEST_BODY_BYTES)

# Host header validation — nothing today builds an absolute URL from the
# request Host (FRONTEND_URL/BACKEND_URL are config, not derived from it), so
# impact is limited to intermediary cache-poisoning scenarios, but rejecting
# an unexpected Host outright is a one-line hardening. Skipped in development
# (no fixed BACKEND_URL host, e.g. localhost with a changing port in tests).
# /health is exempted (HOST_CHECK_EXEMPT_PATHS) — Render's health probe hits
# this process over the private network with the instance's internal address
# as Host, not BACKEND_URL's hostname. See _resolve_allowed_hosts() for the
# fail-open reasoning: an unresolvable allowlist skips this middleware
# entirely rather than 400ing all public traffic (the 0.1.6 outage).
#
# Registered before (i.e. wraps *inside*) ProxyHeadersMiddleware below so a
# rejected request still gets its real client IP resolved for the
# LOG_EVENT_HOST_REJECTED log line in HostCheckMiddleware.
_allowed_hosts = (
    _resolve_allowed_hosts() if settings.APP_ENV != APP_ENV_DEVELOPMENT else []
)
if _allowed_hosts:
    app.add_middleware(
        HostCheckMiddleware,
        allowed_hosts=_allowed_hosts,
        exempt_paths=HOST_CHECK_EXEMPT_PATHS,
    )
#
# HOP-COUNT ASSUMPTION: ProxyHeadersMiddleware itself trusts the *leftmost* XFF
# hop (attacker-controlled if forwarded verbatim), so app.rate_limit.client_key
# never trusts request.client. Production is a two-hop path — browser ->
# Cloudflare Pages Function proxy -> Render -> uvicorn — so the rightmost XFF
# entry Render's own proxy appends is always Cloudflare's egress address, not
# the visitor. client_key() instead prefers an edge-authenticated X-Client-IP
# (proven via X-Edge-Auth against settings.EDGE_SHARED_SECRET, set by the
# Cloudflare Function), falling back to rightmost-XFF only when that pair is
# absent or invalid — correct for a direct-to-Render caller with exactly one
# trusted hop. See docs/security.md and OWASP audit finding G-1.
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

app.include_router(admin_auth_router)
app.include_router(admin_claims_router)
app.include_router(admin_events_router)
app.include_router(admin_jobs_router)
app.include_router(admin_overview_router)
app.include_router(admin_promotion_requests_router)
app.include_router(admin_promotions_router)
app.include_router(admin_reports_router)
app.include_router(admin_router)
app.include_router(admin_submissions_router)
app.include_router(auth_router)
app.include_router(browse_router)
app.include_router(contact_router)
app.include_router(events_router)
app.include_router(feed_router)
app.include_router(feedback_router)
app.include_router(onboarding_router)
app.include_router(organizer_auth_router)
app.include_router(organizer_claim_edits_router)
app.include_router(organizer_claims_router)
app.include_router(organizer_contact_router)
app.include_router(organizer_events_router)
app.include_router(organizer_profile_router)
app.include_router(organizer_promotions_router)
app.include_router(organizer_venues_router)
app.include_router(public_router)
app.include_router(reports_router)
app.include_router(settings_router)
app.include_router(unsubscribe_router)
app.include_router(webhooks_router)
app.include_router(stripe_webhook_router)
app.include_router(organizer_promotion_checkout_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": APP_VERSION}
