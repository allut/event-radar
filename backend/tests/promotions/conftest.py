"""Real-Postgres fixtures for the promotions package.

The cap, overlap and ownership rules are SQL-shaped (and the cap needs a real
lock), so these tests run against a migrated Postgres through the root
conftest's `engine`/`db` fixtures, and skip when none is reachable. Every test
uses dates in 2090 so rows left in a shared dev database can never touch its cap.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, datetime
from contextlib import asynccontextmanager
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.dependencies import get_current_admin
from app.rate_limit import limiter
from app.promotions import sweep as sweep_module
from tests.conftest import at_tallinn
from tests.promotions.fakes import FakePaymentGateway

# "Now" for window tests: well before any 2090 event so only the rule under
# test can refuse a grant.
NOW = at_tallinn(2090, 1, 1, 10)


def d(day: int, month: int = 1) -> date:
    return date(2090, month, day)


@pytest.fixture
def gateway() -> FakePaymentGateway:
    return FakePaymentGateway()


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """(to_email, reason) of every ended-early email the Promotion sweep sends."""
    calls: list[tuple[str, str]] = []

    async def fake(to_email, event_title, start, end, reason, locale, http_client=None):
        calls.append((to_email, reason))

    monkeypatch.setattr(sweep_module, "send_promotion_ended_email", fake)
    return calls


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
    from app.routers import admin_reports as reports_module

    @asynccontextmanager
    async def session_ctx() -> AsyncIterator[Any]:
        yield db

    Clock.now = NOW
    modules = (admin_module, reports_module)
    for module in modules:
        monkeypatch.setattr(module, "AsyncSessionLocal", session_ctx)
        monkeypatch.setattr(module, "now_tallinn", lambda: Clock.now)
    app = FastAPI()
    for module in modules:
        app.include_router(module.router)
    app.dependency_overrides[get_current_admin] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
