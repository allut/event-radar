"""Stripe webhook handling (#618, #619).

Each event id is recorded in the same transaction as its handler, so a replay
finds the id and changes nothing, and a failed handler rolls the id back so
Stripe retries. Handlers read the Promotion's current state and never assume
event order: an `expired` after a `completed` is a no-op, and a `completed`
after the hold was voided is refunded in full and never reinstated.

Emails are returned as callbacks for the caller to run after the commit.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants.admin import (
    ADMIN_ACTION_PROMOTION_SYSTEM_LATE_REFUND,
    ADMIN_ACTION_PROMOTION_SYSTEM_PAID,
    ADMIN_ACTION_PROMOTION_SYSTEM_VOID,
)
from app._generated.shared_constants import PROMOTION_INVOICE_SOURCE_STRIPE
from app.constants.promotions import (
    PROMOTION_END_REASON_CHECKOUT_EXPIRED,
    PROMOTION_LATE_PAYMENT_REASON,
    PAYMENT_NOTICE_DISPUTE_DETAIL,
    PAYMENT_NOTICE_DISPUTE_MATCHED,
    PAYMENT_NOTICE_DISPUTE_SUBJECT,
    PAYMENT_NOTICE_DISPUTE_UNMATCHED,
    PAYMENT_NOTICE_LATE_REFUND_DETAIL,
    PAYMENT_NOTICE_LATE_REFUND_SUBJECT,
    PAYMENT_NOTICE_PAID_DETAIL,
    PAYMENT_NOTICE_PAID_SUBJECT,
    PROMOTION_LATE_REFUND_IDEMPOTENCY_KEY,
    PROMOTION_LATE_REFUND_NOTE,
    PROMOTION_SNAPSHOT_TRIGGER_CHECKOUT_PAID,
    PROMOTION_STATUS_PAID,
    PROMOTION_STATUS_UNPAID,
    PROMOTION_STATUS_VOID,
    STRIPE_EVENT_CHECKOUT_COMPLETED,
    STRIPE_EVENT_CHECKOUT_EXPIRED,
    STRIPE_EVENT_DISPUTE_CREATED,
    STRIPE_PAYMENT_STATUS_PAID,
    STRIPE_WEBHOOK_STATUS_DUPLICATE,
    STRIPE_WEBHOOK_STATUS_IGNORED,
    STRIPE_WEBHOOK_STATUS_OK,
)
from app.email.promotion_admin import send_payment_notice
from app.email.promotion_notice import send_promotion_late_refund_email
from app.events.localize import resolve_title
from app.integrations.payments import (
    InvoiceInfo,
    PaymentGateway,
    PaymentProviderError,
    RefundRequest,
    StripeEvent,
)
from app.models.models import Event, Organizer, ProcessedStripeEvent, Promotion
from app.promotions.audit import record_system_action
from app.promotions.grant import vat_cents
from app.promotions.snapshots import take_snapshot

log = logging.getLogger(__name__)

AfterCommit = Callable[[], Awaitable[None]]


@dataclass
class WebhookOutcome:
    status: str
    after_commit: list[AfterCommit] = field(default_factory=list)


async def _record_event_id(db: AsyncSession, event_id: str) -> bool:
    """True the first time an id is seen. A concurrent duplicate blocks on the
    insert until the first handler commits, then sees it as a replay."""
    inserted = await db.scalar(
        pg_insert(ProcessedStripeEvent)
        .values(stripe_event_id=event_id)
        .on_conflict_do_nothing(index_elements=["stripe_event_id"])
        .returning(ProcessedStripeEvent.stripe_event_id)
    )
    return inserted is not None


async def _locked_by_session(db: AsyncSession, session_id: str) -> Promotion | None:
    return await db.scalar(
        select(Promotion)
        .where(Promotion.stripe_checkout_session_id == session_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _gross_cents(promotion: Promotion) -> tuple[int, int]:
    vat = vat_cents(promotion.net_price_cents, promotion.vat_rate_percent)
    return promotion.net_price_cents, vat


async def _invoice_info(gateway: PaymentGateway, invoice_id: str | None) -> InvoiceInfo:
    if not invoice_id:
        return InvoiceInfo(None, None)
    try:
        return await gateway.retrieve_invoice(invoice_id)
    except PaymentProviderError:
        # The payment is real; don't leave the Organizer unpaid over a missing link.
        log.error("Stripe invoice lookup failed (invoice=%s)", invoice_id, exc_info=True)
        return InvoiceInfo(None, None)


async def _mark_paid(
    db: AsyncSession,
    gateway: PaymentGateway,
    promotion: Promotion,
    session: dict[str, Any],
    now: datetime,
) -> WebhookOutcome:
    invoice_id = session.get("invoice")
    invoice = await _invoice_info(gateway, invoice_id)
    promotion.status = PROMOTION_STATUS_PAID
    promotion.paid_at = now
    promotion.updated_at = now
    promotion.invoice_source = PROMOTION_INVOICE_SOURCE_STRIPE
    promotion.stripe_payment_intent_id = session.get("payment_intent")
    promotion.stripe_invoice_id = invoice_id
    promotion.invoice_reference = invoice.number
    promotion.invoice_url = invoice.hosted_url
    event = await db.get(Event, promotion.event_id)
    assert event is not None
    await take_snapshot(db, promotion, event, now, PROMOTION_SNAPSHOT_TRIGGER_CHECKOUT_PAID)
    record_system_action(
        db, promotion, ADMIN_ACTION_PROMOTION_SYSTEM_PAID, invoice_number=invoice.number
    )
    detail = PAYMENT_NOTICE_PAID_DETAIL.format(
        promotion_id=promotion.id,
        title=event.title_orig,
        start=promotion.start_date,
        end=promotion.end_date,
        advertiser=promotion.advertiser_legal_name,
    )
    promotion_id = promotion.id
    return WebhookOutcome(
        STRIPE_WEBHOOK_STATUS_OK,
        [lambda: send_payment_notice(PAYMENT_NOTICE_PAID_SUBJECT, detail, promotion_id)],
    )


async def _refund_late_payment(
    db: AsyncSession,
    gateway: PaymentGateway,
    promotion: Promotion,
    session: dict[str, Any],
    now: datetime,
) -> WebhookOutcome:
    """A payment for a hold that was already voided: refund it in full, stay
    void. A provider failure propagates so Stripe retries the event."""
    net, vat = _gross_cents(promotion)
    payment_intent = session.get("payment_intent")
    if promotion.refunded_cents >= net + vat or not payment_intent:
        return WebhookOutcome(STRIPE_WEBHOOK_STATUS_IGNORED)
    invoice_id = session.get("invoice")
    result = await gateway.refund(
        RefundRequest(
            payment_intent_id=payment_intent,
            invoice_id=invoice_id,
            net_cents=net,
            vat_cents=vat,
            tax_rate_id=settings.STRIPE_TAX_RATE_ID,
            reason=PROMOTION_LATE_REFUND_NOTE,
            idempotency_key=PROMOTION_LATE_REFUND_IDEMPOTENCY_KEY.format(promotion_id=promotion.id),
            metadata={"promotion_id": str(promotion.id)},
        )
    )
    promotion.invoice_source = PROMOTION_INVOICE_SOURCE_STRIPE
    promotion.stripe_payment_intent_id = payment_intent
    promotion.stripe_invoice_id = invoice_id
    promotion.refunded_cents = net + vat
    promotion.refund_note = PROMOTION_LATE_REFUND_NOTE
    promotion.updated_at = now
    record_system_action(
        db,
        promotion,
        ADMIN_ACTION_PROMOTION_SYSTEM_LATE_REFUND,
        refunded_cents=net + vat,
        refund_id=result.refund_id,
        credit_note_id=result.credit_note_id,
    )
    organizer = await db.get(Organizer, promotion.organizer_id)
    event = await db.get(Event, promotion.event_id)
    promotion_id = promotion.id
    detail = PAYMENT_NOTICE_LATE_REFUND_DETAIL.format(promotion_id=promotion_id, cents=net + vat)
    after: list[AfterCommit] = [
        lambda: send_payment_notice(PAYMENT_NOTICE_LATE_REFUND_SUBJECT, detail, promotion_id)
    ]
    if organizer is not None and event is not None:
        to_email, locale = organizer.email, organizer.locale
        title = resolve_title(event, locale)
        start, end = promotion.start_date, promotion.end_date
        after.append(
            lambda: send_promotion_late_refund_email(
                to_email, title, start, end, PROMOTION_LATE_PAYMENT_REASON, locale
            )
        )
    return WebhookOutcome(STRIPE_WEBHOOK_STATUS_OK, after)


async def _on_completed(
    db: AsyncSession, gateway: PaymentGateway, session: dict[str, Any], now: datetime
) -> WebhookOutcome:
    promotion = await _locked_by_session(db, str(session.get("id", "")))
    if promotion is None or session.get("payment_status") != STRIPE_PAYMENT_STATUS_PAID:
        log.warning("Stripe completed event matched no payable Promotion")
        return WebhookOutcome(STRIPE_WEBHOOK_STATUS_IGNORED)
    if promotion.status == PROMOTION_STATUS_UNPAID:
        return await _mark_paid(db, gateway, promotion, session, now)
    if promotion.status == PROMOTION_STATUS_VOID:
        return await _refund_late_payment(db, gateway, promotion, session, now)
    return WebhookOutcome(STRIPE_WEBHOOK_STATUS_IGNORED)  # already paid or ended


async def _on_expired(db: AsyncSession, session: dict[str, Any], now: datetime) -> WebhookOutcome:
    promotion = await _locked_by_session(db, str(session.get("id", "")))
    if promotion is None or promotion.status != PROMOTION_STATUS_UNPAID:
        return WebhookOutcome(STRIPE_WEBHOOK_STATUS_IGNORED)
    promotion.status = PROMOTION_STATUS_VOID
    promotion.ended_at = now
    promotion.end_reason = PROMOTION_END_REASON_CHECKOUT_EXPIRED
    promotion.updated_at = now
    record_system_action(
        db,
        promotion,
        ADMIN_ACTION_PROMOTION_SYSTEM_VOID,
        end_reason=PROMOTION_END_REASON_CHECKOUT_EXPIRED,
    )
    return WebhookOutcome(STRIPE_WEBHOOK_STATUS_OK)  # quiet: no email


async def _on_dispute(db: AsyncSession, dispute: dict[str, Any]) -> WebhookOutcome:
    payment_intent = dispute.get("payment_intent")
    promotion_id = None
    if payment_intent:
        promotion_id = await db.scalar(
            select(Promotion.id).where(Promotion.stripe_payment_intent_id == payment_intent)
        )
    match = (
        PAYMENT_NOTICE_DISPUTE_MATCHED.format(promotion_id=promotion_id)
        if promotion_id
        else PAYMENT_NOTICE_DISPUTE_UNMATCHED
    )
    detail = PAYMENT_NOTICE_DISPUTE_DETAIL.format(
        dispute_id=dispute.get("id"),
        reason=dispute.get("reason"),
        amount=dispute.get("amount"),
        payment_intent=payment_intent,
        match=match,
    )
    return WebhookOutcome(
        STRIPE_WEBHOOK_STATUS_OK,
        [lambda: send_payment_notice(PAYMENT_NOTICE_DISPUTE_SUBJECT, detail, promotion_id)],
    )


async def process_stripe_event(
    db: AsyncSession, gateway: PaymentGateway, event: StripeEvent, now: datetime
) -> WebhookOutcome:
    """Handle one verified event. The caller commits, then runs `after_commit`."""
    if not await _record_event_id(db, event.id):
        return WebhookOutcome(STRIPE_WEBHOOK_STATUS_DUPLICATE)
    if event.type == STRIPE_EVENT_CHECKOUT_COMPLETED:
        return await _on_completed(db, gateway, event.object, now)
    if event.type == STRIPE_EVENT_CHECKOUT_EXPIRED:
        return await _on_expired(db, event.object, now)
    if event.type == STRIPE_EVENT_DISPUTE_CREATED:
        return await _on_dispute(db, event.object)
    return WebhookOutcome(STRIPE_WEBHOOK_STATUS_IGNORED)
