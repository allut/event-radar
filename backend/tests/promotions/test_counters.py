"""Delivery counters (#606): the in-process counter, its bulk-upsert flush, the
?ref=ad hooks and the admin per-day table, against a real Postgres."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.auth.dependencies import get_current_admin, get_current_user, get_optional_user
from app.constants.promotions import (
    PROMOTION_STAT_DIGEST_SENT,
    PROMOTION_STAT_EXPLORE_SERVED,
    PROMOTION_STAT_SLOT_DISLIKES,
    PROMOTION_STAT_WEB_OPENS,
    PROMOTION_STATUS_UNPAID,
)
from app.db import get_db
from app.models.models import PromotionDailyStat, User, UserEventFeedback
from app.promotions import counters
from app.rate_limit import limiter
from app.routers import admin_promotions as admin_module
from app.routers import events as events_router
from app.routers import feedback as feedback_router
from tests.promotions.conftest import NOW, d
from tests.promotions.test_explore_slot import classified, promote


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    limiter.reset()
    counters.reset()
    monkeypatch.setattr(counters, "now_tallinn", lambda: NOW)
    yield
    counters.reset()
    limiter.reset()


async def stats(db, promotion_id: int) -> dict[Any, PromotionDailyStat]:
    rows = (
        await db.scalars(
            select(PromotionDailyStat).where(PromotionDailyStat.promotion_id == promotion_id)
        )
    ).all()
    for r in rows:
        await db.refresh(r)
    return {r.day: r for r in rows}


async def live_promotion(db, make, **kw):
    org = await make.organizer()
    ev = await classified(make, org=org)
    return ev, await promote(db, ev, org, **kw)


async def test_flush_sums_across_flushes(db, make):
    _, p = await live_promotion(db, make)
    counters.bump(p.id, d(1), PROMOTION_STAT_EXPLORE_SERVED)
    counters.bump(p.id, d(1), PROMOTION_STAT_EXPLORE_SERVED)
    counters.bump(p.id, d(1), PROMOTION_STAT_WEB_OPENS)
    counters.bump(p.id, d(2), PROMOTION_STAT_SLOT_DISLIKES)
    assert (await counters.flush(db))["rows"] == 2
    counters.bump(p.id, d(1), PROMOTION_STAT_EXPLORE_SERVED)
    await counters.flush(db)
    got = await stats(db, p.id)
    assert (got[d(1)].explore_served, got[d(1)].web_opens, got[d(1)].slot_dislikes) == (3, 1, 0)
    assert (got[d(2)].slot_dislikes, got[d(2)].explore_served) == (1, 0)


async def test_flush_empty_is_a_noop(db):
    assert (await counters.flush(db))["rows"] == 0


async def test_failed_flush_keeps_the_counts(db, make):
    _, p = await live_promotion(db, make)
    counters.bump(p.id, d(1), PROMOTION_STAT_WEB_OPENS)

    class Boom:
        async def execute(self, *_a, **_k):
            raise RuntimeError("db down")

    with pytest.raises(RuntimeError):
        await counters.flush(Boom())  # type: ignore[arg-type]
    await counters.flush(db)
    assert (await stats(db, p.id))[d(1)].web_opens == 1


@pytest_asyncio.fixture
async def client(db) -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    app.include_router(events_router.router)
    app.include_router(feedback_router.router)

    async def _db() -> AsyncIterator[Any]:
        yield db

    user = await _make_user(db)
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_optional_user] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _make_user(db) -> User:
    user = User(email=f"counters-{id(db)}@example.com")
    db.add(user)
    await db.flush()
    return user


def _from(ip: str, ua: str = "Mozilla/5.0") -> dict[str, str]:
    return {"X-Forwarded-For": ip, "User-Agent": ua}


async def test_ref_ad_on_live_promotion_counts_a_web_open(db, make, client):
    ev, p = await live_promotion(db, make)
    for ref, ip in (("ad", "198.51.100.1"), ("ad", "198.51.100.2"), (None, "198.51.100.3"), ("other", "198.51.100.4")):
        resp = await client.get(
            f"/events/{ev.id}", params={"ref": ref} if ref else {}, headers=_from(ip)
        )
        assert resp.status_code == 200
    await counters.flush(db)
    assert (await stats(db, p.id))[d(1)].web_opens == 2


async def test_ref_digest_ad_on_live_promotion_counts_a_digest_open(db, make, client):
    ev, p = await live_promotion(db, make)
    for ref, ip in (("digest-ad", "198.51.100.1"), ("digest-ad", "198.51.100.2"), ("ad", "198.51.100.1"), (None, "198.51.100.1")):
        resp = await client.get(
            f"/events/{ev.id}", params={"ref": ref} if ref else {}, headers=_from(ip)
        )
        assert resp.status_code == 200
    await counters.flush(db)
    got = (await stats(db, p.id))[d(1)]
    assert (got.digest_opens, got.web_opens) == (2, 1)


async def test_ref_open_counts_once_per_client_a_day(db, make, client):
    """Anonymous opens reach paying advertisers: one client refreshing, or
    rotating within its IPv6 /64, must not inflate them (security audit)."""
    ev, p = await live_promotion(db, make)
    for ip in ("198.51.100.7", "198.51.100.7", "2001:db8::1", "2001:db8::2"):
        resp = await client.get(f"/events/{ev.id}", params={"ref": "ad"}, headers=_from(ip))
        assert resp.status_code == 200
    await counters.flush(db)  # a flush must not forget who already counted
    resp = await client.get(f"/events/{ev.id}", params={"ref": "ad"}, headers=_from("198.51.100.7"))
    await counters.flush(db)
    assert (await stats(db, p.id))[d(1)].web_opens == 2


async def test_ref_open_from_a_bot_does_not_count(db, make, client):
    ev, p = await live_promotion(db, make)
    resp = await client.get(
        f"/events/{ev.id}",
        params={"ref": "ad"},
        headers=_from("198.51.100.8", "Mozilla/5.0 (compatible; Googlebot/2.1)"),
    )
    assert resp.status_code == 200
    await counters.flush(db)
    assert d(1) not in await stats(db, p.id)


def test_first_ref_hit_is_per_day_and_refuses_new_clients_when_full(monkeypatch, caplog):
    monkeypatch.setattr(counters, "PROMOTION_REF_SEEN_MAX_ENTRIES", 2)
    col = PROMOTION_STAT_WEB_OPENS
    assert counters.first_ref_hit("a", 1, d(1), col)
    assert not counters.first_ref_hit("a", 1, d(1), col)
    assert counters.first_ref_hit("a", 2, d(1), col)  # another Promotion
    # Full: a new client is refused rather than evicting someone (eviction
    # would let rotating addresses re-count without bound); one warning.
    assert not counters.first_ref_hit("b", 1, d(1), col)
    assert not counters.first_ref_hit("c", 1, d(1), col)
    assert [r.event for r in caplog.records] == ["promotion_ref_seen_full"]  # type: ignore[attr-defined]
    assert not counters.first_ref_hit("a", 1, d(1), col)
    # A new day starts empty.
    assert counters.first_ref_hit("a", 1, d(2), col)
    assert counters.first_ref_hit("b", 1, d(2), col)


async def test_digest_sent_flushes(db, make):
    _, p = await live_promotion(db, make)
    counters.bump(p.id, d(1), PROMOTION_STAT_DIGEST_SENT)
    await counters.flush(db)
    assert (await stats(db, p.id))[d(1)].digest_sent == 1


async def test_ref_ad_on_non_live_promotion_counts_nothing(db, make, client):
    ev, _ = await live_promotion(db, make, status=PROMOTION_STATUS_UNPAID)
    ev2, _ = await live_promotion(db, make, start_date=d(10), end_date=d(14))
    for e in (ev, ev2):
        assert (await client.get(f"/events/{e.id}", params={"ref": "ad"})).status_code == 200
    assert (await counters.flush(db))["rows"] == 0


async def test_ref_ad_dislike_counts_and_still_writes_feedback(db, make, client):
    ev, p = await live_promotion(db, make)
    resp = await client.post(
        "/feedback", json={"event_id": ev.id, "signal": "dislike", "ref": "ad"}
    )
    assert resp.status_code == 200
    await client.post("/feedback", json={"event_id": ev.id, "signal": "bookmark", "ref": "ad"})
    await client.post("/feedback", json={"event_id": ev.id, "signal": "dislike"})
    await counters.flush(db)
    assert (await stats(db, p.id))[d(1)].slot_dislikes == 1
    rows = (
        await db.scalars(select(UserEventFeedback).where(UserEventFeedback.event_id == ev.id))
    ).all()
    assert [r.signal for r in rows] == ["dislike"]


@pytest_asyncio.fixture
async def admin_client(db, monkeypatch) -> AsyncIterator[AsyncClient]:
    @asynccontextmanager
    async def session_ctx() -> AsyncIterator[Any]:
        yield db

    monkeypatch.setattr(admin_module, "AsyncSessionLocal", session_ctx)
    monkeypatch.setattr(admin_module, "now_tallinn", lambda: NOW.replace(day=4))
    app = FastAPI()
    app.include_router(admin_module.router)
    app.dependency_overrides[get_current_admin] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_admin_daily_stats_lists_complete_days_only(db, make, admin_client):
    _, p = await live_promotion(db, make)  # window Jan 1-5, "today" is Jan 4
    counters.bump(p.id, d(1), PROMOTION_STAT_EXPLORE_SERVED)
    counters.bump(p.id, d(2), PROMOTION_STAT_WEB_OPENS)
    counters.bump(p.id, d(4), PROMOTION_STAT_WEB_OPENS)  # today: incomplete
    await counters.flush(db)
    resp = await admin_client.get(f"/admin/promotions/{p.id}/daily-stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["promotion_id"] == p.id
    assert [r["day"] for r in body["days"]] == ["2090-01-01", "2090-01-02", "2090-01-03"]
    assert body["days"][0]["explore_served"] == 1
    assert body["days"][1]["web_opens"] == 1
    assert body["days"][2] == {
        "day": "2090-01-03",
        "gate_outcome": None,
        "gate_reason": None,
        "explore_served": 0,
        "daily5_placed": 0,
        "digest_sent": 0,
        "web_opens": 0,
        "digest_opens": 0,
        "slot_dislikes": 0,
    }


async def test_admin_daily_stats_404(admin_client):
    assert (await admin_client.get("/admin/promotions/987654321/daily-stats")).status_code == 404
