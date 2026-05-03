from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import AsyncSessionLocal, engine
from app.seeds import seed_sources


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncSessionLocal() as db:
        await seed_sources(db)
        await db.commit()
    yield
    await engine.dispose()


app = FastAPI(title="Event Radar API", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/internal/tick")
async def tick():
    # Called by Render Cron Job every 15 min to keep the dyno alive.
    return {"status": "ok"}
