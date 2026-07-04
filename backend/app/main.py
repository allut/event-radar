import logging
import secrets
from collections.abc import AsyncGenerator
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
    CORS_ALLOWED_HEADERS,
    CORS_ALLOWED_METHODS,
    DIGEST_SEND_HOUR,
    HSTS_HEADER_NAME,
    HSTS_HEADER_VALUE,
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
from app.routers.events import router as events_router
from app.routers.feed import router as feed_router
from app.routers.feedback import router as feedback_router
from app.routers.onboarding import router as onboarding_router
from app.routers.settings import router as settings_router
from app.routers.webhooks import router as webhooks_router
from app.seeds import seed_personas, seed_sources

# uvicorn configures its own logging during Config.load(), before importing this
# module — calling configure_logging() here runs last and wins, so every logger
# (app, uvicorn, SQL echo) shares one timestamped format.
configure_logging()

log = logging.getLogger(__name__)


async def _run_organizer_sync() -> None:
    async with AsyncSessionLocal() as db:
        try:
            result = await sync_fienta_organizers(db)
            await db.commit()
            log.info("organizer sync committed: %s", result)
        except Exception:
            await db.rollback()
            log.exception("organizer sync failed")


async def _run_cleanup() -> None:
    async with AsyncSessionLocal() as db:
        try:
            summary = await cleanup_stale_data(db)
            await db.commit()
            log.info("cleanup_stale_data committed: %s", summary)
        except Exception:
            await db.rollback()
            log.exception("cleanup_stale_data failed")


async def _run_ingest_all() -> None:
    try:
        results = await ingest_all_enabled()
        log.info("hourly ingest completed: %s", results)
    except Exception:
        log.exception("hourly ingest failed")


async def _run_dedup_pass() -> None:
    try:
        summary = await dedup_pass_drained()
        log.info("dedup pass completed: %s", summary)
    except Exception:
        log.exception("dedup pass failed")


async def _run_classify_pending() -> None:
    try:
        summary = await classify_pending_drained()
        log.info("classify_pending completed: %s", summary)
    except Exception:
        log.exception("classify_pending failed")


async def _run_publish_pending() -> None:
    try:
        summary = await publish_pending_job()
        log.info("publish_pending completed: %s", summary)
    except Exception:
        log.exception("publish_pending failed")


async def _run_geocode_pending() -> None:
    try:
        summary = await geocode_pending_job()
        log.info("geocode_pending completed: %s", summary)
    except Exception:
        log.exception("geocode_pending failed")


async def _run_refetch_details() -> None:
    try:
        summary = await refetch_event_details_job()
        log.info("refetch_event_details completed: %s", summary)
    except Exception:
        log.exception("refetch_event_details failed")


async def _run_build_daily_feeds() -> None:
    async with AsyncSessionLocal() as db:
        try:
            summary = await build_daily_feeds(db)
            log.info("build_daily_feeds completed: %s", summary)
        except Exception:
            await db.rollback()
            log.exception("build_daily_feeds failed")


async def _run_send_daily_digests() -> None:
    async with AsyncSessionLocal() as db:
        try:
            summary = await send_daily_digests(db)
            log.info("send_daily_digests completed: %s", summary)
        except Exception:
            log.exception("send_daily_digests failed")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    async with AsyncSessionLocal() as db:
        await seed_sources(db)
        await seed_personas(db)
        await db.commit()

    scheduler = AsyncIOScheduler(timezone=TALLINN_TZ_NAME)

    # Organizer discovery — weekly Sunday 03:00 EET
    scheduler.add_job(
        _run_organizer_sync,
        trigger="cron",
        day_of_week="sun",
        hour=3,
        minute=0,
        id="sync_fienta_organizers",
        replace_existing=True,
    )

    # Data retention cleanup — weekly Sunday 03:30 EET (after organizer sync, off-peak)
    scheduler.add_job(
        _run_cleanup,
        trigger="cron",
        day_of_week="sun",
        hour=3,
        minute=30,
        id="cleanup_stale_data",
        replace_existing=True,
    )

    # Hourly ingestion of all enabled sources
    scheduler.add_job(
        _run_ingest_all,
        trigger="interval",
        hours=1,
        id="ingest_all_sources",
        replace_existing=True,
    )

    # Every 6h: dedup pass + classify pending
    scheduler.add_job(
        _run_dedup_pass,
        trigger="interval",
        hours=6,
        id="dedup_pass",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_classify_pending,
        trigger="interval",
        hours=6,
        id="classify_pending",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_publish_pending,
        trigger="interval",
        hours=6,
        id="publish_pending",
        replace_existing=True,
    )
    scheduler.add_job(
        _run_geocode_pending,
        trigger="interval",
        hours=6,
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
        hour=4,
        minute=30,
        id="refetch_event_details",
        replace_existing=True,
    )
    # Daily 06:00 EET: build personalized feeds for all users
    scheduler.add_job(
        _run_build_daily_feeds,
        trigger="cron",
        hour=6,
        minute=0,
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
    title="Event Radar API",
    version="0.1.0",
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
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(events_router)
app.include_router(feed_router)
app.include_router(feedback_router)
app.include_router(onboarding_router)
app.include_router(settings_router)
app.include_router(webhooks_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/internal/tick")
async def tick(request: Request) -> dict:
    """Called by Render Cron Job every 15 min to keep the dyno alive."""
    token = settings.INTERNAL_TOKEN
    if token:
        received = request.headers.get("X-Internal-Token", "")
        if not secrets.compare_digest(received, token):
            log.warning(
                "internal/tick: invalid token (client=%s)",
                request.client.host if request.client else "unknown",
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token"
            )
    elif settings.APP_ENV != APP_ENV_DEVELOPMENT:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="INTERNAL_TOKEN not configured",
        )
    return {"status": "ok"}
