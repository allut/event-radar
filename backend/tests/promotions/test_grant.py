"""Granting a Promotion: ownership, window, overlap, cap, price, complimentary."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.constants.promotions import (
    PROMOTION_ERROR_CAP_EXCEEDED,
    PROMOTION_ERROR_ENDS_AFTER_EVENT,
    PROMOTION_ERROR_INVALID_INVOICE_REFERENCE,
    PROMOTION_ERROR_INVALID_REGISTRY_CODE,
    PROMOTION_ERROR_INVOICE_ON_COMPLIMENTARY,
    PROMOTION_ERROR_NOTE_REQUIRED,
    PROMOTION_ERROR_NO_OWNER,
    PROMOTION_ERROR_OVERLAP,
    PROMOTION_ERROR_STARTS_TOO_EARLY,
    PROMOTION_ERROR_TOO_LONG,
    PROMOTION_ERROR_TOO_SHORT,
    PROMOTION_LIVE_CAP,
    PROMOTION_STATUS_PAID,
    PROMOTION_STATUS_UNPAID,
)
from app.models.models import Event, Promotion
from app.promotions.grant import GrantRequest, PromotionRefused, grant_promotion, validate_grant
from tests.promotions.conftest import NOW, at_tallinn, d


def req(start: date, end: date, **kw) -> GrantRequest:
    base = dict(
        start_date=start,
        end_date=end,
        advertiser_legal_name="Acme Events OÜ",
        advertiser_registry_code="12345678",
    )
    base.update(kw)
    return GrantRequest(**base)  # type: ignore[arg-type]


async def refused_codes(db, event, request, now=NOW) -> list[str]:
    with pytest.raises(PromotionRefused) as exc:
        await grant_promotion(db, event, request, now)
    return [v.code for v in exc.value.violations]


@pytest.mark.asyncio
async def test_grant_creates_promotion_owned_by_resolved_organizer(db, make) -> None:
    org = await make.organizer()
    ev = await make.event(submitted_by=org)
    promo = await grant_promotion(db, ev, req(d(10), d(14), billing_email="b@example.com"), NOW)
    assert promo.id is not None
    assert (promo.event_id, promo.organizer_id) == (ev.id, org.id)
    assert (promo.start_date, promo.end_date, promo.days) == (d(10), d(14), 5)
    assert promo.status == PROMOTION_STATUS_UNPAID
    assert promo.advertiser_legal_name == "Acme Events OÜ"
    assert promo.advertiser_registry_code == "12345678"
    assert promo.billing_email == "b@example.com"
    assert promo.granted_by == "admin"
    assert promo.paid_at is None


@pytest.mark.asyncio
async def test_grant_via_claim_owner(db, make) -> None:
    org = await make.organizer()
    ev = await make.event()
    await make.publisher_claim(ev, org)
    promo = await grant_promotion(db, ev, req(d(10), d(12)), NOW)
    assert promo.organizer_id == org.id


@pytest.mark.asyncio
async def test_grant_refused_when_event_has_no_owner(db, make) -> None:
    ev = await make.event()
    assert await refused_codes(db, ev, req(d(10), d(12))) == [PROMOTION_ERROR_NO_OWNER]
    assert (await db.scalars(select(Promotion).where(Promotion.event_id == ev.id))).all() == []


@pytest.mark.asyncio
async def test_priced_grant_stores_net_price_and_vat_rate(db, make) -> None:
    ev = await make.event(submitted_by=await make.organizer())
    promo = await grant_promotion(
        db, ev, req(d(10), d(14), invoice_reference="ER-M-2090-001"), NOW
    )
    assert promo.net_price_cents == 5 * 500
    assert promo.vat_rate_percent == Decimal("24.00")
    assert promo.is_complimentary is False
    assert (promo.invoice_reference, promo.invoice_source) == ("ER-M-2090-001", "manual")


@pytest.mark.asyncio
async def test_complimentary_requires_note(db, make) -> None:
    ev = await make.event(submitted_by=await make.organizer())
    assert await refused_codes(db, ev, req(d(10), d(12), is_complimentary=True)) == [
        PROMOTION_ERROR_NOTE_REQUIRED
    ]
    assert await refused_codes(
        db, ev, req(d(10), d(12), is_complimentary=True, complimentary_note="   ")
    ) == [PROMOTION_ERROR_NOTE_REQUIRED]


@pytest.mark.asyncio
async def test_complimentary_is_stored_paid_at_zero(db, make) -> None:
    ev = await make.event(submitted_by=await make.organizer())
    promo = await grant_promotion(
        db, ev, req(d(10), d(12), is_complimentary=True, complimentary_note="Pilot with the venue"), NOW
    )
    assert promo.status == PROMOTION_STATUS_PAID
    assert promo.net_price_cents == 0
    assert promo.is_complimentary is True
    assert promo.complimentary_note == "Pilot with the venue"
    assert promo.paid_at == NOW
    assert promo.invoice_reference is None


@pytest.mark.asyncio
async def test_complimentary_refuses_an_invoice_reference(db, make) -> None:
    ev = await make.event(submitted_by=await make.organizer())
    got = await refused_codes(
        db,
        ev,
        req(d(10), d(12), is_complimentary=True, complimentary_note="x", invoice_reference="ER-M-1"),
    )
    assert got == [PROMOTION_ERROR_INVOICE_ON_COMPLIMENTARY]


@pytest.mark.asyncio
async def test_field_validation(db, make) -> None:
    ev = await make.event(submitted_by=await make.organizer())
    assert await refused_codes(
        db, ev, req(d(10), d(12), advertiser_registry_code="12AB")
    ) == [PROMOTION_ERROR_INVALID_REGISTRY_CODE]
    assert await refused_codes(
        db, ev, req(d(10), d(12), invoice_reference="INV-1")
    ) == [PROMOTION_ERROR_INVALID_INVOICE_REFERENCE]


@pytest.mark.asyncio
async def test_window_rules_are_enforced(db, make) -> None:
    ev = await make.event(submitted_by=await make.organizer())
    assert await refused_codes(db, ev, req(d(10), d(11))) == [PROMOTION_ERROR_TOO_SHORT]
    assert await refused_codes(db, ev, req(d(10), d(24))) == [PROMOTION_ERROR_TOO_LONG]
    # NOW is 2090-01-01 10:00 Tallinn, so tomorrow is the 2nd.
    assert await refused_codes(db, ev, req(d(1), d(3))) == [PROMOTION_ERROR_STARTS_TOO_EARLY]
    assert (await grant_promotion(db, ev, req(d(2), d(4)), NOW)).start_date == d(2)


@pytest.mark.asyncio
async def test_start_cutoff_moves_at_tallinn_midnight(db, make) -> None:
    ev = await make.event(submitted_by=await make.organizer())
    just_before = at_tallinn(2090, 1, 1, 23, 59, 59)
    just_after = at_tallinn(2090, 1, 2, 0, 0, 0)
    assert (await grant_promotion(db, ev, req(d(2), d(4)), just_before)).start_date == d(2)
    ev2 = await make.event(submitted_by=await make.organizer())
    assert await refused_codes(db, ev2, req(d(2), d(4)), just_after) == [
        PROMOTION_ERROR_STARTS_TOO_EARLY
    ]
    assert (await grant_promotion(db, ev2, req(d(3), d(5)), just_after)).start_date == d(3)


@pytest.mark.asyncio
async def test_must_end_on_or_before_events_last_tallinn_day(db, make) -> None:
    # Event ends 2090-01-20 00:30 Tallinn = 2090-01-19 in UTC: the Tallinn day wins.
    ev = await make.event(
        submitted_by=await make.organizer(),
        starts_at=at_tallinn(2090, 1, 19, 20),
        ends_at=at_tallinn(2090, 1, 20, 0, 30),
    )
    assert await refused_codes(db, ev, req(d(18), d(21))) == [PROMOTION_ERROR_ENDS_AFTER_EVENT]
    assert (await grant_promotion(db, ev, req(d(18), d(20)), NOW)).end_date == d(20)


@pytest.mark.asyncio
async def test_event_without_end_uses_start_day(db, make) -> None:
    ev = await make.event(
        submitted_by=await make.organizer(),
        starts_at=at_tallinn(2090, 1, 12, 19),
        ends_at=None,
    )
    assert await refused_codes(db, ev, req(d(10), d(13))) == [PROMOTION_ERROR_ENDS_AFTER_EVENT]
    assert (await grant_promotion(db, ev, req(d(10), d(12)), NOW)).end_date == d(12)


@pytest.mark.asyncio
async def test_overlap_refused_but_back_to_back_allowed(db, make) -> None:
    ev = await make.event(submitted_by=await make.organizer())
    await grant_promotion(db, ev, req(d(10), d(14)), NOW)
    assert await refused_codes(db, ev, req(d(14), d(16))) == [PROMOTION_ERROR_OVERLAP]
    assert await refused_codes(db, ev, req(d(8), d(10))) == [PROMOTION_ERROR_OVERLAP]
    assert (await grant_promotion(db, ev, req(d(15), d(17)), NOW)).start_date == d(15)
    assert (await grant_promotion(db, ev, req(d(7), d(9)), NOW)).end_date == d(9)


@pytest.mark.asyncio
async def test_void_and_ended_early_do_not_block_overlap(db, make) -> None:
    ev = await make.event(submitted_by=await make.organizer())
    first = await grant_promotion(db, ev, req(d(10), d(14)), NOW)
    first.status = "void"
    await db.flush()
    assert (await grant_promotion(db, ev, req(d(10), d(14)), NOW)).id != first.id


async def fill_day(db, make, day_start: date, day_end: date, count: int) -> list[Event]:
    events = []
    for _ in range(count):
        e = await make.event(submitted_by=await make.organizer())
        await grant_promotion(db, e, req(day_start, day_end), NOW)
        events.append(e)
    return events


@pytest.mark.asyncio
async def test_cap_refuses_a_sixth_on_any_day_of_the_window(db, make) -> None:
    await fill_day(db, make, d(12), d(14), PROMOTION_LIVE_CAP)
    ev = await make.event(submitted_by=await make.organizer())
    # Overlaps the full days only at the window's last day.
    got = await refused_codes(db, ev, req(d(10), d(12)))
    assert got == [PROMOTION_ERROR_CAP_EXCEEDED]
    # Touching no full day is fine.
    assert (await grant_promotion(db, ev, req(d(9), d(11)), NOW)).start_date == d(9)


@pytest.mark.asyncio
async def test_cap_counts_paid_and_unpaid_but_not_void(db, make) -> None:
    events = await fill_day(db, make, d(12), d(14), PROMOTION_LIVE_CAP)
    promos = (await db.scalars(select(Promotion).where(Promotion.event_id == events[0].id))).all()
    promos[0].status = "void"
    await db.flush()
    ev = await make.event(submitted_by=await make.organizer())
    assert (await grant_promotion(db, ev, req(d(12), d(14)), NOW)).days == 3


@pytest.mark.asyncio
async def test_cap_applies_to_complimentary_grants_too(db, make) -> None:
    await fill_day(db, make, d(12), d(14), PROMOTION_LIVE_CAP)
    ev = await make.event(submitted_by=await make.organizer())
    got = await refused_codes(
        db, ev, req(d(12), d(14), is_complimentary=True, complimentary_note="pilot")
    )
    assert got == [PROMOTION_ERROR_CAP_EXCEEDED]


@pytest.mark.asyncio
async def test_validate_grant_reports_every_problem_without_writing(db, make) -> None:
    await fill_day(db, make, d(12), d(14), PROMOTION_LIVE_CAP)
    ev = await make.event(submitted_by=await make.organizer())
    await grant_promotion(db, ev, req(d(2), d(4)), NOW)
    violations = await validate_grant(db, ev, d(3), d(13), NOW)
    codes = [v.code for v in violations]
    assert PROMOTION_ERROR_OVERLAP in codes
    assert PROMOTION_ERROR_CAP_EXCEEDED in codes
    cap = next(v for v in violations if v.code == PROMOTION_ERROR_CAP_EXCEEDED)
    assert cap.dates == [d(12), d(13)]
    total = (await db.scalars(select(Promotion).where(Promotion.event_id == ev.id))).all()
    assert len(total) == 1


@pytest.mark.asyncio
async def test_granting_never_touches_the_events_updated_at(db, make) -> None:
    ev = await make.event(submitted_by=await make.organizer())
    before = ev.updated_at
    await grant_promotion(db, ev, req(d(10), d(14)), NOW)
    await db.refresh(ev)
    assert ev.updated_at == before


@pytest.mark.asyncio
async def test_bulk_validation_keeps_an_overlong_window_from_widening_the_load(
    db, make, monkeypatch
) -> None:
    from app.promotions import grant as grant_module
    from app.promotions.grant import validate_grants

    far = await make.event(
        submitted_by=await make.organizer(),
        starts_at=at_tallinn(2095, 1, 1, 19),
        ends_at=at_tallinn(2095, 1, 31, 22),
    )
    await grant_promotion(db, far, req(date(2095, 1, 10), date(2095, 1, 14)), NOW)
    long_ev = await make.event(submitted_by=await make.organizer())
    await grant_promotion(db, long_ev, req(d(12), d(16)), NOW)
    short_ev = await make.event(submitted_by=await make.organizer())
    seen: list[tuple[str, date, date]] = []
    real_tally = grant_module.tally_cap_days

    def spy(rows, start, end, today):
        rows = list(rows)
        seen.extend(rows)
        return real_tally(rows, start, end, today)

    monkeypatch.setattr(grant_module, "tally_cap_days", spy)

    long_found, short_found = await validate_grants(
        db, [(long_ev, d(10), date(2096, 1, 1)), (short_ev, d(20), d(24))], NOW
    )

    assert PROMOTION_ERROR_OVERLAP in [v.code for v in long_found]
    assert short_found == []
    assert all(start.year == 2090 for _, start, _ in seen)  # 2095 never loaded
