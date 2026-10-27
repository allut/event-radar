"""Admin direct grant of a Promotion: validation, pricing and the serialized
cap check-and-insert. The caller owns the transaction: it adds the audit row
after this returns and commits, which also releases the cap lock."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import ColumnElement, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app._generated.shared_constants import (
    PROMOTION_DAY_PRICE_CENTS,
    PROMOTION_VAT_RATE_PERCENT,
)
from app.constants.promotions import (
    PROMOTION_CAP_CHECK_MAX_DAYS,
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
    PROMOTION_LIVE_CAP,
    PROMOTION_REGISTRY_CODE_RE,
    PROMOTION_SNAPSHOT_TRIGGER_GRANT,
    PROMOTION_STATUS_PAID,
    PROMOTION_STATUS_UNPAID,
)
from app.models.models import Event, Promotion
from app.promotions.cap import lock_cap, tally_cap_days
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


def split_vat_cents(gross_cents: int, vat_rate_percent: Decimal) -> int:
    """The VAT part of a gross amount (the inverse of `vat_cents`)."""
    return int(
        (Decimal(gross_cents) * vat_rate_percent / (100 + vat_rate_percent)).quantize(
            Decimal(1), ROUND_HALF_UP
        )
    )


def net_price_cents(days: int, is_complimentary: bool) -> int:
    return 0 if is_complimentary else days * PROMOTION_DAY_PRICE_CENTS


def request_violations(request: GrantRequest) -> list[RuleViolation]:
    found: list[RuleViolation] = []
    if request.is_complimentary and not (request.complimentary_note or "").strip():
        found.append(RuleViolation(PROMOTION_ERROR_NOTE_REQUIRED))
    if not PROMOTION_REGISTRY_CODE_RE.fullmatch(request.advertiser_registry_code):
        found.append(RuleViolation(PROMOTION_ERROR_INVALID_REGISTRY_CODE))
    if request.invoice_reference:
        if request.is_complimentary:
            found.append(RuleViolation(PROMOTION_ERROR_INVOICE_ON_COMPLIMENTARY))
        elif not PROMOTION_INVOICE_REFERENCE_RE.fullmatch(request.invoice_reference):
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
    [found] = await validate_grants(db, [(event, start, end)], now, exclude_promotion_id)
    return found


async def validate_grants(
    db: AsyncSession,
    windows: Sequence[tuple[Event, date, date]],
    now: datetime,
    exclude_promotion_id: int | None = None,
) -> list[list[RuleViolation]]:
    """``validate_grant`` for many (event, start, end) windows, one list per
    window, in one query whatever their number, then overlap and cap per
    window in Python. The query reaches each window's own event (overlap) and
    every Promotion over the cap-checked windows' combined span (cap); an
    over-long window joins no span, so it can't widen the load to all of
    history."""
    today = tallinn_today(now)
    ordered = [(event, s, e) for event, s, e in windows if e >= s]
    capped = [(s, e) for _, s, e in ordered if window_days(s, e) <= PROMOTION_CAP_CHECK_MAX_DAYS]
    rows: Sequence[tuple[int, str, date, date]] = []
    if ordered:
        reach: ColumnElement[bool] = Promotion.event_id.in_({event.id for event, _, _ in ordered})
        if capped:
            reach = or_(
                reach,
                and_(
                    Promotion.start_date <= max(e for _, e in capped),
                    Promotion.end_date >= min(s for s, _ in capped),
                ),
            )
        query = select(
            Promotion.event_id, Promotion.status, Promotion.start_date, Promotion.end_date
        ).where(Promotion.status.in_(PROMOTION_HOLDING_STATUSES), reach)
        if exclude_promotion_id is not None:
            query = query.where(Promotion.id != exclude_promotion_id)
        rows = (await db.execute(query)).tuples().all()
    by_event: dict[int, list[tuple[date, date]]] = {}
    for event_id, _, p_start, p_end in rows:
        by_event.setdefault(event_id, []).append((p_start, p_end))

    results: list[list[RuleViolation]] = []
    for event, start, end in windows:
        found = window_violations(start, end, today, event_last_day(event))
        if end >= start:
            if any(s <= end and e >= start for s, e in by_event.get(event.id, [])):
                found.append(RuleViolation(PROMOTION_ERROR_OVERLAP))
            # An out-of-bounds window can span years; cap-check only a sane span.
            if window_days(start, end) <= PROMOTION_CAP_CHECK_MAX_DAYS:
                cap = tally_cap_days(
                    ((status, s, e) for _, status, s, e in rows), start, end, today
                )
                full = [c.day for c in cap if c.reserved >= PROMOTION_LIVE_CAP]
                if full:
                    found.append(RuleViolation(PROMOTION_ERROR_CAP_EXCEEDED, full))
        results.append(found)
    return results


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
