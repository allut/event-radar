"""Admin lifecycle commands on an existing Promotion: mark paid, edit,
re-point, end early, void and record a refund.

Each command takes the cap lock, then the Promotion row lock, so it runs
serialized against grants and other commands, enforces its rules against the
state it just read, and raises `PromotionRefused` (nothing written) when a rule
breaks. The caller adds the audit row and commits, which releases both locks.
"""

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app._generated.shared_constants import (
    PROMOTION_ERROR_ENDS_AFTER_EVENT,
    PROMOTION_ERROR_INVALID_REGISTRY_CODE,
    PROMOTION_ERROR_OVERLAP,
    PROMOTION_INVOICE_SOURCE_MANUAL,
    PROMOTION_INVOICE_SOURCE_STRIPE,
    PROMOTION_SNAPSHOT_TRIGGER_EDIT,
    PROMOTION_SNAPSHOT_TRIGGER_MARK_PAID,
    PROMOTION_SNAPSHOT_TRIGGER_REPOINT,
)
from app.constants.promotions import (
    PROMOTION_END_REASON_ADMIN,
    PROMOTION_ERROR_ADVERTISER_NAME_REQUIRED,
    PROMOTION_ERROR_ALREADY_STARTED,
    PROMOTION_ERROR_INVALID_INVOICE_REFERENCE,
    PROMOTION_ERROR_INVALID_TRANSITION,
    PROMOTION_ERROR_INVOICE_ON_COMPLIMENTARY,
    PROMOTION_ERROR_LIVE_EDIT_FIELDS,
    PROMOTION_ERROR_LIVE_END_IN_PAST,
    PROMOTION_ERROR_LIVE_END_MUST_SHORTEN,
    PROMOTION_ERROR_NOT_EDITABLE,
    PROMOTION_ERROR_NO_CHANGES,
    PROMOTION_ERROR_REASON_REQUIRED,
    PROMOTION_ERROR_REFUND_AMOUNT,
    PROMOTION_ERROR_REFUND_EXCEEDS_PAID,
    PROMOTION_ERROR_REFUND_NOTE_REQUIRED,
    PROMOTION_ERROR_REFUND_NOT_PAID,
    PROMOTION_ERROR_REPOINT_NOT_OWNER,
    PROMOTION_ERROR_REPOINT_NOT_SAME_GROUP,
    PROMOTION_ERROR_REPOINT_SAME_EVENT,
    PROMOTION_ERROR_REPOINT_TARGET_NOT_FOUND,
    PROMOTION_ERROR_STRIPE_DATES_LOCKED,
    PROMOTION_HOLDING_STATUSES,
    PROMOTION_INVOICE_REFERENCE_RE,
    PROMOTION_NULLABLE_TEXT_FIELDS,
    PROMOTION_REFUND_IDEMPOTENCY_KEY,
    PROMOTION_REFUND_NOTE_LABEL_CREDIT_NOTE,
    PROMOTION_REFUND_NOTE_LABEL_REFUND,
    PROMOTION_REGISTRY_CODE_RE,
    PROMOTION_STATUS_ENDED_EARLY,
    PROMOTION_STATUS_PAID,
    PROMOTION_STATUS_UNPAID,
    PROMOTION_STATUS_VOID,
)
from app.config import settings
from app.integrations.payments import PaymentGateway, RefundRequest
from app.models.events import Event
from app.models.promotions import Promotion
from app.promotions.cap import lock_cap
from app.promotions.restriction import clear_existing
from app.promotions.grant import (
    PromotionRefused,
    net_price_cents,
    split_vat_cents,
    validate_grant,
    vat_cents,
)
from app.promotions.owners import resolve_owner_ids
from app.promotions.snapshots import take_snapshot
from app.promotions.windows import (
    RuleViolation,
    event_last_day,
    tallinn_today,
    window_days,
)

# Fields an edit may change, and the ones that clear to NULL when blank.
PROMOTION_EDITABLE_FIELDS = frozenset(
    {
        "start_date",
        "end_date",
        "advertiser_legal_name",
        "advertiser_registry_code",
        "billing_email",
        "invoice_reference",
    }
)


class PromotionNotFound(Exception):
    """No Promotion with that id."""


def _refuse(*codes: str) -> PromotionRefused:
    return PromotionRefused([RuleViolation(code) for code in codes])


async def _load_locked(db: AsyncSession, promotion_id: int) -> Promotion:
    """Cap lock first (the same order a grant uses), then the row lock."""
    await lock_cap(db)
    promotion = await db.scalar(
        select(Promotion)
        .where(Promotion.id == promotion_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if promotion is None:
        raise PromotionNotFound(promotion_id)
    return promotion


async def _event_of(db: AsyncSession, promotion: Promotion) -> Event:
    event = await db.get(Event, promotion.event_id)
    assert event is not None  # events.id is RESTRICT-referenced
    return event


def _is_holding(promotion: Promotion, today: date) -> bool:
    """Unpaid or paid, and not past its last day."""
    return promotion.status in PROMOTION_HOLDING_STATUSES and today <= promotion.end_date


async def mark_paid(
    db: AsyncSession,
    promotion_id: int,
    now: datetime,
    invoice_reference: str | None = None,
) -> Promotion:
    """`unpaid -> paid`, any time before the start date (Tallinn)."""
    promotion = await _load_locked(db, promotion_id)
    if promotion.status != PROMOTION_STATUS_UNPAID:
        raise _refuse(PROMOTION_ERROR_INVALID_TRANSITION)
    # An open card checkout is paid by its webhook, never by hand.
    if promotion.stripe_checkout_session_id is not None:
        raise _refuse(PROMOTION_ERROR_INVALID_TRANSITION)
    if tallinn_today(now) >= promotion.start_date:
        raise _refuse(PROMOTION_ERROR_ALREADY_STARTED)
    reference = (invoice_reference or "").strip() or None
    if reference is not None and not PROMOTION_INVOICE_REFERENCE_RE.fullmatch(reference):
        raise _refuse(PROMOTION_ERROR_INVALID_INVOICE_REFERENCE)
    if reference is not None:
        promotion.invoice_reference = reference
        promotion.invoice_source = PROMOTION_INVOICE_SOURCE_MANUAL
    promotion.status = PROMOTION_STATUS_PAID
    promotion.paid_at = now
    promotion.updated_at = now
    await take_snapshot(
        db, promotion, await _event_of(db, promotion), now, PROMOTION_SNAPSHOT_TRIGGER_MARK_PAID
    )
    return promotion


def _normalize_changes(changes: Mapping[str, Any]) -> dict[str, Any]:
    unknown = set(changes) - PROMOTION_EDITABLE_FIELDS
    if unknown:
        raise ValueError(f"not editable: {sorted(unknown)}")
    out: dict[str, Any] = {}
    for key, value in changes.items():
        if isinstance(value, str):
            value = value.strip()
            if not value and key in PROMOTION_NULLABLE_TEXT_FIELDS:
                value = None
        out[key] = value
    return out


def _field_violations(promotion: Promotion, diff: Mapping[str, Any]) -> list[RuleViolation]:
    found: list[RuleViolation] = []
    if "advertiser_legal_name" in diff and not diff["advertiser_legal_name"]:
        found.append(RuleViolation(PROMOTION_ERROR_ADVERTISER_NAME_REQUIRED))
    if "advertiser_registry_code" in diff and not PROMOTION_REGISTRY_CODE_RE.fullmatch(
        diff["advertiser_registry_code"] or ""
    ):
        found.append(RuleViolation(PROMOTION_ERROR_INVALID_REGISTRY_CODE))
    reference = diff.get("invoice_reference")
    if reference is not None:
        if promotion.is_complimentary:
            found.append(RuleViolation(PROMOTION_ERROR_INVOICE_ON_COMPLIMENTARY))
        elif not PROMOTION_INVOICE_REFERENCE_RE.fullmatch(reference):
            found.append(RuleViolation(PROMOTION_ERROR_INVALID_INVOICE_REFERENCE))
    return found


async def edit_promotion(
    db: AsyncSession, promotion_id: int, changes: Mapping[str, Any], now: datetime
) -> Promotion:
    """Edit a Promotion.

    Before the start date: the dates (window, overlap and cap rechecked
    against the other Promotions, price recomputed), advertiser details and
    invoice reference. A card-paid Promotion's dates are refused: the price
    charged is fixed. While live: only an earlier end date, never before
    today; the price paid stays on the row (a refund is recorded separately).
    A finished, ended or void Promotion cannot be edited. Takes a content
    snapshot, because an edit can change what the Promotion displays."""
    promotion = await _load_locked(db, promotion_id)
    today = tallinn_today(now)
    diff = {
        key: value
        for key, value in _normalize_changes(changes).items()
        if getattr(promotion, key) != value
    }
    if not _is_holding(promotion, today):
        raise _refuse(PROMOTION_ERROR_NOT_EDITABLE)
    if not diff:
        raise _refuse(PROMOTION_ERROR_NO_CHANGES)
    event = await _event_of(db, promotion)

    if today >= promotion.start_date:  # live
        if set(diff) - {"end_date"}:
            raise _refuse(PROMOTION_ERROR_LIVE_EDIT_FIELDS)
        new_end: date = diff["end_date"]
        if new_end >= promotion.end_date:
            raise _refuse(PROMOTION_ERROR_LIVE_END_MUST_SHORTEN)
        if new_end < today:
            raise _refuse(PROMOTION_ERROR_LIVE_END_IN_PAST)
        promotion.end_date = new_end
        promotion.days = window_days(promotion.start_date, new_end)
    else:
        if promotion.invoice_source == PROMOTION_INVOICE_SOURCE_STRIPE and (
            {"start_date", "end_date"} & set(diff)
        ):
            # The card charge fixed the price, and every refund is capped by it.
            raise _refuse(PROMOTION_ERROR_STRIPE_DATES_LOCKED)
        violations = _field_violations(promotion, diff)
        if "start_date" in diff or "end_date" in diff:
            start = diff.get("start_date", promotion.start_date)
            end = diff.get("end_date", promotion.end_date)
            violations += await validate_grant(
                db, event, start, end, now, exclude_promotion_id=promotion.id
            )
        if violations:
            raise PromotionRefused(violations)
        for key, value in diff.items():
            setattr(promotion, key, value)
        if "start_date" in diff or "end_date" in diff:
            promotion.days = window_days(promotion.start_date, promotion.end_date)
            promotion.net_price_cents = net_price_cents(promotion.days, promotion.is_complimentary)
        if "invoice_reference" in diff:
            promotion.invoice_source = (
                PROMOTION_INVOICE_SOURCE_MANUAL if diff["invoice_reference"] else None
            )
    promotion.updated_at = now
    await db.flush()
    await take_snapshot(db, promotion, event, now, PROMOTION_SNAPSHOT_TRIGGER_EDIT)
    return promotion


def _dedup_group_key(event: Event) -> int:
    return event.dedup_group_id if event.dedup_group_id is not None else event.id


async def repoint_promotion(
    db: AsyncSession, promotion_id: int, target_event_id: int, now: datetime
) -> Promotion:
    """Move a Promotion to another event the same Organizer owns in the same
    dedup group (the rescue for a Promotion paused by a lost dedup collision).
    The window must still end on or before the target's last day and must not
    overlap another Promotion on it."""
    promotion = await _load_locked(db, promotion_id)
    if not _is_holding(promotion, tallinn_today(now)):
        raise _refuse(PROMOTION_ERROR_NOT_EDITABLE)
    if target_event_id == promotion.event_id:
        raise _refuse(PROMOTION_ERROR_REPOINT_SAME_EVENT)
    target = await db.get(Event, target_event_id)
    if target is None:
        raise _refuse(PROMOTION_ERROR_REPOINT_TARGET_NOT_FOUND)
    source = await _event_of(db, promotion)
    violations: list[RuleViolation] = []
    if (await resolve_owner_ids(db, [target])).get(target.id) != promotion.organizer_id:
        violations.append(RuleViolation(PROMOTION_ERROR_REPOINT_NOT_OWNER))
    if _dedup_group_key(target) != _dedup_group_key(source):
        violations.append(RuleViolation(PROMOTION_ERROR_REPOINT_NOT_SAME_GROUP))
    if violations:
        raise PromotionRefused(violations)
    if promotion.end_date > event_last_day(target):
        violations.append(RuleViolation(PROMOTION_ERROR_ENDS_AFTER_EVENT))
    clash = await db.scalar(
        select(Promotion.id).where(
            Promotion.event_id == target.id,
            Promotion.id != promotion.id,
            Promotion.status.in_(PROMOTION_HOLDING_STATUSES),
            Promotion.start_date <= promotion.end_date,
            Promotion.end_date >= promotion.start_date,
        )
    )
    if clash is not None:
        violations.append(RuleViolation(PROMOTION_ERROR_OVERLAP))
    if violations:
        raise PromotionRefused(violations)
    promotion.event_id = target.id
    promotion.updated_at = now
    await db.flush()
    await take_snapshot(db, promotion, target, now, PROMOTION_SNAPSHOT_TRIGGER_REPOINT)
    return promotion


def _required_reason(reason: str) -> str:
    cleaned = (reason or "").strip()
    if not cleaned:
        raise _refuse(PROMOTION_ERROR_REASON_REQUIRED)
    return cleaned


async def end_early(
    db: AsyncSession,
    promotion_id: int,
    reason: str,
    now: datetime,
    end_reason: str = PROMOTION_END_REASON_ADMIN,
) -> Promotion:
    """`paid -> ended_early` with a required reason. Every cap day is released
    at once (the Promotion stops being a holding status), and the fill gate
    stops serving it."""
    cleaned = _required_reason(reason)
    promotion = await _load_locked(db, promotion_id)
    if promotion.status != PROMOTION_STATUS_PAID or tallinn_today(now) > promotion.end_date:
        raise _refuse(PROMOTION_ERROR_INVALID_TRANSITION)
    promotion.status = PROMOTION_STATUS_ENDED_EARLY
    promotion.ended_at = now
    promotion.end_reason = end_reason
    promotion.end_note = cleaned
    promotion.updated_at = now
    await db.flush()
    return promotion


async def void_promotion(
    db: AsyncSession, promotion_id: int, reason: str, now: datetime
) -> Promotion:
    """`unpaid -> void` with a required reason, releasing all its days."""
    cleaned = _required_reason(reason)
    promotion = await _load_locked(db, promotion_id)
    if promotion.status != PROMOTION_STATUS_UNPAID:
        raise _refuse(PROMOTION_ERROR_INVALID_TRANSITION)
    promotion.status = PROMOTION_STATUS_VOID
    promotion.ended_at = now
    promotion.end_reason = PROMOTION_END_REASON_ADMIN
    promotion.end_note = cleaned
    promotion.updated_at = now
    await db.flush()
    return promotion


async def record_refund(
    db: AsyncSession,
    promotion_id: int,
    amount_cents: int,
    note: str,
    now: datetime,
    gateway: PaymentGateway | None = None,
) -> Promotion:
    """Refund `amount_cents` (gross) with a required note. Cumulative; the total
    can't exceed what was charged (net plus VAT). Only a paid, non-complimentary
    Promotion, live or ended early, can be refunded.

    An off-platform payment is only recorded. A Stripe-paid one is issued:
    `gateway.refund()` makes the credit note (reversing the VAT) and the card
    refund in one call, and the credit note and refund ids go into the note. That
    call runs between two transactions, outside the cap lock: the session is
    committed first, then the row is re-locked to record the refund. A provider
    failure raises `PaymentProviderError` and records nothing."""
    cleaned = (note or "").strip()
    promotion = await _load_locked(db, promotion_id)
    if amount_cents <= 0:
        raise _refuse(PROMOTION_ERROR_REFUND_AMOUNT)
    if not cleaned:
        raise _refuse(PROMOTION_ERROR_REFUND_NOTE_REQUIRED)
    if promotion.is_complimentary or promotion.status not in (
        PROMOTION_STATUS_PAID,
        PROMOTION_STATUS_ENDED_EARLY,
    ):
        raise _refuse(PROMOTION_ERROR_REFUND_NOT_PAID)
    gross = promotion.net_price_cents + vat_cents(
        promotion.net_price_cents, promotion.vat_rate_percent
    )
    if promotion.refunded_cents + amount_cents > gross:
        raise _refuse(PROMOTION_ERROR_REFUND_EXCEEDS_PAID)
    recorded = cleaned
    if promotion.invoice_source == PROMOTION_INVOICE_SOURCE_STRIPE:
        if gateway is None or not promotion.stripe_payment_intent_id:
            raise _refuse(PROMOTION_ERROR_REFUND_NOT_PAID)
        vat_part = split_vat_cents(amount_cents, promotion.vat_rate_percent)
        request = RefundRequest(
            payment_intent_id=promotion.stripe_payment_intent_id,
            invoice_id=promotion.stripe_invoice_id,
            net_cents=amount_cents - vat_part,
            vat_cents=vat_part,
            tax_rate_id=settings.STRIPE_TAX_RATE_ID,
            reason=cleaned,
            idempotency_key=PROMOTION_REFUND_IDEMPOTENCY_KEY.format(
                promotion_id=promotion.id,
                refunded_cents=promotion.refunded_cents,
                amount_cents=amount_cents,
            ),
            metadata={"promotion_id": str(promotion.id)},
        )
        # The network call runs with no lock held. The commit releases the cap
        # and row locks (and keeps whatever the caller already wrote); a retry
        # after a crash replays the same idempotency key, so Stripe refunds once.
        await db.commit()
        result = await gateway.refund(request)
        promotion = await _load_locked(db, promotion_id)
        refs = [
            f"{label} {ref}"
            for label, ref in (
                (PROMOTION_REFUND_NOTE_LABEL_CREDIT_NOTE, result.credit_note_id),
                (PROMOTION_REFUND_NOTE_LABEL_REFUND, result.refund_id),
            )
            if ref
        ]
        recorded = f"{cleaned} ({', '.join(refs)})" if refs else cleaned
    promotion.refunded_cents += amount_cents
    promotion.refund_note = f"{promotion.refund_note}\n{recorded}" if promotion.refund_note else recorded
    promotion.updated_at = now
    await db.flush()
    return promotion


async def clear_restriction(
    db: AsyncSession, promotion_id: int, note: str | None, now: datetime
) -> Promotion:
    """Record a Restriction clearance for the event's current restriction on a
    scheduled or live Promotion (the newly-flagged path): the fill gate then
    lets it resume. The clearance covers only that restriction."""
    promotion = await _load_locked(db, promotion_id)
    if not _is_holding(promotion, tallinn_today(now)):
        raise _refuse(PROMOTION_ERROR_NOT_EDITABLE)
    event = await _event_of(db, promotion)
    violations = clear_existing(promotion, event, note, now)
    if violations:
        raise PromotionRefused(violations)
    promotion.updated_at = now
    await db.flush()
    return promotion
