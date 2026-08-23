import logging
import secrets
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from fastapi import FastAPI, HTTPException, Request, Response, status
from starlette.middleware.base import RequestResponseEndpoint
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.datastructures import Headers
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config import settings
from app.constants import (
    APP_ENV_DEVELOPMENT,
    APP_VERSION,
    ASGI_MESSAGE_TYPE_REQUEST,
    ASGI_MESSAGE_TYPE_RESPONSE_BODY,
    ASGI_MESSAGE_TYPE_RESPONSE_START,
    ASGI_SCOPE_TYPE_HTTP,
    CLEANUP_HOUR,
    CLEANUP_MINUTE,
    CORS_ALLOWED_HEADERS,
    CORS_ALLOWED_METHODS,
    CSRF_UNSAFE_METHODS,
    DEV_DB_LOCAL_HOSTS,
    DIGEST_SEND_HOUR,
    ERROR_INTERNAL_TICK_INVALID_TOKEN,
    FEED_BUILD_HOUR,
    FEED_BUILD_MINUTE,
    HOST_CHECK_EXEMPT_PATHS,
    HSTS_HEADER_NAME,
    HSTS_HEADER_VALUE,
    INGEST_INTERVAL_HOURS,
    JOB_ID_BUILD_DAILY_FEEDS,
    JOB_ID_CLASSIFY_PENDING,
    JOB_ID_CLEANUP_STALE_DATA,
    JOB_ID_DEDUP_PASS,
    JOB_ID_GEOCODE_PENDING,
    JOB_ID_INGEST_ALL_SOURCES,
    JOB_ID_PUBLISH_PENDING,
    JOB_ID_REFETCH_EVENT_DETAILS,
    JOB_ID_SEND_DAILY_DIGESTS,
    JOB_ID_SYNC_FIENTA_ORGANIZERS,
    LLM_PASS_INTERVAL_HOURS,
    LOG_EVENT_AUTH_FAILED,
    LOG_EVENT_HOST_REJECTED,
    LOG_EVENT_JOB_RUN,
    LOG_STATUS_ERROR,
    LOG_STATUS_OK,
    MAX_REQUEST_BODY_BYTES,
    ORGANIZER_SYNC_HOUR,
    ORGANIZER_SYNC_MINUTE,
    RATE_LIMIT_INTERNAL_TICK,
    REFETCH_HOUR,
    REFETCH_MINUTE,
    SECURITY_HEADERS,
    TALLINN_TZ_NAME,
    TRUSTED_HOST_REJECT_BODY,
)
from app.cleanup import cleanup_stale_data
from app.db import AsyncSessionLocal, engine
from app.email.digest import send_daily_digests
from app.ingestion.jobs import (
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
from app.routers.auth import router as auth_router
from app.routers.browse import router as browse_router
from app.routers.contact import router as contact_router
from app.routers.events import router as events_router
from app.routers.feed import router as feed_router
from app.routers.feedback import router as feedback_router
from app.routers.onboarding import router as onboarding_router
from app.routers.organizer_auth import router as organizer_auth_router
from app.routers.organizer_events import router as organizer_events_router
from app.routers.public import router as public_router
from app.routers.reports import router as reports_router
from app.routers.settings import router as settings_router
from app.routers.unsubscribe import router as unsubscribe_router
from app.routers.utils import require_configured_secret, run_in_session
from app.routers.webhooks import router as webhooks_router
from app.seeds import seed_personas, seed_sources

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
    traceback); admin-triggered runs of the same jobs convert failures to 500s
    via routers.utils.run_admin_job instead.
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
                    "duration_ms": round((time.monotonic() - start) * 1000),
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
                    "duration_ms": round((time.monotonic() - start) * 1000),
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
    "organizer sync", _in_session(sync_fienta_organizers, commit=True)
)
_run_cleanup = _scheduled(
    JOB_ID_CLEANUP_STALE_DATA, _in_session(cleanup_stale_data, commit=True)
)
_run_ingest_all = _scheduled("hourly ingest", ingest_all_enabled)
_run_dedup_pass = _scheduled("dedup pass", dedup_pass_drained)
_run_classify_pending = _scheduled(JOB_ID_CLASSIFY_PENDING, classify_pending_drained)
_run_publish_pending = _scheduled(JOB_ID_PUBLISH_PENDING, publish_pending_job)
_run_geocode_pending = _scheduled(JOB_ID_GEOCODE_PENDING, geocode_pending_job)
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


def _register_scheduled_jobs(scheduler: AsyncIOScheduler) -> None:
    """Wire the full cron schedule (see CLAUDE.md Architecture for the cadence)."""
    # Organizer discovery — weekly Sunday 03:00 EET
    scheduler.add_job(
        _run_organizer_sync,
        trigger="cron",
        day_of_week="sun",
        hour=ORGANIZER_SYNC_HOUR,
        minute=ORGANIZER_SYNC_MINUTE,
        id=JOB_ID_SYNC_FIENTA_ORGANIZERS,
        replace_existing=True,
    )

    # Data retention cleanup — weekly Sunday 03:30 EET (after organizer sync, off-peak)
    scheduler.add_job(
        _run_cleanup,
        trigger="cron",
        day_of_week="sun",
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

    # Every 6h: dedup pass + classify pending
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
    # Daily 04:30 EET: re-fetch every future event's detail page and reconcile
    # venue/address/coords/price against the source (after hourly ingest, before
    # the 06:00 feed build). A coord NULLed here on an address change is repaired
    # by the next geocode_pending interval pass — coords aren't a publish gate.
    scheduler.add_job(
        _run_refetch_details,
        trigger="cron",
        hour=REFETCH_HOUR,
        minute=REFETCH_MINUTE,
        id=JOB_ID_REFETCH_EVENT_DETAILS,
        replace_existing=True,
    )
    # Daily 06:00 EET: build personalized feeds for all users
    scheduler.add_job(
        _run_build_daily_feeds,
        trigger="cron",
        hour=FEED_BUILD_HOUR,
        minute=FEED_BUILD_MINUTE,
        id=JOB_ID_BUILD_DAILY_FEEDS,
        replace_existing=True,
    )
    # Daily 07:00 EET: send digest emails to opted-in users (one hour after feeds are built)
    scheduler.add_job(
        _run_send_daily_digests,
        trigger="cron",
        hour=DIGEST_SEND_HOUR,
        minute=0,
        id=JOB_ID_SEND_DAILY_DIGESTS,
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
            {"detail": "Origin header does not match a trusted origin."},
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

        origin = Headers(scope=scope).get("origin")
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

        async def _send(message: Message) -> None:
            nonlocal saw_400, rejected
            if message["type"] == ASGI_MESSAGE_TYPE_RESPONSE_START:
                saw_400 = message["status"] == status.HTTP_400_BAD_REQUEST
            elif message["type"] == ASGI_MESSAGE_TYPE_RESPONSE_BODY:
                if saw_400 and TRUSTED_HOST_REJECT_BODY in message.get("body", b""):
                    rejected = True
                saw_400 = False
            await send(message)

        await self._guarded(scope, receive, _send)
        if rejected:
            log.warning(
                "Host header rejected: host=%r path=%r client=%r",
                Headers(scope=scope).get("host"),
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
        response = JSONResponse(
            {"detail": f"Request body exceeds {self.max_bytes} bytes."},
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
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
    async with AsyncSessionLocal() as db:
        await seed_sources(db)
        await seed_personas(db)
        await db.commit()

    scheduler = _start_scheduler()
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        await engine.dispose()
        shutdown_log_shipping()


# Swagger UI / ReDoc load their JS/CSS from a CDN, which the restrictive
# default-src 'none' CSP (SECURITY_HEADERS, set on every response below) blocks —
# rather than carve out CDN exceptions in the policy, disable the docs routes
# outside development. CLAUDE.md already frames this as "a pure JSON API with no
# first-party HTML/script surface"; this makes that statement true everywhere.
_docs_enabled = settings.APP_ENV == APP_ENV_DEVELOPMENT
app = FastAPI(
    title="What's on Radar API",
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
    # API's own origin and only ever travels through the same-origin Vercel
    # `/api` rewrite the SPA is served behind, never via a cross-origin
    # browser fetch/XHR — so credentialed CORS would only widen the attack
    # surface for no functional gain, regardless of what CORS_ORIGINS lists.
    allow_credentials=False,
    allow_methods=CORS_ALLOWED_METHODS,
    allow_headers=CORS_ALLOWED_HEADERS,
)

# CORS_ORIGINS now serves double duty — CORS (above) and CSRF trust (below).
# Widening it for one purpose widens the other too; a value added here to let a
# new frontend deployment through CORS also becomes a trusted CSRF origin.
app.add_middleware(
    CsrfOriginCheckMiddleware,
    trusted_origins=frozenset(settings.CORS_ORIGINS) | {settings.FRONTEND_URL},
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
# derives the limiter/audit-log key from the *rightmost* XFF entry instead — the
# one appended by the single trusted hop (Render's proxy) — which is correct only
# if there is exactly one trusted hop between the client and this process. Adding
# another proxy/CDN in front of Render breaks this the same way it would break
# trusted_hosts="*" above.
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(browse_router)
app.include_router(contact_router)
app.include_router(events_router)
app.include_router(feed_router)
app.include_router(feedback_router)
app.include_router(onboarding_router)
app.include_router(organizer_auth_router)
app.include_router(organizer_events_router)
app.include_router(public_router)
app.include_router(reports_router)
app.include_router(settings_router)
app.include_router(unsubscribe_router)
app.include_router(webhooks_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": APP_VERSION}


@app.get("/internal/tick")
@limiter.limit(RATE_LIMIT_INTERNAL_TICK)
async def tick(request: Request) -> dict:
    """Keepalive ping — hit by a cron-job.org job every 10 min so Render's free
    tier never idles out (it sleeps after 15 min), which would halt the embedded
    APScheduler. Render cron services are paid, hence the external pinger."""
    token = settings.INTERNAL_TOKEN
    if require_configured_secret(
        token,
        feature="Internal tick",
        setting_name="INTERNAL_TOKEN",
        app_env=settings.APP_ENV,
        allow_insecure_dev=settings.ALLOW_INSECURE_DEV,
    ):
        received = request.headers.get("X-Internal-Token", "")
        if not secrets.compare_digest(received.encode(), token.encode()):
            log.warning(
                "internal/tick: invalid token (client=%s)",
                client_key(request),
                extra={"event": LOG_EVENT_AUTH_FAILED},
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=ERROR_INTERNAL_TICK_INVALID_TOKEN,
            )
    return {"status": "ok"}
