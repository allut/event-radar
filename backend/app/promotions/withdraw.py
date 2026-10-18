"""Withdraw (#620): end a Promotion because the Operator pulled the feature.

Each command ends the paid Promotion with `feature_withdrawn` and records a
full refund of its unused whole days. Today counts as used, so a live
Promotion keeps today; a scheduled one is refunded in full. A complimentary
Promotion has nothing to refund. The caller adds the audit rows, commits and
emails the Organizer.

A card-paid Promotion is refunded through the payment gateway. That call
commits the session, so the refund runs first and the Promotion ends only once
it succeeded; a provider failure leaves the Promotion paid and untouched.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.promotions import (
    PROMOTION_END_REASON_FEATURE_WITHDRAWN,
    PROMOTION_ERROR_REFUND_PROVIDER,
    PROMOTION_INVOICE_SOURCE_STRIPE,
    PROMOTION_STATUS_PAID,
    PROMOTION_WITHDRAWN_NOTE,
    PROMOTION_WITHDRAWN_REFUND_NOTE,
)
from app.models.models import Promotion
from app.promotions.grant import PromotionRefused, vat_cents
from app.integrations.payments import PaymentGateway, PaymentProviderError
from app.promotions.lifecycle import PromotionNotFound, end_early, record_refund
from app.promotions.windows import tallinn_today

log = logging.getLogger(__name__)


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
    db: AsyncSession,
    promotion_id: int,
    now: datetime,
    gateway: PaymentGateway | None = None,
) -> WithdrawResult:
    """End one paid, unfinished Promotion with `feature_withdrawn` and record
    the refund (issued through `gateway` when it was paid by card). Raises
    `PromotionRefused` (nothing written) when it is not `paid` or already
    finished, and `PaymentProviderError` when Stripe refuses (it stays paid)."""
    today = tallinn_today(now)
    current = await db.get(Promotion, promotion_id, populate_existing=True)
    if current is None:
        raise PromotionNotFound(promotion_id)
    card_paid = (
        current.invoice_source == PROMOTION_INVOICE_SOURCE_STRIPE
        and current.status == PROMOTION_STATUS_PAID
        and today <= current.end_date
    )
    if card_paid:
        # record_refund commits around the Stripe call, so refund before ending:
        # a failed refund then leaves a paid Promotion, never an ended unrefunded one.
        unused = unused_days(current, today)
        refund = refund_for_unused(current, unused)
        if refund > 0:
            await record_refund(
                db, promotion_id, refund, PROMOTION_WITHDRAWN_REFUND_NOTE, now, gateway=gateway
            )
    promotion = await end_early(
        db,
        promotion_id,
        PROMOTION_WITHDRAWN_NOTE,
        now,
        end_reason=PROMOTION_END_REASON_FEATURE_WITHDRAWN,
    )
    if not card_paid:
        unused = unused_days(promotion, today)
        refund = refund_for_unused(promotion, unused)
        if refund > 0:
            await record_refund(db, promotion.id, refund, PROMOTION_WITHDRAWN_REFUND_NOTE, now)
    return WithdrawResult(promotion, unused, refund)


async def withdraw_all(
    db: AsyncSession, now: datetime, gateway: PaymentGateway | None = None
) -> WithdrawAllResult:
    """Withdraw every paid Promotion that has not finished. One failing
    Promotion is listed in `skipped` (a refused one wrote nothing; a card
    refund Stripe refused leaves it paid), so it never blocks the rest. Each
    Promotion is committed on its own, because a card refund commits. The id
    list is one query."""
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
            result.withdrawn.append(await withdraw_promotion(db, promotion_id, now, gateway))
        except PromotionRefused as refused:
            result.skipped.append({"id": promotion_id, "code": refused.violations[0].code})
        except PaymentProviderError:
            log.error("Withdraw refund refused by Stripe (promotion_id=%s)", promotion_id, exc_info=True)
            result.skipped.append({"id": promotion_id, "code": PROMOTION_ERROR_REFUND_PROVIDER})
        await db.commit()  # one Promotion per transaction; also frees the locks
    return result
