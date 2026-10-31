"""Two simultaneous checkouts for the last cap day leave exactly one holding it
(#618). Needs real commits across connections, so it cleans up after itself."""

import asyncio

import pytest
from sqlalchemy import delete, func, select

from app.constants.promotions import PROMOTION_LIVE_CAP
from app.models.events import Event
from app.models.promotions import Promotion
from app.models.organizers import Organizer
from app.promotions import grant as grant_module
from app.promotions.checkout import CheckoutInput, start_checkout
from app.promotions.grant import GrantRequest, PromotionRefused, grant_promotion
from tests.conftest import Factory
from tests.promotions.conftest import NOW, d
from tests.promotions.fakes import FakePaymentGateway, FakeRegistry


@pytest.mark.asyncio
async def test_two_simultaneous_checkouts_for_the_last_cap_day_leave_exactly_one(
    engine, sessionmaker_for, monkeypatch
) -> None:
    real_validate_grants = grant_module.validate_grants

    async def slow_validate_grants(*args, **kwargs):
        result = await real_validate_grants(*args, **kwargs)
        await asyncio.sleep(0.3)  # widen the check-then-insert gap
        return result

    monkeypatch.setattr(grant_module, "validate_grants", slow_validate_grants)
    gateway, registry = FakePaymentGateway(), FakeRegistry()
    registry.found("12345678", "Acme OÜ")
    created_events: list[int] = []
    created_orgs: list[int] = []
    window = (d(25), d(29))

    try:
        async with sessionmaker_for() as setup:
            make = Factory(setup)
            for _ in range(PROMOTION_LIVE_CAP - 1):
                org = await make.organizer()
                ev = await make.event(submitted_by=org)
                created_orgs.append(org.id)
                created_events.append(ev.id)
                await grant_promotion(
                    setup, ev, GrantRequest(window[0], window[1], "Acme OÜ", "12345678"), NOW
                )
            racers: list[tuple[int, int]] = []
            for _ in range(2):
                org = await make.organizer()
                ev = await make.event(submitted_by=org, promotion_restriction="none")
                created_orgs.append(org.id)
                created_events.append(ev.id)
                racers.append((org.id, ev.id))
            await setup.commit()

        async def attempt(organizer_id: int, event_id: int) -> bool:
            async with sessionmaker_for() as s:
                organizer = await s.get(Organizer, organizer_id)
                assert organizer is not None
                try:
                    await start_checkout(
                        s,
                        gateway,
                        registry,
                        organizer,
                        CheckoutInput(
                            event_id=event_id,
                            start_date=window[0],
                            end_date=window[1],
                            registry_code="12345678",
                            billing_email=None,
                            content_policy_attested=True,
                            business_attested=True,
                            terms_accepted=True,
                        ),
                        NOW,
                    )
                except PromotionRefused:
                    return False
                return True

        results = await asyncio.gather(*(attempt(o, e) for o, e in racers))

        assert sorted(results) == [False, True]
        assert len(gateway.sessions) == 1  # the loser never reached Stripe
        async with sessionmaker_for() as check:
            held = await check.scalar(
                select(func.count()).select_from(Promotion).where(
                    Promotion.event_id.in_(created_events),
                    Promotion.start_date <= window[1],
                    Promotion.end_date >= window[0],
                )
            )
        assert held == PROMOTION_LIVE_CAP
    finally:
        async with sessionmaker_for() as cleanup:
            await cleanup.execute(delete(Promotion).where(Promotion.event_id.in_(created_events)))
            await cleanup.execute(delete(Event).where(Event.id.in_(created_events)))
            await cleanup.execute(delete(Organizer).where(Organizer.id.in_(created_orgs)))
            await cleanup.commit()
