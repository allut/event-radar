"""Promotion command helpers shared by the admin and organizer promotion routers."""

import logging
from collections.abc import Callable
from datetime import date

from fastapi import HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app._generated.shared_constants import (
    PROMOTION_ERROR_REQUEST_DAILY_LIMIT,
)
from app.config import settings
from app.constants.admin import ADMIN_ACTION_PROMOTION_END, ADMIN_ACTION_PROMOTION_REFUND
from app.constants.log_events import LOG_EVENT_EMAIL_SEND_FAILED
from app.constants.promotions import (
    ERROR_PROMOTION_SLOTS_STILL_ENABLED,
    PROMOTION_END_REASON_FEATURE_WITHDRAWN,
    PROMOTION_WITHDRAWN_NOTE,
    PROMOTION_WITHDRAWN_REFUND_NOTE,
    PROMOTION_ADVERTISER_NAME_MAX_CHARS,
    PROMOTION_BILLING_EMAIL_MAX_CHARS,
    PROMOTION_CONFLICT_ERROR_CODES,
    PROMOTION_INVOICE_REFERENCE_MAX_LEN,
    PROMOTION_NOTE_MAX_CHARS,
    PROMOTION_REGISTRY_CODE_MAX_LEN,
)
from app.email.promotion_notice import send_promotion_ended_email, send_promotion_void_email
from app.events.localize import resolve_title
from app.models.events import Event
from app.models.organizers import Organizer
from app.models.promotions import Promotion
from app.promotions.grant import PromotionRefused
from app.promotions.withdraw import WithdrawResult
from app.routers.utils.admin import log_admin_action

log = logging.getLogger(__name__)


def promotion_refusal(refused: PromotionRefused) -> HTTPException:
    """409 when the state of things forbids the command, 429 for the daily
    request ceiling, 422 for bad input; `detail.errors` lists every rule
    broken."""
    codes = [v.code for v in refused.violations]
    if any(c in PROMOTION_CONFLICT_ERROR_CODES for c in codes):
        code = status.HTTP_409_CONFLICT
    elif PROMOTION_ERROR_REQUEST_DAILY_LIMIT in codes:
        code = status.HTTP_429_TOO_MANY_REQUESTS
    else:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(
        status_code=code,
        detail={
            "code": refused.violations[0].code,
            "message": refused.violations[0].message,
            "errors": [v.as_dict() for v in refused.violations],
        },
    )


class PromotionGrantBody(BaseModel):
    start_date: date
    end_date: date
    advertiser_legal_name: str = Field(max_length=PROMOTION_ADVERTISER_NAME_MAX_CHARS)
    advertiser_registry_code: str = Field(max_length=PROMOTION_REGISTRY_CODE_MAX_LEN)
    billing_email: EmailStr | None = Field(
        default=None, max_length=PROMOTION_BILLING_EMAIL_MAX_CHARS
    )
    is_complimentary: bool = False
    complimentary_note: str | None = Field(default=None, max_length=PROMOTION_NOTE_MAX_CHARS)
    invoice_reference: str | None = Field(default=None, max_length=PROMOTION_INVOICE_REFERENCE_MAX_LEN)
    # Required (both) when the event carries a Promotion restriction (#612).
    restriction_clearance_confirmed: bool = False
    restriction_clearance_note: str | None = Field(default=None, max_length=PROMOTION_NOTE_MAX_CHARS)


def promotion_audit_summary(promotion: Promotion) -> dict:
    return {
        "promotion_id": promotion.id,
        "event_id": promotion.event_id,
        "organizer_id": promotion.organizer_id,
        "status": promotion.status,
        "start_date": promotion.start_date.isoformat(),
        "end_date": promotion.end_date.isoformat(),
        "days": promotion.days,
        "net_price_cents": promotion.net_price_cents,
        "refunded_cents": promotion.refunded_cents,
    }


async def notify_promotion_ended(
    organizer: Organizer, event: Event, promotion: Promotion, reason: str, voided: bool
) -> None:
    """Email the Organizer the reason, in their locale. Best-effort after the
    commit: a failed send is logged, never undoes the command."""
    send = send_promotion_void_email if voided else send_promotion_ended_email
    try:
        await send(
            organizer.email,
            resolve_title(event, organizer.locale),
            promotion.start_date,
            promotion.end_date,
            reason,
            organizer.locale,
        )
    except Exception:
        log.error(
            "Failed to send promotion %s email (promotion_id=%s)",
            "void" if voided else "ended",
            promotion.id,
            exc_info=True,
            extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
        )


def withdraw_audit(result: WithdrawResult) -> dict:
    return {
        **promotion_audit_summary(result.promotion),
        "reason": PROMOTION_WITHDRAWN_NOTE,
        "end_reason": PROMOTION_END_REASON_FEATURE_WITHDRAWN,
        "unused_days": result.unused_days,
        "refund_cents": result.refund_cents,
    }


async def audit_withdrawals(db: AsyncSession, results: list[WithdrawResult]) -> list[Callable[[], None]]:
    emits: list[Callable[[], None]] = []
    for item in results:
        emits.append(
            log_admin_action(
                db, ADMIN_ACTION_PROMOTION_END, item.promotion.id, withdraw_audit(item)
            )
        )
        if item.refund_cents > 0:
            emits.append(
                log_admin_action(
                    db,
                    ADMIN_ACTION_PROMOTION_REFUND,
                    item.promotion.id,
                    {**promotion_audit_summary(item.promotion), "amount_cents": item.refund_cents,
                     "note": PROMOTION_WITHDRAWN_REFUND_NOTE},
                )
            )
    return emits


def withdraw_guard() -> None:
    """Withdraw only runs after the slots flag is off (step two of the
    runbook), so no ad is still being served while Promotions end."""
    if settings.PROMOTIONS_SLOTS_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=ERROR_PROMOTION_SLOTS_STILL_ENABLED
        )
