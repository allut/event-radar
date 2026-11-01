"""Admin promotion lifecycle commands: mark paid, edit, re-point, clear a restriction, end, withdraw, void and refund."""

import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_admin
from app.constants.admin import (
    ADMIN_ACTION_PROMOTION_CLEAR_RESTRICTION,
    ADMIN_ACTION_PROMOTION_EDIT,
    ADMIN_ACTION_PROMOTION_END,
    ADMIN_ACTION_PROMOTION_MARK_PAID,
    ADMIN_ACTION_PROMOTION_REFUND,
    ADMIN_ACTION_PROMOTION_REPOINT,
    ADMIN_ACTION_PROMOTION_VOID,
)
from app.constants.promotions import (
    ERROR_PROMOTION_FIELD_NOT_NULLABLE,
    ERROR_PROMOTION_NOT_FOUND,
    PROMOTION_ADVERTISER_NAME_MAX_CHARS,
    PROMOTION_BILLING_EMAIL_MAX_CHARS,
    PROMOTION_WITHDRAWN_NOTE,
    PROMOTION_CHECKOUT_ERROR_MESSAGES,
    PROMOTION_ERROR_REFUND_PROVIDER,
    PROMOTION_INVOICE_REFERENCE_MAX_LEN,
    PROMOTION_NOTE_MAX_CHARS,
    PROMOTION_NULLABLE_TEXT_FIELDS,
    PROMOTION_REGISTRY_CODE_MAX_LEN,
)
from app.constants.rate_limits import (
    RATE_LIMIT_ADMIN,
)
from app.db import AsyncSessionLocal
from app.integrations.payments import PaymentGateway, PaymentProviderError
from app.integrations.providers import get_payment_gateway
from app.promotions.grant import (
    PromotionRefused,
)
from app.promotions.lifecycle import (
    clear_restriction,
    PromotionNotFound,
    edit_promotion,
    end_early,
    mark_paid,
    record_refund,
    repoint_promotion,
    void_promotion,
)
from app.promotions.views import (
    promotion_detail,
)
from app.promotions.windows import now_tallinn
from app.promotions.withdraw import withdraw_promotion
from app.models.events import Event
from app.models.organizers import Organizer
from app.models.promotions import Promotion
from app.rate_limit import limiter
from app.routers.utils.promotions import (
    audit_withdrawals,
    notify_promotion_ended,
    promotion_audit_summary,
    promotion_refusal,
    withdraw_guard,
)
from app.routers.utils.admin import log_admin_action, run_admin_job

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")

# ---------------------------------------------------------------------------
# Promotion lifecycle commands (#601). Each command runs under the cap lock,
# writes its audit row in the same transaction and returns the refreshed
# detail payload.
# ---------------------------------------------------------------------------


class _PromotionMarkPaidBody(BaseModel):
    invoice_reference: str | None = Field(default=None, max_length=PROMOTION_INVOICE_REFERENCE_MAX_LEN)


class _PromotionEditBody(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    advertiser_legal_name: str | None = Field(
        default=None, max_length=PROMOTION_ADVERTISER_NAME_MAX_CHARS
    )
    advertiser_registry_code: str | None = Field(default=None, max_length=PROMOTION_REGISTRY_CODE_MAX_LEN)
    billing_email: EmailStr | None = Field(
        default=None, max_length=PROMOTION_BILLING_EMAIL_MAX_CHARS
    )
    invoice_reference: str | None = Field(default=None, max_length=PROMOTION_INVOICE_REFERENCE_MAX_LEN)


class _PromotionRepointBody(BaseModel):
    event_id: int


class _PromotionClearBody(BaseModel):
    note: str = Field(max_length=PROMOTION_NOTE_MAX_CHARS)


class _PromotionReasonBody(BaseModel):
    reason: str = Field(max_length=PROMOTION_NOTE_MAX_CHARS)


class _PromotionRefundBody(BaseModel):
    amount_cents: int
    note: str = Field(max_length=PROMOTION_NOTE_MAX_CHARS)


async def _run_promotion_command(
    promotion_id: int,
    action: str,
    command: Callable[[AsyncSession, datetime], Awaitable[Promotion]],
    audit_extra: dict,
    notify_reason: str | None = None,
    voided: bool = False,
) -> dict:
    async def _run() -> dict:
        now = now_tallinn()
        async with AsyncSessionLocal() as db:
            try:
                promotion = await command(db, now)
            except PromotionNotFound:
                await db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_PROMOTION_NOT_FOUND
                ) from None
            except PromotionRefused as refused:
                await db.rollback()
                raise promotion_refusal(refused) from None
            except PaymentProviderError:
                await db.rollback()
                log.error("Stripe refused a Promotion command (%s)", action, exc_info=True)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=PROMOTION_CHECKOUT_ERROR_MESSAGES[PROMOTION_ERROR_REFUND_PROVIDER],
                ) from None
            emit_admin_log = log_admin_action(
                db, action, promotion.id, {**promotion_audit_summary(promotion), **audit_extra}
            )
            payload = await promotion_detail(db, promotion, now)
            organizer = await db.get(Organizer, promotion.organizer_id)
            event = await db.get(Event, promotion.event_id)
            await db.commit()
            emit_admin_log()
            if notify_reason is not None and organizer is not None and event is not None:
                await notify_promotion_ended(organizer, event, promotion, notify_reason, voided)
            return payload

    return await run_admin_job(f"Promotion {action}", _run())


@router.post("/promotions/{promotion_id}/mark-paid", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_mark_promotion_paid(
    promotion_id: int, body: _PromotionMarkPaidBody, request: Request
) -> dict:
    """`unpaid -> paid`, any time before the start date (Tallinn). Optionally
    records the invoice reference (`ER-M-` series)."""
    return await _run_promotion_command(
        promotion_id,
        ADMIN_ACTION_PROMOTION_MARK_PAID,
        lambda db, now: mark_paid(db, promotion_id, now, body.invoice_reference),
        {"invoice_reference": (body.invoice_reference or "").strip() or None},
    )


@router.patch("/promotions/{promotion_id}", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_edit_promotion(
    promotion_id: int, body: _PromotionEditBody, request: Request
) -> dict:
    """Edit the fields sent. Before the start date: dates (cap rechecked,
    price recomputed), advertiser details and invoice reference. While live:
    only an earlier `end_date`. Send `billing_email` / `invoice_reference` as
    null to clear them."""
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        if value is None and key not in PROMOTION_NULLABLE_TEXT_FIELDS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=ERROR_PROMOTION_FIELD_NOT_NULLABLE.format(key=key),
            )
    logged = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in changes.items()}
    return await _run_promotion_command(
        promotion_id,
        ADMIN_ACTION_PROMOTION_EDIT,
        lambda db, now: edit_promotion(db, promotion_id, changes, now),
        {"changes": logged},
    )


@router.post("/promotions/{promotion_id}/repoint", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_repoint_promotion(
    promotion_id: int, body: _PromotionRepointBody, request: Request
) -> dict:
    """Move the Promotion to another event the same Organizer owns in the same
    dedup group."""
    return await _run_promotion_command(
        promotion_id,
        ADMIN_ACTION_PROMOTION_REPOINT,
        lambda db, now: repoint_promotion(db, promotion_id, body.event_id, now),
        {"to_event_id": body.event_id},
    )


@router.post("/promotions/{promotion_id}/clear-restriction", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_clear_promotion_restriction(
    promotion_id: int, body: _PromotionClearBody, request: Request
) -> dict:
    """Clear the event's current Promotion restriction on a scheduled or live
    Promotion (a required note); the fill gate then lets it resume. 422 when
    the event is not restricted or the note is empty. Covers only that restriction."""
    return await _run_promotion_command(
        promotion_id,
        ADMIN_ACTION_PROMOTION_CLEAR_RESTRICTION,
        lambda db, now: clear_restriction(db, promotion_id, body.note, now),
        {"note": body.note.strip()},
    )


@router.post("/promotions/{promotion_id}/end", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_end_promotion(
    promotion_id: int, body: _PromotionReasonBody, request: Request
) -> dict:
    """`paid -> ended_early` with a required reason, which is emailed to the
    Organizer in their locale. Releases every cap day."""
    reason = body.reason.strip()
    return await _run_promotion_command(
        promotion_id,
        ADMIN_ACTION_PROMOTION_END,
        lambda db, now: end_early(db, promotion_id, reason, now),
        {"reason": reason},
        notify_reason=reason,
    )


@router.post("/promotions/{promotion_id}/withdraw", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_withdraw_promotion(
    promotion_id: int, request: Request, gateway: PaymentGateway = Depends(get_payment_gateway)
) -> dict:
    """Withdraw (#620) one paid Promotion: `ended_early` with
    `feature_withdrawn` and a full refund of its unused days, emailed to the
    Organizer. A card-paid one is refunded through Stripe (502 when Stripe
    refuses; it stays paid). 409 `slots_still_enabled` while the slots flag is
    on. Returns the refreshed detail."""
    withdraw_guard()

    async def _run() -> dict:
        now = now_tallinn()
        async with AsyncSessionLocal() as db:
            try:
                item = await withdraw_promotion(db, promotion_id, now, gateway)
            except PromotionNotFound:
                await db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_PROMOTION_NOT_FOUND
                ) from None
            except PromotionRefused as refused:
                await db.rollback()
                raise promotion_refusal(refused) from None
            except PaymentProviderError:
                await db.rollback()
                log.error("Stripe refused a Promotion withdraw refund", exc_info=True)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=PROMOTION_CHECKOUT_ERROR_MESSAGES[PROMOTION_ERROR_REFUND_PROVIDER],
                ) from None
            emits = await audit_withdrawals(db, [item])
            payload = await promotion_detail(db, item.promotion, now)
            organizer = await db.get(Organizer, item.promotion.organizer_id)
            event = await db.get(Event, item.promotion.event_id)
            await db.commit()
            for emit in emits:
                emit()
            if organizer is not None and event is not None:
                await notify_promotion_ended(
                    organizer, event, item.promotion, PROMOTION_WITHDRAWN_NOTE, False
                )
            return payload

    return await run_admin_job("Withdraw promotion", _run())


@router.post("/promotions/{promotion_id}/void", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_void_promotion(
    promotion_id: int, body: _PromotionReasonBody, request: Request
) -> dict:
    """`unpaid -> void` with a required reason, which is emailed to the
    Organizer in their locale. Releases every cap day."""
    reason = body.reason.strip()
    return await _run_promotion_command(
        promotion_id,
        ADMIN_ACTION_PROMOTION_VOID,
        lambda db, now: void_promotion(db, promotion_id, reason, now),
        {"reason": reason},
        notify_reason=reason,
        voided=True,
    )


@router.post("/promotions/{promotion_id}/refund", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_record_promotion_refund(
    promotion_id: int,
    body: _PromotionRefundBody,
    request: Request,
    gateway: PaymentGateway = Depends(get_payment_gateway),
) -> dict:
    """Refund gross `amount_cents` with a required note. Cumulative, capped at
    what was charged. An off-platform payment is only recorded; a Stripe-paid
    one is issued (credit note and card refund in one Stripe call), 502 when
    Stripe refuses and nothing is recorded. `refund_prefill` on the detail
    holds the suggested amount."""
    return await _run_promotion_command(
        promotion_id,
        ADMIN_ACTION_PROMOTION_REFUND,
        lambda db, now: record_refund(
            db, promotion_id, body.amount_cents, body.note, now, gateway=gateway
        ),
        {"amount_cents": body.amount_cents, "note": body.note.strip()},
    )
