"""The suggested refund for an admin: unused days plus paused days, priced at
what was paid per day. The admin edits it and adds the required note."""

from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from app.constants.core import TALLINN_TZ
from app.constants.promotions import (
    PROMOTION_GATE_OUTCOME_PAUSED,
    PROMOTION_INVOICE_SOURCE_STRIPE,
    PROMOTION_STATUS_ENDED_EARLY,
    PROMOTION_STATUS_PAID,
)
from app.models.models import Promotion, PromotionDailyStat
from app.promotions.grant import vat_cents
from app.promotions.windows import window_days


def used_through(promotion: Promotion, today: date) -> date:
    """The last window day that counts as used: today while live (the day is
    already running), the day it was ended for an early end, and the day
    before the start while scheduled."""
    if promotion.status == PROMOTION_STATUS_ENDED_EARLY and promotion.ended_at is not None:
        ended_day = promotion.ended_at.astimezone(TALLINN_TZ).date()
        return min(max(ended_day, promotion.start_date), promotion.end_date)
    last = min(today, promotion.end_date)
    return max(last, promotion.start_date - timedelta(days=1))


def refund_prefill(
    promotion: Promotion, stored: dict[date, PromotionDailyStat], today: date
) -> dict | None:
    """(unused days + paused days) x the gross price paid per day, capped at
    what is still refundable. None when the Promotion cannot be refunded."""
    if promotion.is_complimentary or promotion.status not in (
        PROMOTION_STATUS_PAID,
        PROMOTION_STATUS_ENDED_EARLY,
    ):
        return None
    gross = promotion.net_price_cents + vat_cents(
        promotion.net_price_cents, promotion.vat_rate_percent
    )
    remaining = max(gross - promotion.refunded_cents, 0)
    through = used_through(promotion, today)
    unused = max(promotion.end_date.toordinal() - through.toordinal(), 0)
    paused = sum(
        1
        for day, row in stored.items()
        if promotion.start_date <= day <= through and row.gate_outcome == PROMOTION_GATE_OUTCOME_PAUSED
    )
    days = max(window_days(promotion.start_date, promotion.end_date), 1)
    suggested = int(
        (Decimal(gross) * (unused + paused) / days).quantize(Decimal(1), ROUND_HALF_UP)
    )
    per_day = int((Decimal(gross) / days).quantize(Decimal(1), ROUND_HALF_UP))
    return {
        "mode": "stripe" if promotion.invoice_source == PROMOTION_INVOICE_SOURCE_STRIPE else "manual",
        "unused_days": unused,
        "paused_days": paused,
        "gross_per_day_cents": per_day,
        "suggested_cents": min(suggested, remaining),
        "remaining_cents": remaining,
    }
