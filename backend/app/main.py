import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI

from app.constants import TALLINN_TZ_NAME
from app.db import AsyncSessionLocal, engine
from app.ingestion.organizer_sync import sync_fienta_organizers
from app.seeds import seed_sources

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncSessionLocal() as db:
        await seed_sources(db)
        await db.commit()

    scheduler = AsyncIOScheduler(timezone=TALLINN_TZ_NAME)
    scheduler.add_job(
        _run_organizer_sync,
        trigger="cron",
        day_of_week="sun",
        hour=3,
        minute=0,
        id="sync_fienta_organizers",
        replace_existing=True,
    )
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        await engine.dispose()


app = FastAPI(title="Event Radar API", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/internal/tick")
async def tick():
    # Called by Render Cron Job every 15 min to keep the dyno alive.
    return {"status": "ok"}
