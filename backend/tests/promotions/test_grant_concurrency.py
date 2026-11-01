"""Two simultaneous grants, or a grant and an edit, for the last cap day:
exactly one holds it.

Needs real commits across two connections, so it cleans up after itself
instead of relying on the rollback fixture.
"""

import asyncio

import pytest
from sqlalchemy import delete, func, select

from app.constants.promotions import PROMOTION_LIVE_CAP
from app.models.events import Event
from app.models.promotions import Promotion, PromotionSnapshot
from app.models.organizers import Organizer
from app.promotions import grant as grant_module
from app.promotions.grant import GrantRequest, PromotionRefused, grant_promotion
from app.promotions.lifecycle import edit_promotion
from tests.conftest import Factory
from tests.promotions.conftest import NOW, d


@pytest.mark.asyncio
async def test_two_concurrent_grants_for_the_last_cap_day_leave_exactly_one(
    engine, sessionmaker_for, monkeypatch
) -> None:
    # Widen the check-then-insert gap so an unserialized pair would both pass
    # the cap check before either inserts.
    real_validate_grants = grant_module.validate_grants

    async def slow_validate_grants(*args, **kwargs):
        result = await real_validate_grants(*args, **kwargs)
        await asyncio.sleep(0.3)
        return result

    monkeypatch.setattr(grant_module, "validate_grants", slow_validate_grants)
    created_events: list[int] = []
    created_orgs: list[int] = []
    day = (d(20), d(22))

    def request() -> GrantRequest:
        return GrantRequest(
            start_date=day[0],
            end_date=day[1],
            advertiser_legal_name="Acme OÜ",
            advertiser_registry_code="12345678",
        )

    try:
        async with sessionmaker_for() as setup:
            make = Factory(setup)
            for _ in range(PROMOTION_LIVE_CAP - 1):
                org = await make.organizer()
                ev = await make.event(submitted_by=org)
                created_orgs.append(org.id)
                created_events.append(ev.id)
                await grant_promotion(setup, ev, request(), NOW)
            racers = []
            for _ in range(2):
                org = await make.organizer()
                ev = await make.event(submitted_by=org)
                created_orgs.append(org.id)
                created_events.append(ev.id)
                racers.append(ev.id)
            await setup.commit()

        async def attempt(event_id: int) -> bool:
            async with sessionmaker_for() as s:
                ev = await s.get(Event, event_id)
                assert ev is not None
                try:
                    await grant_promotion(s, ev, request(), NOW)
                except PromotionRefused:
                    await s.rollback()
                    return False
                await s.commit()
                return True

        results = await asyncio.gather(*(attempt(e) for e in racers))

        assert sorted(results) == [False, True]
        async with sessionmaker_for() as check:
            held = await check.scalar(
                select(func.count()).select_from(Promotion).where(
                    Promotion.event_id.in_(created_events),
                    Promotion.start_date <= day[1],
                    Promotion.end_date >= day[0],
                )
            )
        assert held == PROMOTION_LIVE_CAP
    finally:
        async with sessionmaker_for() as cleanup:
            await cleanup.execute(delete(Promotion).where(Promotion.event_id.in_(created_events)))
            await cleanup.execute(delete(Event).where(Event.id.in_(created_events)))
            await cleanup.execute(delete(Organizer).where(Organizer.id.in_(created_orgs)))
            await cleanup.commit()


@pytest.mark.asyncio
async def test_a_grant_and_an_edit_racing_for_the_last_cap_day_leave_exactly_one(
    engine, sessionmaker_for, monkeypatch
) -> None:
    real_validate_grants = grant_module.validate_grants

    async def slow_validate_grants(*args, **kwargs):
        result = await real_validate_grants(*args, **kwargs)
        await asyncio.sleep(0.3)
        return result

    monkeypatch.setattr(grant_module, "validate_grants", slow_validate_grants)
    created_events: list[int] = []
    created_orgs: list[int] = []

    try:
        async with sessionmaker_for() as setup:
            make = Factory(setup)

            async def new_event() -> Event:
                org = await make.organizer()
                ev = await make.event(submitted_by=org)
                created_orgs.append(org.id)
                created_events.append(ev.id)
                return ev

            for _ in range(PROMOTION_LIVE_CAP - 1):
                await grant_promotion(
                    setup, await new_event(), GrantRequest(d(21), d(23), "A", "12345678"), NOW
                )
            editor = await grant_promotion(
                setup, await new_event(), GrantRequest(d(18), d(20), "A", "12345678"), NOW
            )
            editor_id = editor.id
            grantee_id = (await new_event()).id
            await setup.commit()

        async def grant_attempt() -> bool:
            async with sessionmaker_for() as s:
                ev = await s.get(Event, grantee_id)
                assert ev is not None
                try:
                    await grant_promotion(s, ev, GrantRequest(d(21), d(23), "A", "12345678"), NOW)
                except PromotionRefused:
                    await s.rollback()
                    return False
                await s.commit()
                return True

        async def edit_attempt() -> bool:
            async with sessionmaker_for() as s:
                try:
                    await edit_promotion(s, editor_id, {"end_date": d(22)}, NOW)
                except PromotionRefused:
                    await s.rollback()
                    return False
                await s.commit()
                return True

        results = await asyncio.gather(grant_attempt(), edit_attempt())

        assert sorted(results) == [False, True]
        async with sessionmaker_for() as check:
            held = await check.scalar(
                select(func.count()).select_from(Promotion).where(
                    Promotion.event_id.in_(created_events),
                    Promotion.start_date <= d(22),
                    Promotion.end_date >= d(22),
                )
            )
        assert held == PROMOTION_LIVE_CAP
    finally:
        async with sessionmaker_for() as cleanup:
            ids = select(Promotion.id).where(Promotion.event_id.in_(created_events))
            await cleanup.execute(delete(PromotionSnapshot).where(PromotionSnapshot.promotion_id.in_(ids)))
            await cleanup.execute(delete(Promotion).where(Promotion.event_id.in_(created_events)))
            await cleanup.execute(delete(Event).where(Event.id.in_(created_events)))
            await cleanup.execute(delete(Organizer).where(Organizer.id.in_(created_orgs)))
            await cleanup.commit()
