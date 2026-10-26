"""The Daily 5 Sponsored slot (#607): the nightly pick in build_daily_feeds, the
3-day cooldown, the gate-outcome rows, counters and reach, against a real
Postgres.

Candidate events are created relative to the real clock because
build_daily_feeds reads "now" itself. Everything rolls back with the test's
outer transaction.
"""

import itertools
import os
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import delete, select

from app.config import settings
from app.constants.core import TALLINN_TZ
from app.constants.promotions import (
    PROMOTION_NOT_SHOWING_RESTRICTION_UNASSESSED,
    PROMOTION_NOT_SHOWING_SLOTS_DISABLED,
    PROMOTION_STATUS_PAID,
)
from app.models.models import (
    DailyFeed,
    DailySponsoredSlot,
    EventClassification,
    Promotion,
    PromotionDailyStat,
    User,
    UserEventFeedback,
)
from app.promotions import counters
from app.ranking.score import build_daily_feeds
from tests.conftest import count_statements
from datetime import datetime

_n = itertools.count(1)
CATEGORIES = ["music", "theatre", "film", "food", "art", "sport", "comedy", "tech"]


def today():
    return datetime.now(TALLINN_TZ).date()


@pytest.fixture(autouse=True)
def _flags(monkeypatch):
    monkeypatch.setattr(settings, "PROMOTIONS_SLOTS_ENABLED", True)
    counters.reset()
    yield
    counters.reset()


async def users(db, n: int) -> list[User]:
    out = []
    for _ in range(n):
        u = User(
            email=f"d5-{next(_n)}-{os.getpid()}@example.com", email_verified=True, locale="en"
        )
        db.add(u)
        out.append(u)
    await db.flush()
    return out


async def organic(make, n: int = 8) -> list:
    """n upcoming organic events across categories, soon, so they win the five."""
    now = datetime.now(TALLINN_TZ)
    out = []
    for i in range(n):
        ev = await make.event(
            starts_at=now + timedelta(days=1, hours=i),
            ends_at=now + timedelta(days=1, hours=i + 2),
        )
        make.db.add(EventClassification(event_id=ev.id, categories=[CATEGORIES[i]], vibes=[]))
        out.append(ev)
    await make.db.flush()
    return out


async def promoted(make, org, *, days_ahead: int = 12, restriction: str | None = "none", **kw: Any):
    """An owned, cleared event far enough out that it never makes the five, plus
    a paid Promotion covering today."""
    now = datetime.now(TALLINN_TZ)
    ev = await make.event(
        submitted_by=org,
        starts_at=now + timedelta(days=days_ahead),
        ends_at=now + timedelta(days=days_ahead, hours=2),
        promotion_restriction=restriction,
    )
    make.db.add(EventClassification(event_id=ev.id, categories=["music"], vibes=[]))
    t = today()
    fields: dict[str, Any] = dict(
        event_id=ev.id,
        organizer_id=org.id,
        status=PROMOTION_STATUS_PAID,
        start_date=t - timedelta(days=1),
        end_date=t + timedelta(days=5),
        days=7,
        net_price_cents=0,
        vat_rate_percent=24,
        is_complimentary=True,
        complimentary_note="pilot",
        advertiser_legal_name=f"{org.name} OÜ",
        advertiser_registry_code="12345678",
    )
    fields.update(kw)
    promo = Promotion(**fields)
    make.db.add(promo)
    await make.db.flush()
    return ev, promo


async def slots(db) -> dict[int, DailySponsoredSlot]:
    rows = (
        await db.scalars(
            select(DailySponsoredSlot).where(DailySponsoredSlot.slot_date == today())
        )
    ).all()
    return {r.user_id: r for r in rows}


async def run_build(db) -> None:
    await build_daily_feeds(db)
    await db.flush()


@pytest.mark.asyncio
async def test_full_five_gets_one_stored_slot_and_counts(db, make) -> None:
    org = await make.organizer("Acme")
    await organic(make)
    ev, promo = await promoted(make, org)
    (user,) = await users(db, 1)

    await run_build(db)

    row = (await slots(db))[user.id]
    assert (row.promotion_id, row.is_swap, row.replaced_promotion_id) == (promo.id, False, None)
    feed = await db.scalar(select(DailyFeed).where(DailyFeed.user_id == user.id))
    assert len(feed.event_ids) == 5 and ev.id not in feed.event_ids
    stat = await db.scalar(
        select(PromotionDailyStat).where(
            PromotionDailyStat.promotion_id == promo.id, PromotionDailyStat.day == today()
        )
    )
    assert (stat.gate_outcome, stat.gate_reason, stat.daily5_placed) == ("shown", None, 1)
    await db.refresh(promo)
    assert promo.daily5_reach == 1


@pytest.mark.asyncio
async def test_five_is_identical_with_and_without_promotions(db, make) -> None:
    org = await make.organizer("Acme")
    await organic(make)
    (user,) = await users(db, 1)
    await run_build(db)
    baseline = (await db.scalar(select(DailyFeed).where(DailyFeed.user_id == user.id))).event_ids

    await promoted(make, org)
    await db.execute(delete(DailyFeed))
    await run_build(db)
    with_ads = (await db.scalar(select(DailyFeed).where(DailyFeed.user_id == user.id))).event_ids
    assert with_ads == baseline
    assert user.id in await slots(db)


@pytest.mark.asyncio
async def test_no_slot_without_a_full_five(db, make) -> None:
    org = await make.organizer("Acme")
    await organic(make, n=3)
    await promoted(make, org)
    await users(db, 1)
    await run_build(db)
    assert await slots(db) == {}


@pytest.mark.asyncio
async def test_slot_is_never_an_event_already_in_the_five(db, make) -> None:
    org = await make.organizer("Acme")
    events = await organic(make)
    # Promote an organic event that is sure to be in the five: the earliest one.
    promo = Promotion(
        event_id=events[0].id,
        organizer_id=org.id,
        status=PROMOTION_STATUS_PAID,
        start_date=today(),
        end_date=today() + timedelta(days=4),
        days=5,
        net_price_cents=0,
        vat_rate_percent=24,
        is_complimentary=True,
        complimentary_note="pilot",
        advertiser_legal_name="Acme OÜ",
        advertiser_registry_code="12345678",
    )
    events[0].submitted_by_organizer_id = org.id
    events[0].promotion_restriction = "none"
    db.add(promo)
    (user,) = await users(db, 1)
    await db.flush()
    await run_build(db)
    feed = await db.scalar(select(DailyFeed).where(DailyFeed.user_id == user.id))
    if events[0].id in feed.event_ids:
        assert await slots(db) == {}


@pytest.mark.asyncio
async def test_event_outside_the_14_day_window_is_not_picked(db, make) -> None:
    org = await make.organizer("Acme")
    await organic(make)
    await promoted(make, org, days_ahead=20)
    await users(db, 1)
    await run_build(db)
    assert await slots(db) == {}


@pytest.mark.asyncio
async def test_cooldown_collapses_the_slot_instead_of_repeating(db, make) -> None:
    org = await make.organizer("Acme")
    await organic(make)
    ev, promo = await promoted(make, org)
    (user,) = await users(db, 1)
    for ago in (1, 3):
        db.add(
            DailySponsoredSlot(
                user_id=user.id, slot_date=today() - timedelta(days=ago), promotion_id=promo.id
            )
        )
    await db.flush()
    await run_build(db)
    assert await slots(db) == {}  # sole Promotion was shown within 3 days: collapse


@pytest.mark.asyncio
async def test_cooldown_lifts_after_three_days_and_rotates_to_the_unshown(db, make) -> None:
    org = await make.organizer("Acme")
    await organic(make)
    _, shown = await promoted(make, org)
    _, other = await promoted(make, await make.organizer("Beta"))
    (user,) = await users(db, 1)
    db.add(
        DailySponsoredSlot(
            user_id=user.id, slot_date=today() - timedelta(days=2), promotion_id=shown.id
        )
    )
    await db.flush()
    await run_build(db)
    assert (await slots(db))[user.id].promotion_id == other.id

    # Four days ago is outside the cooldown, so both are eligible again.
    await db.execute(delete(DailySponsoredSlot).where(DailySponsoredSlot.slot_date == today()))
    await db.execute(
        DailySponsoredSlot.__table__.update().values(slot_date=today() - timedelta(days=4))
    )
    await run_build(db)
    assert user.id in await slots(db)


@pytest.mark.asyncio
async def test_viewer_exclusions_skip_a_disliked_event(db, make) -> None:
    org = await make.organizer("Acme")
    await organic(make)
    ev1, p1 = await promoted(make, org)
    ev2, p2 = await promoted(make, await make.organizer("Beta"))
    disliker, plain = await users(db, 2)
    db.add(UserEventFeedback(user_id=disliker.id, event_id=ev1.id, signal="dislike"))
    db.add(UserEventFeedback(user_id=disliker.id, event_id=ev2.id, signal="dislike"))
    await db.flush()
    await run_build(db)
    picked = await slots(db)
    assert disliker.id not in picked  # every Promotion excluded: collapse
    assert plain.id in picked


@pytest.mark.asyncio
async def test_gate_outcome_rows_name_the_paused_reason(db, make) -> None:
    org = await make.organizer("Acme")
    await organic(make)
    _, ok = await promoted(make, org)
    _, paused = await promoted(make, await make.organizer("Beta"), restriction=None)
    await users(db, 1)
    await run_build(db)
    rows = {
        r.promotion_id: r
        for r in (
            await db.scalars(select(PromotionDailyStat).where(PromotionDailyStat.day == today()))
        ).all()
    }
    assert (rows[ok.id].gate_outcome, rows[ok.id].gate_reason) == ("shown", None)
    assert (rows[paused.id].gate_outcome, rows[paused.id].gate_reason) == (
        "paused",
        PROMOTION_NOT_SHOWING_RESTRICTION_UNASSESSED,
    )
    assert rows[paused.id].daily5_placed == 0


@pytest.mark.asyncio
async def test_flag_off_picks_nothing_and_records_why(db, make, monkeypatch) -> None:
    monkeypatch.setattr(settings, "PROMOTIONS_SLOTS_ENABLED", False)
    org = await make.organizer("Acme")
    await organic(make)
    _, promo = await promoted(make, org)
    await users(db, 1)
    await run_build(db)
    assert await slots(db) == {}
    stat = await db.scalar(
        select(PromotionDailyStat).where(PromotionDailyStat.promotion_id == promo.id)
    )
    assert (stat.gate_outcome, stat.gate_reason) == ("paused", PROMOTION_NOT_SHOWING_SLOTS_DISABLED)


@pytest.mark.asyncio
async def test_reach_counts_distinct_users_and_freezes_after_the_window(db, make) -> None:
    org = await make.organizer("Acme")
    await organic(make)
    _, promo = await promoted(make, org)
    await users(db, 3)
    await run_build(db)
    await db.refresh(promo)
    assert promo.daily5_reach == 3

    # A window that ended two days ago is frozen: its stored reach is not touched.
    _, old = await promoted(
        make,
        await make.organizer("Gamma"),
        start_date=today() - timedelta(days=9),
        end_date=today() - timedelta(days=2),
        daily5_reach=42,
    )
    await db.execute(delete(DailySponsoredSlot).where(DailySponsoredSlot.slot_date == today()))
    await run_build(db)
    await db.refresh(old)
    assert old.daily5_reach == 42


@pytest.mark.asyncio
async def test_query_count_is_fixed_as_users_and_promotions_grow(db, make) -> None:
    org = await make.organizer("Acme")
    await organic(make)
    await promoted(make, org)
    await users(db, 2)
    with count_statements(db) as statements:
        await build_daily_feeds(db)
        small = len(statements)

        for i in range(3):
            await promoted(make, await make.organizer(f"Org{i}"))
        await users(db, 6)
        await db.execute(delete(DailyFeed))
        await db.execute(delete(DailySponsoredSlot))
        statements.clear()
        await build_daily_feeds(db)
        large = len(statements)
    assert large == small
