"""GET /feed with the Daily 5 Sponsored slot (#607): the stored slot after the
five, the mid-day swap and its stickiness, against a real Postgres."""

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.auth.dependencies import get_current_user
from app.config import settings
from app.constants.promotions import PROMOTION_STAT_DAILY5_PLACED
from app.db import get_db
from app.models.models import DailyFeed, DailySponsoredSlot, PromotionDailyStat
from app.promotions import counters
from app.rate_limit import limiter
from app.routers import feed
from tests.promotions.test_daily5_slot import organic, promoted, today, users


@pytest.fixture(autouse=True)
def _state(monkeypatch):
    limiter.reset()
    counters.reset()
    monkeypatch.setattr(settings, "PROMOTIONS_SLOTS_ENABLED", True)
    yield
    counters.reset()
    limiter.reset()


class Viewer:
    user: Any = None


@pytest_asyncio.fixture
async def client(db) -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    app.include_router(feed.router)

    async def _db() -> AsyncIterator[Any]:
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: Viewer.user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def setup_user(db, make, n_promos: int = 1):
    """A user with a stored five, and n Promotions; the first is stored for them."""
    events = await organic(make)
    (user,) = await users(db, 1)
    Viewer.user = user
    db.add(DailyFeed(user_id=user.id, feed_date=today(), event_ids=[e.id for e in events[:5]]))
    promos = []
    for i in range(n_promos):
        ev, promo = await promoted(make, await make.organizer(f"Org{i}"))
        promos.append((ev, promo))
    db.add(
        DailySponsoredSlot(user_id=user.id, slot_date=today(), promotion_id=promos[0][1].id)
    )
    await db.flush()
    return user, events[:5], promos


async def stored(db, user) -> DailySponsoredSlot:
    return await db.scalar(
        select(DailySponsoredSlot).where(
            DailySponsoredSlot.user_id == user.id, DailySponsoredSlot.slot_date == today()
        )
    )


@pytest.mark.asyncio
async def test_feed_returns_the_stored_slot_after_the_five(client, db, make) -> None:
    user, five, promos = await setup_user(db, make)
    body = (await client.get("/feed")).json()
    assert [e["id"] for e in body["events"]] == [e.id for e in five]
    slot = body["sponsored_slot"]
    assert slot["id"] == promos[0][0].id
    assert slot["advertiser"] == "Org0 OÜ"
    assert slot["explanation"] == "daily5"
    assert slot["id"] not in [e["id"] for e in body["events"]]  # outside the list


@pytest.mark.asyncio
async def test_five_is_identical_with_and_without_a_slot(client, db, make, monkeypatch) -> None:
    await setup_user(db, make)
    with_slot = (await client.get("/feed")).json()
    monkeypatch.setattr(settings, "PROMOTIONS_SLOTS_ENABLED", False)
    without = (await client.get("/feed")).json()
    assert "sponsored_slot" not in without
    assert with_slot["events"] == without["events"]


@pytest.mark.asyncio
async def test_no_stored_row_means_no_slot(client, db, make) -> None:
    user, _, _ = await setup_user(db, make)
    await db.delete(await stored(db, user))
    await db.flush()
    assert "sponsored_slot" not in (await client.get("/feed")).json()


@pytest.mark.asyncio
async def test_bot_user_agent_gets_no_slot(client, db, make) -> None:
    await setup_user(db, make)
    body = (await client.get("/feed", headers={"user-agent": "Googlebot/2.1"})).json()
    assert "sponsored_slot" not in body


@pytest.mark.asyncio
async def test_failing_stored_pick_is_swapped_once_stored_and_sticks(client, db, make) -> None:
    user, _, promos = await setup_user(db, make, n_promos=2)
    first_ev, first = promos[0]
    second_ev, second = promos[1]

    first_ev.promotion_restriction = "gambling"  # newly flagged: the gate now fails
    await db.flush()
    body = (await client.get("/feed")).json()
    assert body["sponsored_slot"]["id"] == second_ev.id
    row = await stored(db, user)
    assert (row.promotion_id, row.is_swap, row.replaced_promotion_id) == (
        second.id,
        True,
        first.id,
    )
    # Swap counted as placed.
    await counters.flush(db)
    stat = await db.scalar(
        select(PromotionDailyStat).where(
            PromotionDailyStat.promotion_id == second.id, PromotionDailyStat.day == today()
        )
    )
    assert getattr(stat, PROMOTION_STAT_DAILY5_PLACED) == 1

    # Sticks: the original recovering does not bring it back.
    first_ev.promotion_restriction = "none"
    await db.flush()
    again = (await client.get("/feed")).json()
    assert again["sponsored_slot"]["id"] == second_ev.id
    assert (await stored(db, user)).replaced_promotion_id == first.id


@pytest.mark.asyncio
async def test_swap_collapses_when_nothing_is_left_and_sticks(client, db, make) -> None:
    user, _, promos = await setup_user(db, make)
    ev, promo = promos[0]
    ev.promotion_restriction = "gambling"
    await db.flush()
    assert "sponsored_slot" not in (await client.get("/feed")).json()
    row = await stored(db, user)
    assert (row.promotion_id, row.is_swap, row.replaced_promotion_id) == (None, True, promo.id)
    ev.promotion_restriction = "none"
    await db.flush()
    assert "sponsored_slot" not in (await client.get("/feed")).json()


@pytest.mark.asyncio
async def test_swap_never_repeats_the_cooldown_or_a_viewer_excluded_promotion(
    client, db, make
) -> None:
    user, _, promos = await setup_user(db, make, n_promos=2)
    # The only replacement was shown to this user two days ago.
    db.add(
        DailySponsoredSlot(
            user_id=user.id, slot_date=today() - timedelta(days=2), promotion_id=promos[1][1].id
        )
    )
    promos[0][0].promotion_restriction = "gambling"
    await db.flush()
    assert "sponsored_slot" not in (await client.get("/feed")).json()
    assert (await stored(db, user)).promotion_id is None
