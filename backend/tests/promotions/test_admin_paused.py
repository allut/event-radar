"""Admin list and detail carry the fill gate's current pause reason (#629)."""

import pytest

from app._generated.shared_constants import (
    PROMOTION_NOT_SHOWING_EVENT_NOT_PUBLIC,
    PROMOTION_NOT_SHOWING_NOT_OWNED,
    PROMOTION_NOT_SHOWING_RESTRICTION_FLAGGED,
    PROMOTION_NOT_SHOWING_RESTRICTION_UNASSESSED,
)
from app.constants.promotions import PROMOTION_STATUS_UNPAID
from app.promotions.views import grant_context, list_promotions, paused_reasons, promotion_detail
from tests.conftest import count_statements
from tests.promotions.conftest import NOW, d
from tests.promotions.test_explore_slot import classified, clear, promote


async def listed(db, state: str | None = None) -> dict[int, dict]:
    items, _ = await list_promotions(db, state=state, limit=100, offset=0, now=NOW)
    return {i["id"]: i for i in items}


@pytest.mark.asyncio
async def test_dormant_claim_reads_paused_in_list_and_detail(db, make) -> None:
    claimant = await make.organizer("Claimant")
    ev = await classified(make)
    await make.publisher_claim(ev, claimant, dormant=True)
    await clear(db, ev)
    promo = await promote(db, ev, claimant, start_date=d(1), end_date=d(5))
    row = (await listed(db))[promo.id]
    assert row["state"] == "live"
    assert row["paused_reason"] == PROMOTION_NOT_SHOWING_NOT_OWNED
    detail = await promotion_detail(db, promo, NOW)
    assert detail["paused_reason"] == PROMOTION_NOT_SHOWING_NOT_OWNED


@pytest.mark.asyncio
async def test_unassessed_restriction_pauses(db, make) -> None:
    org = await make.organizer()
    ev = await classified(make, org=org)
    await clear(db, ev, None)
    promo = await promote(db, ev, org, start_date=d(1), end_date=d(5))
    assert (await listed(db))[promo.id]["paused_reason"] == PROMOTION_NOT_SHOWING_RESTRICTION_UNASSESSED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_kw", "restriction", "expected"),
    [
        ({"status": "draft"}, "none", PROMOTION_NOT_SHOWING_EVENT_NOT_PUBLIC),
        ({}, "gambling", PROMOTION_NOT_SHOWING_RESTRICTION_FLAGGED),
    ],
)
async def test_other_gate_reasons_reach_list_and_detail(db, make, event_kw, restriction, expected) -> None:
    org = await make.organizer()
    ev = await classified(make, org=org, **event_kw)
    await clear(db, ev, restriction)
    promo = await promote(db, ev, org, start_date=d(1), end_date=d(5))
    assert (await listed(db))[promo.id]["paused_reason"] == expected
    assert (await promotion_detail(db, promo, NOW))["paused_reason"] == expected


@pytest.mark.asyncio
async def test_grant_context_lists_paused_reason(db, make) -> None:
    claimant = await make.organizer("Claimant")
    ev = await classified(make)
    await make.publisher_claim(ev, claimant, dormant=True)
    await clear(db, ev)
    promo = await promote(db, ev, claimant, start_date=d(1), end_date=d(5))
    ctx = await grant_context(db, ev, NOW)
    assert {p["id"]: p["paused_reason"] for p in ctx["promotions"]}[promo.id] == PROMOTION_NOT_SHOWING_NOT_OWNED


@pytest.mark.asyncio
async def test_showing_scheduled_and_unpaid_have_no_reason(db, make) -> None:
    org = await make.organizer()
    showing = await promote(db, await _owned(db, make, org, 0), org, start_date=d(1), end_date=d(5))
    scheduled = await promote(db, await _owned(db, make, org, 1), org, start_date=d(3), end_date=d(7))
    unpaid = await promote(
        db, await _owned(db, make, org, 2), org, start_date=d(1), end_date=d(5), status=PROMOTION_STATUS_UNPAID
    )
    rows = await listed(db)
    assert rows[showing.id]["paused_reason"] is None
    assert rows[scheduled.id]["paused_reason"] is None
    assert rows[unpaid.id]["paused_reason"] is None


@pytest.mark.asyncio
async def test_list_reason_is_the_shared_paused_reasons_mapping(db, make) -> None:
    claimant = await make.organizer("Claimant")
    ev = await classified(make)
    await make.publisher_claim(ev, claimant, dormant=True)
    await clear(db, ev)
    promo = await promote(db, ev, claimant, start_date=d(1), end_date=d(5))
    assert (await paused_reasons(db, [promo], NOW))[promo.id] == (await listed(db))[promo.id]["paused_reason"]


@pytest.mark.asyncio
async def test_list_query_count_is_fixed(db, make) -> None:
    async def count(n: int) -> int:
        org = await make.organizer()
        for i in range(n):
            await promote(db, await _owned(db, make, org, i), org, start_date=d(1), end_date=d(5))
        with count_statements(db) as seen:
            await listed(db)
        return len(seen)

    small = await count(1)
    large = await count(4)
    assert large == small


async def _owned(db, make, org, i: int):
    ev = await classified(make, i, org=org)
    await clear(db, ev)
    return ev
