"""The expiry sweep (#618): an `unpaid` card checkout is voided an hour after
its session expiry, silently. Manual unpaid Promotions are untouched."""

from datetime import timedelta

import pytest

from app.models.audit import AdminAction
from app.promotions.sweep import sweep_promotions
from sqlalchemy import select
from tests.promotions.conftest import NOW
from tests.promotions.test_lifecycle_commands import make_promo

EXPIRY = NOW + timedelta(minutes=30)


@pytest.mark.asyncio
async def test_stale_checkout_hold_is_voided_after_expiry_plus_an_hour(db, make, sent) -> None:
    _, promo = await make_promo(db, make, 10, 14)
    promo.checkout_expires_at = EXPIRY
    promo.stripe_checkout_session_id = "cs_test_1"

    await sweep_promotions(db, EXPIRY + timedelta(minutes=59))
    assert promo.status == "unpaid"  # still inside the grace

    result = await sweep_promotions(db, EXPIRY + timedelta(hours=1, seconds=1))
    assert promo.status == "void"
    assert promo.end_reason == "checkout_expired"
    assert result["voided"] == 1
    rows = (await db.scalars(select(AdminAction).where(AdminAction.target == str(promo.id)))).all()
    assert [(r.action, r.result["actor"]) for r in rows[-1:]] == [("promotion_system_void", "system")]
    assert sent == []  # abandoned checkouts are never emailed


@pytest.mark.asyncio
async def test_manual_unpaid_promotion_is_not_swept_by_the_checkout_rule(db, make, sent) -> None:
    _, promo = await make_promo(db, make, 10, 14)
    await sweep_promotions(db, EXPIRY + timedelta(hours=5))
    assert promo.status == "unpaid"
