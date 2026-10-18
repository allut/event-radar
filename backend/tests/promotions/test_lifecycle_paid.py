"""Mark paid and content snapshots, with the clock frozen around Tallinn midnight."""

import pytest
from sqlalchemy import select

from app.constants.promotions import (
    PROMOTION_ERROR_ALREADY_STARTED,
    PROMOTION_ERROR_INVALID_INVOICE_REFERENCE,
    PROMOTION_ERROR_INVALID_TRANSITION,
    PROMOTION_STATUS_PAID,
    PROMOTION_STATUS_UNPAID,
)
from app.models.models import PromotionSnapshot
from app.promotions.grant import GrantRequest, PromotionRefused, grant_promotion
from app.promotions.lifecycle import mark_paid
from tests.promotions.conftest import NOW, at_tallinn, d


async def unpaid(db, make, start=10, end=14, **event_kw):
    org = await make.organizer()
    ev = await make.event(submitted_by=org, **event_kw)
    promo = await grant_promotion(db, ev, GrantRequest(d(start), d(end), "Acme OÜ", "12345678"), NOW)
    return ev, promo


async def snapshots(db, promo) -> list[PromotionSnapshot]:
    return list(
        (
            await db.scalars(
                select(PromotionSnapshot)
                .where(PromotionSnapshot.promotion_id == promo.id)
                .order_by(PromotionSnapshot.id)
            )
        ).all()
    )


async def codes_of(coro) -> list[str]:
    with pytest.raises(PromotionRefused) as exc:
        await coro
    return [v.code for v in exc.value.violations]


@pytest.mark.asyncio
async def test_mark_paid_sets_paid_and_takes_a_snapshot(db, make) -> None:
    ev, promo = await unpaid(db, make, image_url="https://img.example/a.jpg", venue_name="Hall A")
    ev.title_localized = {"et": "Etendus", "en": "Show", "ru": "Шоу"}
    ev.description_orig = "x" * 500
    await db.flush()
    assert await snapshots(db, promo) == []

    await mark_paid(db, promo.id, NOW)

    assert promo.status == PROMOTION_STATUS_PAID
    assert promo.paid_at == NOW
    (snap,) = await snapshots(db, promo)
    assert (snap.title_et, snap.title_en, snap.title_ru) == ("Etendus", "Show", "Шоу")
    assert snap.description_excerpt is not None and len(snap.description_excerpt) <= 300
    assert snap.image_url == "https://img.example/a.jpg"
    assert snap.venue_name == "Hall A"
    assert (snap.start_date, snap.end_date) == (d(10), d(14))
    assert snap.net_price_cents == 2500
    assert snap.label_text == "REKLAAM · Acme OÜ"
    assert snap.trigger == "mark_paid"


@pytest.mark.asyncio
async def test_mark_paid_may_record_the_invoice_reference(db, make) -> None:
    _, promo = await unpaid(db, make)
    await mark_paid(db, promo.id, NOW, invoice_reference="ER-M-2090-1")
    assert (promo.invoice_reference, promo.invoice_source) == ("ER-M-2090-1", "manual")
    _, bad = await unpaid(db, make)
    assert await codes_of(mark_paid(db, bad.id, NOW, invoice_reference="X-1")) == [
        PROMOTION_ERROR_INVALID_INVOICE_REFERENCE
    ]


@pytest.mark.asyncio
async def test_mark_paid_allowed_until_tallinn_midnight_before_start(db, make) -> None:
    _, promo = await unpaid(db, make, start=10, end=14)
    just_before = at_tallinn(2090, 1, 9, 23, 59, 59)
    await mark_paid(db, promo.id, just_before)
    assert promo.status == PROMOTION_STATUS_PAID


@pytest.mark.asyncio
async def test_mark_paid_refused_from_start_date_midnight(db, make) -> None:
    _, promo = await unpaid(db, make, start=10, end=14)
    midnight = at_tallinn(2090, 1, 10, 0, 0, 0)
    assert await codes_of(mark_paid(db, promo.id, midnight)) == [PROMOTION_ERROR_ALREADY_STARTED]
    assert promo.status == PROMOTION_STATUS_UNPAID
    assert await snapshots(db, promo) == []


@pytest.mark.asyncio
async def test_mark_paid_only_from_unpaid(db, make) -> None:
    _, promo = await unpaid(db, make)
    await mark_paid(db, promo.id, NOW)
    assert await codes_of(mark_paid(db, promo.id, NOW)) == [PROMOTION_ERROR_INVALID_TRANSITION]


@pytest.mark.asyncio
async def test_complimentary_grant_takes_a_grant_snapshot(db, make) -> None:
    org = await make.organizer()
    ev = await make.event(submitted_by=org)
    promo = await grant_promotion(
        db,
        ev,
        GrantRequest(d(10), d(14), "Acme OÜ", "12345678", is_complimentary=True, complimentary_note="pilot"),
        NOW,
    )
    (snap,) = await snapshots(db, promo)
    assert (snap.trigger, snap.net_price_cents) == ("grant", 0)


@pytest.mark.asyncio
async def test_priced_grant_takes_no_snapshot_until_paid(db, make) -> None:
    _, promo = await unpaid(db, make)
    assert await snapshots(db, promo) == []
