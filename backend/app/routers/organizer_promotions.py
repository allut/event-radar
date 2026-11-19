"""Organizer Promotions: request a Promotion, follow it, read its per-day
report (#614, #616).

Every route 404s while PROMOTIONS_OFFER_ENABLED is off (admin direct grants are
unaffected). Stays under /organizer/* so the organizer_session cookie, scoped
to Path=/api/organizer, reaches it.
"""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_organizer
from app.config import settings
from app.constants.events import ERROR_EVENT_NOT_FOUND
from app.constants.log_events import LOG_EVENT_EMAIL_SEND_FAILED
from app.constants.promotions import (
    ERROR_PROMOTION_NOT_FOUND,
    ERROR_PROMOTION_OFFER_DISABLED,
    ERROR_PROMOTION_REQUEST_NOT_FOUND,
    PROMOTION_ADVERTISER_NAME_MAX_CHARS,
    PROMOTION_BILLING_EMAIL_MAX_CHARS,
    PROMOTION_NOTE_MAX_CHARS,
    PROMOTION_REGISTRY_CODE_MAX_LEN,
)
from app.constants.rate_limits import RATE_LIMIT_BROWSE, RATE_LIMIT_SUBMIT
from app.db import get_db
from app.email.promotion_admin import send_request_notice
from app.models.events import Event
from app.models.promotions import Promotion
from app.models.organizers import Organizer
from app.promotions.grant import PromotionRefused, validate_grant
from app.promotions.organizer_view import (
    promotion_report,
    promotions_list,
    request_context,
    serialize_request,
)
from app.promotions.owners import resolve_owner_ids
from app.promotions.requests import RequestInput, RequestNotFound, create_request, withdraw_request
from app.promotions.views import validation_payload
from app.promotions.windows import now_tallinn
from app.events.localize import resolve_title
from app.rate_limit import limiter
from app.routers.utils.promotions import promotion_refusal

log = logging.getLogger(__name__)


async def require_offer_enabled() -> None:
    if not settings.PROMOTIONS_OFFER_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_PROMOTION_OFFER_DISABLED
        )


# Stays under /organizer/* deliberately (see organizer_events.py).
router = APIRouter(
    prefix="/organizer/promotions",
    tags=["organizer-promotions"],
    dependencies=[Depends(require_offer_enabled)],
)


class PromotionRequestBody(BaseModel):
    event_id: int
    start_date: date
    end_date: date
    advertiser_legal_name: str = Field(max_length=PROMOTION_ADVERTISER_NAME_MAX_CHARS)
    advertiser_registry_code: str = Field(max_length=PROMOTION_REGISTRY_CODE_MAX_LEN)
    billing_email: EmailStr | None = Field(
        default=None, max_length=PROMOTION_BILLING_EMAIL_MAX_CHARS
    )
    note: str | None = Field(default=None, max_length=PROMOTION_NOTE_MAX_CHARS)
    business_attested: bool = False
    terms_accepted: bool = False

    @field_validator("advertiser_legal_name", "advertiser_registry_code")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value


async def _own_event_or_404(db: AsyncSession, event_id: int, organizer: Organizer) -> Event:
    """The event, only when this Organizer currently owns it (submitter or an
    approved, non-dormant claim); 404 otherwise, whatever the reason."""
    event = await db.get(Event, event_id)
    if (
        event is None
        or (await resolve_owner_ids(db, [event])).get(event.id) != organizer.id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_EVENT_NOT_FOUND
        )
    return event


@router.get("")
@limiter.limit(RATE_LIMIT_BROWSE)
async def list_promotions(
    request: Request,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Requests and Promotions in one list, newest first. Each item's `status`
    is one of requested, declined, awaiting_payment, awaiting_checkout, scheduled, live, paused,
    finished, ended_early, cancelled; a paused item carries the fill gate's
    `paused_reason` code."""
    return {"items": await promotions_list(db, current_organizer, now_tallinn())}


@router.get("/context")
@limiter.limit(RATE_LIMIT_BROWSE)
async def promotion_request_context(
    request: Request,
    event_id: int = Query(...),
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The request form's context for one owned event: rules, price, the days
    already sold out (dates, never counts), whether it is promotable and
    whether card checkout is open for it (`checkout_available`, `review_required`)."""
    event = await _own_event_or_404(db, event_id, current_organizer)
    return await request_context(db, current_organizer, event, now_tallinn())


@router.get("/validate")
@limiter.limit(RATE_LIMIT_BROWSE)
async def validate_promotion_dates(
    request: Request,
    event_id: int = Query(...),
    start_date: date = Query(...),
    end_date: date = Query(...),
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Live date validation for the form: window, overlap and sold-out
    problems (full days listed as dates, no counts) and the price. Writes
    nothing."""
    event = await _own_event_or_404(db, event_id, current_organizer)
    violations = await validate_grant(db, event, start_date, end_date, now_tallinn())
    return validation_payload(start_date, end_date, violations, False)


@router.post("/requests", status_code=status.HTTP_201_CREATED)
@limiter.limit(RATE_LIMIT_SUBMIT)
async def create_promotion_request(
    body: PromotionRequestBody,
    request: Request,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Request a Promotion. Refused (409 request_pending / overlap /
    cap_exceeded / not_promotable, 429 daily_request_limit, 422 for window,
    registry code and terms rules) with `detail.errors` listing every rule
    broken. The admin is emailed after the commit."""
    event = await _own_event_or_404(db, body.event_id, current_organizer)
    try:
        promotion_request = await create_request(
            db,
            current_organizer.id,
            event,
            RequestInput(
                start_date=body.start_date,
                end_date=body.end_date,
                advertiser_legal_name=body.advertiser_legal_name,
                advertiser_registry_code=body.advertiser_registry_code,
                billing_email=str(body.billing_email or current_organizer.email),
                note=(body.note or "").strip() or None,
                business_attested=body.business_attested,
                terms_accepted=body.terms_accepted,
            ),
            now_tallinn(),
        )
    except PromotionRefused as refused:
        await db.rollback()
        raise promotion_refusal(refused) from None
    payload = serialize_request(promotion_request, resolve_title(event, current_organizer.locale))
    await db.commit()
    try:
        await send_request_notice(promotion_request, event, current_organizer)
    except Exception:
        log.error(
            "Failed to send promotion request notice (request_id=%s)",
            payload["id"],
            exc_info=True,
            extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
        )
    return payload


@router.post("/requests/{request_id}/withdraw")
@limiter.limit(RATE_LIMIT_SUBMIT)
async def withdraw_promotion_request(
    request_id: int,
    request: Request,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Withdraw a pending request (409 request_not_pending otherwise; 404 for
    another Organizer's)."""
    try:
        promotion_request = await withdraw_request(
            db, request_id, current_organizer.id, now_tallinn()
        )
    except RequestNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_PROMOTION_REQUEST_NOT_FOUND
        ) from None
    except PromotionRefused as refused:
        await db.rollback()
        raise promotion_refusal(refused) from None
    event = await db.get(Event, promotion_request.event_id)
    assert event is not None
    payload = serialize_request(promotion_request, resolve_title(event, current_organizer.locale))
    await db.commit()
    return payload


@router.get("/{promotion_id}/report")
@limiter.limit(RATE_LIMIT_BROWSE)
async def get_promotion_report(
    promotion_id: int,
    request: Request,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The per-day report for a Promotion this Organizer bought: complete days
    only, anonymous totals, no viewer data. It does not depend on current
    ownership, so it stays after a claim goes dormant or is revoked. Another
    Organizer's Promotion is a 404."""
    promotion = await db.get(Promotion, promotion_id)
    if promotion is None or promotion.organizer_id != current_organizer.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_PROMOTION_NOT_FOUND
        )
    return await promotion_report(db, promotion, now_tallinn())
