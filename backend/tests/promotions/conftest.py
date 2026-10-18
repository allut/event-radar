"""Real-Postgres fixtures for the promotions package.

The cap, overlap and ownership rules are SQL-shaped (and the cap needs a real
lock), so these tests run against a migrated Postgres and skip when none is
reachable (the migrations CI job, or the devcontainer db). Every test uses
dates in 2090 so rows left in a shared dev database can never touch its cap.
"""

from __future__ import annotations

import itertools
import os
from collections.abc import AsyncIterator
from datetime import date, datetime
from contextlib import asynccontextmanager
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.dependencies import get_current_admin
from app.constants.claims import CLAIM_KIND_PUBLISHER, CLAIM_KIND_SERIES, CLAIM_STATUS_APPROVED
from app.constants.core import TALLINN_TZ
from app.rate_limit import limiter
from app.models.models import Claim, Event, EventSource, Organizer, Publisher, Source

_counter = itertools.count(1)


def at_tallinn(y: int, m: int, d: int, hh: int = 12, mm: int = 0, ss: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, ss, tzinfo=TALLINN_TZ)


# "Now" for window tests: well before any 2090 event so only the rule under
# test can refuse a grant.
NOW = at_tallinn(2090, 1, 1, 10)
EVENT_START = at_tallinn(2090, 2, 1, 19)
EVENT_END = at_tallinn(2090, 2, 28, 22)


def d(day: int, month: int = 1) -> date:
    return date(2090, month, day)


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[Any]:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set")
    eng = create_async_engine(url)
    try:
        async with eng.connect() as conn:
            ok = await conn.scalar(text("SELECT to_regclass('public.promotion_snapshots')"))
    except Exception:
        await eng.dispose()
        pytest.skip("Postgres unreachable")
    if not ok:
        await eng.dispose()
        pytest.skip("DB not at migration 0062")
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine: Any) -> AsyncIterator[AsyncSession]:
    """A session inside an outer transaction that is rolled back, so nothing a
    test writes (commits included) survives it."""
    async with engine.connect() as conn:
        outer = await conn.begin()
        session = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            yield session
        finally:
            await session.close()
            await outer.rollback()


class Factory:
    def __init__(self, session: AsyncSession) -> None:
        self.db = session

    async def organizer(self, name: str | None = "Acme Events") -> Organizer:
        n = next(_counter)
        org = Organizer(email=f"promo-{n}-{os.getpid()}@example.com", name=name)
        self.db.add(org)
        await self.db.flush()
        return org

    async def event(
        self,
        *,
        submitted_by: Organizer | None = None,
        starts_at: datetime = EVENT_START,
        ends_at: datetime | None = EVENT_END,
        title: str = "Promo Show",
        venue_name: str | None = None,
        status: str = "published",
        **kw: Any,
    ) -> Event:
        n = next(_counter)
        ev = Event(
            slug=f"promo-{n}-{os.getpid()}",
            title_orig=f"{title} {n}",
            starts_at=starts_at,
            ends_at=ends_at,
            venue_name=venue_name or f"Hall {n}",
            status=status,
            submitted_by_organizer_id=submitted_by.id if submitted_by else None,
            **kw,
        )
        self.db.add(ev)
        await self.db.flush()
        await self.db.refresh(ev)  # series_key is trigger-maintained
        return ev

    async def publisher_claim(
        self, event: Event, organizer: Organizer, *, dormant: bool = False, status: str = CLAIM_STATUS_APPROVED
    ) -> Claim:
        n = next(_counter)
        source = Source(slug=f"promo-src-{n}-{os.getpid()}", kind="html", config={})
        self.db.add(source)
        await self.db.flush()
        pub = Publisher(source_id=source.id, external_id=str(n), name=f"Pub {n}")
        self.db.add(pub)
        await self.db.flush()
        self.db.add(EventSource(event_id=event.id, source_id=source.id, publisher_id=pub.id))
        claim = Claim(
            organizer_id=organizer.id,
            kind=CLAIM_KIND_PUBLISHER,
            publisher_id=pub.id,
            status=status,
            proof_token="tok",
            dormant=dormant,
        )
        self.db.add(claim)
        await self.db.flush()
        return claim

    async def series_claim(
        self, event: Event, organizer: Organizer, *, dormant: bool = False, status: str = CLAIM_STATUS_APPROVED
    ) -> Claim:
        claim = Claim(
            organizer_id=organizer.id,
            kind=CLAIM_KIND_SERIES,
            event_series_key=event.series_key,
            status=status,
            proof_token="tok",
            justification="mine",
            dormant=dormant,
        )
        self.db.add(claim)
        await self.db.flush()
        return claim


@pytest.fixture
def make(db: AsyncSession) -> Factory:
    return Factory(db)


@pytest.fixture
def sessionmaker_for(engine: Any) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture(autouse=True)
def _fresh_limiter():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture(autouse=True)
def _checkout_clock(monkeypatch):
    """The checkout reads a fresh clock just before it opens the Stripe
    session; tests pin it to NOW so session expiries stay in the 2090 frame."""
    from app.promotions import checkout as checkout_module

    monkeypatch.setattr(checkout_module, "_clock", lambda: NOW)


class Clock:
    now: datetime = NOW


@pytest_asyncio.fixture
async def client(db, monkeypatch) -> AsyncIterator[AsyncClient]:
    from app.routers import admin as admin_module

    @asynccontextmanager
    async def session_ctx() -> AsyncIterator[Any]:
        yield db

    monkeypatch.setattr(admin_module, "AsyncSessionLocal", session_ctx)
    Clock.now = NOW
    monkeypatch.setattr(admin_module, "now_tallinn", lambda: Clock.now)
    app = FastAPI()
    app.include_router(admin_module.router)
    app.dependency_overrides[get_current_admin] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
