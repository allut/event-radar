"""Withdraw (#620): end a Promotion because the Operator pulled the feature.

Each command ends the paid Promotion with `feature_withdrawn` and records a
full refund of its unused whole days. Today counts as used, so a live
Promotion keeps today; a scheduled one is refunded in full. A complimentary
Promotion has nothing to refund. The caller adds the audit rows, commits and
emails the Organizer.
"""

from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.promotions import (
    PROMOTION_END_REASON_FEATURE_WITHDRAWN,
    PROMOTION_STATUS_PAID,
    PROMOTION_WITHDRAWN_NOTE,
    PROMOTION_WITHDRAWN_REFUND_NOTE,
)
from app.models.models import Promotion
from app.promotions.grant import PromotionRefused, vat_cents
from app.promotions.lifecycle import end_early, record_refund
from app.promotions.windows import tallinn_today


@dataclass(frozen=True)
class WithdrawResult:
    promotion: Promotion
    unused_days: int
    refund_cents: int


@dataclass
class WithdrawAllResult:
    withdrawn: list[WithdrawResult] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)


def unused_days(promotion: Promotion, today: date) -> int:
    """Whole days of the window that never started: all of them while
    scheduled, the days after today while live."""
    if promotion.start_date > today:
        return promotion.days
    return max((promotion.end_date - today).days, 0)


def refund_for_unused(promotion: Promotion, unused: int) -> int:
    """Gross cents owed for `unused` days, never beyond what is still
    refundable. The whole window refunds the exact amount charged."""
    if promotion.is_complimentary or unused <= 0:
        return 0
    gross = promotion.net_price_cents + vat_cents(
        promotion.net_price_cents, promotion.vat_rate_percent
    )
    if unused >= promotion.days:
        owed = gross
    else:
        net = promotion.net_price_cents * unused // promotion.days
        owed = net + vat_cents(net, promotion.vat_rate_percent)
    return max(min(owed, gross - promotion.refunded_cents), 0)


async def withdraw_promotion(
    db: AsyncSession, promotion_id: int, now: datetime
) -> WithdrawResult:
    """End one paid, unfinished Promotion with `feature_withdrawn` and record
    the refund. Raises `PromotionRefused` (nothing written) when it is not
    `paid` or already finished."""
    promotion = await end_early(
        db,
        promotion_id,
        PROMOTION_WITHDRAWN_NOTE,
        now,
        end_reason=PROMOTION_END_REASON_FEATURE_WITHDRAWN,
    )
    unused = unused_days(promotion, tallinn_today(now))
    refund = refund_for_unused(promotion, unused)
    if refund > 0:
        await record_refund(db, promotion.id, refund, PROMOTION_WITHDRAWN_REFUND_NOTE, now)
    return WithdrawResult(promotion, unused, refund)


async def withdraw_all(db: AsyncSession, now: datetime) -> WithdrawAllResult:
    """Withdraw every paid Promotion that has not finished. One failing
    Promotion is rolled back to its savepoint and listed in `skipped`, so it
    never blocks the rest. The id list is one query."""
    today = tallinn_today(now)
    ids = (
        await db.scalars(
            select(Promotion.id)
            .where(Promotion.status == PROMOTION_STATUS_PAID, Promotion.end_date >= today)
            .order_by(Promotion.id)
        )
    ).all()
    result = WithdrawAllResult()
    for promotion_id in ids:
        try:
            async with db.begin_nested():
                result.withdrawn.append(await withdraw_promotion(db, promotion_id, now))
        except PromotionRefused as refused:
            result.skipped.append(
                {"id": promotion_id, "code": refused.violations[0].code}
            )
    return result
