"""Admin direct grant of a Promotion: validation, pricing and the serialized
cap check-and-insert. The caller owns the transaction: it adds the audit row
after this returns and commits, which also releases the cap lock."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.promotions import (
    PROMOTION_DAY_PRICE_CENTS,
    PROMOTION_ERROR_CAP_EXCEEDED,
    PROMOTION_ERROR_INVALID_INVOICE_REFERENCE,
    PROMOTION_ERROR_INVALID_REGISTRY_CODE,
    PROMOTION_ERROR_INVOICE_ON_COMPLIMENTARY,
    PROMOTION_ERROR_NOTE_REQUIRED,
    PROMOTION_ERROR_NO_OWNER,
    PROMOTION_ERROR_OVERLAP,
    PROMOTION_GRANTED_BY_ADMIN,
    PROMOTION_HOLDING_STATUSES,
    PROMOTION_INVOICE_REFERENCE_RE,
    PROMOTION_INVOICE_SOURCE_MANUAL,
    PROMOTION_REGISTRY_CODE_RE,
    PROMOTION_SNAPSHOT_TRIGGER_GRANT,
    PROMOTION_STATUS_PAID,
    PROMOTION_STATUS_UNPAID,
    PROMOTION_VAT_RATE_PERCENT,
)
from app.models.models import Event, Promotion
from app.promotions.cap import full_days, lock_cap
from app.promotions.owners import resolve_owner_ids
from app.promotions.restriction import clearance_violations, is_restricted, record_clearance
from app.promotions.snapshots import take_snapshot
from app.promotions.windows import (
    RuleViolation,
    event_last_day,
    tallinn_today,
    window_days,
    window_violations,
)


class PromotionRefused(Exception):
    """A grant broke one or more rules; nothing was written."""

    def __init__(self, violations: list[RuleViolation]) -> None:
        super().__init__(", ".join(v.code for v in violations))
        self.violations = violations


@dataclass(frozen=True)
class GrantRequest:
    start_date: date
    end_date: date
    advertiser_legal_name: str
    advertiser_registry_code: str
    billing_email: str | None = None
    is_complimentary: bool = False
    complimentary_note: str | None = None
    invoice_reference: str | None = None
    # Restriction clearance (#612): required when the event is restricted.
    restriction_clearance_confirmed: bool = False
    restriction_clearance_note: str | None = None


def vat_cents(net_cents: int, vat_rate_percent: Decimal) -> int:
    return int((Decimal(net_cents) * vat_rate_percent / 100).quantize(Decimal(1), ROUND_HALF_UP))


def net_price_cents(days: int, is_complimentary: bool) -> int:
    return 0 if is_complimentary else days * PROMOTION_DAY_PRICE_CENTS


def request_violations(request: GrantRequest) -> list[RuleViolation]:
    found: list[RuleViolation] = []
    if request.is_complimentary and not (request.complimentary_note or "").strip():
        found.append(RuleViolation(PROMOTION_ERROR_NOTE_REQUIRED))
    if not PROMOTION_REGISTRY_CODE_RE.match(request.advertiser_registry_code):
        found.append(RuleViolation(PROMOTION_ERROR_INVALID_REGISTRY_CODE))
    if request.invoice_reference:
        if request.is_complimentary:
            found.append(RuleViolation(PROMOTION_ERROR_INVOICE_ON_COMPLIMENTARY))
        elif not PROMOTION_INVOICE_REFERENCE_RE.match(request.invoice_reference):
            found.append(RuleViolation(PROMOTION_ERROR_INVALID_INVOICE_REFERENCE))
    return found


async def validate_grant(
    db: AsyncSession,
    event: Event,
    start: date,
    end: date,
    now: datetime,
    exclude_promotion_id: int | None = None,
) -> list[RuleViolation]:
    """Window, overlap and cap violations for a candidate window (no owner or
    field checks, no lock, no write). Backs the live date validation; the
    grant itself re-runs the same checks under the cap lock. An edit passes
    `exclude_promotion_id` so the Promotion doesn't collide with itself."""
    today = tallinn_today(now)
    found = window_violations(start, end, today, event_last_day(event))
    if end < start:
        return found
    overlap_query = select(Promotion.id).where(
        Promotion.event_id == event.id,
        Promotion.status.in_(PROMOTION_HOLDING_STATUSES),
        Promotion.start_date <= end,
        Promotion.end_date >= start,
    )
    if exclude_promotion_id is not None:
        overlap_query = overlap_query.where(Promotion.id != exclude_promotion_id)
    overlapping = (await db.scalars(overlap_query)).first()
    if overlapping is not None:
        found.append(RuleViolation(PROMOTION_ERROR_OVERLAP))
    # An out-of-bounds window can span years; cap-check only a sane span.
    if window_days(start, end) <= 366:
        full = await full_days(db, start, end, today, exclude_promotion_id)
        if full:
            found.append(RuleViolation(PROMOTION_ERROR_CAP_EXCEEDED, full))
    return found


async def grant_promotion(
    db: AsyncSession, event: Event, request: GrantRequest, now: datetime
) -> Promotion:
    """Create a Promotion for `event`, or raise PromotionRefused.

    Takes the cap lock before checking and inserts in the same transaction, so
    two concurrent grants can't both take the last day. The caller commits."""
    await lock_cap(db)
    owner_id = (await resolve_owner_ids(db, [event])).get(event.id)
    if owner_id is None:
        raise PromotionRefused([RuleViolation(PROMOTION_ERROR_NO_OWNER)])
    violations = (
        request_violations(request)
        + clearance_violations(
            event, request.restriction_clearance_confirmed, request.restriction_clearance_note
        )
        + await validate_grant(db, event, request.start_date, request.end_date, now)
    )
    if violations:
        raise PromotionRefused(violations)

    days = window_days(request.start_date, request.end_date)
    invoice_reference = None if request.is_complimentary else (request.invoice_reference or None)
    promotion = Promotion(
        event_id=event.id,
        organizer_id=owner_id,
        status=PROMOTION_STATUS_PAID if request.is_complimentary else PROMOTION_STATUS_UNPAID,
        start_date=request.start_date,
        end_date=request.end_date,
        days=days,
        net_price_cents=net_price_cents(days, request.is_complimentary),
        vat_rate_percent=PROMOTION_VAT_RATE_PERCENT,
        is_complimentary=request.is_complimentary,
        complimentary_note=(request.complimentary_note or "").strip() or None
        if request.is_complimentary
        else None,
        invoice_reference=invoice_reference,
        invoice_source=PROMOTION_INVOICE_SOURCE_MANUAL if invoice_reference else None,
        advertiser_legal_name=request.advertiser_legal_name,
        advertiser_registry_code=request.advertiser_registry_code,
        billing_email=request.billing_email or None,
        granted_by=PROMOTION_GRANTED_BY_ADMIN,
        paid_at=now if request.is_complimentary else None,
    )
    if is_restricted(event.promotion_restriction):
        record_clearance(promotion, event, request.restriction_clearance_note or "", now)
    db.add(promotion)
    await db.flush()
    if request.is_complimentary:
        await take_snapshot(db, promotion, event, now, PROMOTION_SNAPSHOT_TRIGGER_GRANT)
    return promotion
