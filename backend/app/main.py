import logging
import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.constants import DIGEST_SEND_HOUR, TALLINN_TZ_NAME
from app.db import AsyncSessionLocal, engine
from app.email.digest import send_daily_digests
from app.ingestion.jobs import classify_pending_job, dedup_pass, ingest_all_enabled
from app.ingestion.organizer_sync import sync_fienta_organizers
from app.ranking.score import build_daily_feeds
from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router
from app.routers.events import router as events_router
from app.routers.feed import router as feed_router
from app.routers.feedback import router as feedback_router
from app.routers.onboarding import router as onboarding_router
from app.routers.settings import router as settings_router
from app.routers.webhooks import router as webhooks_router
from app.seeds import seed_personas, seed_sources

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


async def _run_ingest_all() -> None:
    try:
        results = await ingest_all_enabled()
        log.info("hourly ingest completed: %s", results)
    except Exception:
        log.exception("hourly ingest failed")


async def _run_dedup_pass() -> None:
    try:
        summary = await dedup_pass()
        log.info("dedup pass completed: %s", summary)
    except Exception:
        log.exception("dedup pass failed")


async def _run_classify_pending() -> None:
    try:
        summary = await classify_pending_job()
        log.info("classify_pending completed: %s", summary)
    except Exception:
        log.exception("classify_pending failed")


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


app = FastAPI(title="Event Radar API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token"
            )
    elif settings.APP_ENV != "development":
        log.warning(
            "INTERNAL_TOKEN not set; /internal/tick is unauthenticated (APP_ENV=%s)",
            settings.APP_ENV,
        )
    return {"status": "ok"}
