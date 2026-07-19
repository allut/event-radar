import logging
import secrets
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from fastapi import FastAPI, HTTPException, Request, Response, status
from starlette.middleware.base import RequestResponseEndpoint
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config import settings
from app.constants import (
    APP_ENV_DEVELOPMENT,
    APP_VERSION,
    CLEANUP_HOUR,
    CLEANUP_MINUTE,
    CORS_ALLOWED_HEADERS,
    CORS_ALLOWED_METHODS,
    DIGEST_SEND_HOUR,
    FEED_BUILD_HOUR,
    FEED_BUILD_MINUTE,
    HSTS_HEADER_NAME,
    HSTS_HEADER_VALUE,
    INGEST_INTERVAL_HOURS,
    LLM_PASS_INTERVAL_HOURS,
    ORGANIZER_SYNC_HOUR,
    ORGANIZER_SYNC_MINUTE,
    REFETCH_HOUR,
    REFETCH_MINUTE,
    SECURITY_HEADERS,
    TALLINN_TZ_NAME,
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
from app.rate_limit import limiter, rate_limit_exceeded_handler
from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.routers.browse import router as browse_router
from app.routers.events import router as events_router
from app.routers.feed import router as feed_router
from app.routers.feedback import router as feedback_router
from app.routers.onboarding import router as onboarding_router
from app.routers.public import router as public_router
from app.routers.settings import router as settings_router
from app.routers.utils import require_configured_secret
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
        try:
            summary = await run()
            log.info("%s completed: %s", label, summary)
        except Exception:
            log.exception("%s failed", label)

    return _job


def _in_session(
    func: Callable[..., Awaitable[object]], *, commit: bool
) -> Callable[[], Awaitable[object]]:
    """Session-scoped job runner: open a session, run, commit when asked,
    roll back on failure (the error still propagates to _scheduled's logger)."""

    async def _run() -> object:
        async with AsyncSessionLocal() as db:
            try:
                result = await func(db)
                if commit:
                    await db.commit()
                return result
            except Exception:
                await db.rollback()
                raise

    return _run


_run_organizer_sync = _scheduled(
    "organizer sync", _in_session(sync_fienta_organizers, commit=True)
)
_run_cleanup = _scheduled(
    "cleanup_stale_data", _in_session(cleanup_stale_data, commit=True)
)
_run_ingest_all = _scheduled("hourly ingest", ingest_all_enabled)
_run_dedup_pass = _scheduled("dedup pass", dedup_pass_drained)
_run_classify_pending = _scheduled("classify_pending", classify_pending_drained)
_run_publish_pending = _scheduled("publish_pending", publish_pending_job)
_run_geocode_pending = _scheduled("geocode_pending", geocode_pending_job)
_run_refetch_details = _scheduled("refetch_event_details", refetch_event_details_job)
# build_daily_feeds and send_daily_digests commit internally / send only.
_run_build_daily_feeds = _scheduled(
    "build_daily_feeds", _in_session(build_daily_feeds, commit=False)
)
_run_send_daily_digests = _scheduled(
    "send_daily_digests", _in_session(send_daily_digests, commit=False)
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
        id="sync_fienta_organizers",
        replace_existing=True,
    )

    # Data retention cleanup — weekly Sunday 03:30 EET (after organizer sync, off-peak)
    scheduler.add_job(
        _run_cleanup,
        trigger="cron",
        day_of_week="sun",
        hour=CLEANUP_HOUR,
        minute=CLEANUP_MINUTE,
        id="cleanup_stale_data",
        replace_existing=True,
    )

    # Hourly ingestion of all enabled sources
    scheduler.add_job(
        _run_ingest_all,
        trigger="interval",
        hours=INGEST_INTERVAL_HOURS,
        id="ingest_all_sources",
        replace_existing=True,
    )

    # Every 6h: dedup pass + classify pending
    scheduler.add_job(
        _run_dedup_pass,
        trigger="interval",
        hours=LLM_PASS_INTERVAL_HOURS,
        id="dedup_pass",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_classify_pending,
        trigger="interval",
        hours=LLM_PASS_INTERVAL_HOURS,
        id="classify_pending",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_publish_pending,
        trigger="interval",
        hours=LLM_PASS_INTERVAL_HOURS,
        id="publish_pending",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_geocode_pending,
        trigger="interval",
        hours=LLM_PASS_INTERVAL_HOURS,
        id="geocode_pending",
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
        id="refetch_event_details",
        replace_existing=True,
    )
    # Daily 06:00 EET: build personalized feeds for all users
    scheduler.add_job(
        _run_build_daily_feeds,
        trigger="cron",
        hour=FEED_BUILD_HOUR,
        minute=FEED_BUILD_MINUTE,
        id="build_daily_feeds",
        replace_existing=True,
    )
    # Daily 07:00 EET: send digest emails to opted-in users (one hour after feeds are built)
    scheduler.add_job(
        _run_send_daily_digests,
        trigger="cron",
        hour=DIGEST_SEND_HOUR,
        minute=0,
        id="send_daily_digests",
        replace_existing=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    async with AsyncSessionLocal() as db:
        await seed_sources(db)
        await seed_personas(db)
        await db.commit()

    scheduler = AsyncIOScheduler(timezone=TALLINN_TZ_NAME)
    _register_scheduled_jobs(scheduler)
    scheduler.start()
    try:
        yield
    finally:
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
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    # Auth is a Bearer token in a header, never a cookie — credentialed CORS would
    # only widen the attack surface (and browsers reject `*` origins with it anyway).
    allow_credentials=False,
    allow_methods=CORS_ALLOWED_METHODS,
    allow_headers=CORS_ALLOWED_HEADERS,
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
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(browse_router)
app.include_router(events_router)
app.include_router(feed_router)
app.include_router(feedback_router)
app.include_router(onboarding_router)
app.include_router(public_router)
app.include_router(settings_router)
app.include_router(webhooks_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": APP_VERSION}


@app.get("/internal/tick")
async def tick(request: Request) -> dict:
    """Called by Render Cron Job every 15 min to keep the dyno alive."""
    token = settings.INTERNAL_TOKEN
    if require_configured_secret(
        token,
        feature="Internal tick",
        setting_name="INTERNAL_TOKEN",
        app_env=settings.APP_ENV,
    ):
        received = request.headers.get("X-Internal-Token", "")
        if not secrets.compare_digest(received, token):
            log.warning(
                "internal/tick: invalid token (client=%s)",
                request.client.host if request.client else "unknown",
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token"
            )
    return {"status": "ok"}
