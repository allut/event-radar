"""Admin promotion-request queue — list, grant and decline organizer Promotion requests."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_admin
from app._generated.shared_constants import (
    ADMIN_PROMOTION_REQUESTS_PAGE_SIZE,
    PAGINATION_MAX_OFFSET,
    PROMOTION_DECLINE_REASON_MAX_CHARS,
)
from app.constants.admin import (
    ADMIN_ACTION_PROMOTION_REQUEST_DECLINE,
    ADMIN_ACTION_PROMOTION_REQUEST_GRANT,
)
from app.constants.log_events import LOG_EVENT_EMAIL_SEND_FAILED
from app.constants.ranking import (
    PAGINATION_MIN_LIMIT,
    PAGINATION_MIN_OFFSET,
)
from app.constants.promotions import (
    ADMIN_PROMOTIONS_MAX_PAGE_SIZE,
    ERROR_PROMOTION_ADVERTISER_LEGAL_NAME_REQUIRED,
    ERROR_PROMOTION_REQUEST_INVALID_STATUS,
    ERROR_PROMOTION_REQUEST_NOT_FOUND,
    PROMOTION_ERROR_MESSAGES,
    PROMOTION_ERROR_REASON_REQUIRED,
    PROMOTION_REQUEST_STATUS_PENDING,
    VALID_PROMOTION_REQUEST_STATUSES,
)
from app.constants.rate_limits import (
    RATE_LIMIT_ADMIN,
    RATE_LIMIT_BROWSE,
    RATE_LIMIT_SCOPE_ADMIN_READ,
)
from app.db import AsyncSessionLocal
from app.email.promotion_notice import (
    send_promotion_request_declined_email,
)
from app.promotions.request_queue import list_requests as list_promotion_requests
from app.promotions.request_queue import pending_count as pending_request_count
from app.promotions.requests import (
    RequestNotFound,
    decline_request as decline_promotion_request,
    grant_request as grant_promotion_request,
)
from app.promotions.grant import (
    GrantRequest,
    PromotionRefused,
)
from app.promotions.views import (
    serialize_promotion,
)
from app.promotions.windows import now_tallinn, tallinn_today
from app.models.events import Event
from app.models.organizers import Organizer
from app.rate_limit import limiter
from app.routers.utils import PromotionGrantBody, promotion_refusal
from app.routers.utils.admin import log_admin_action, run_admin_job
from app.events.localize import (
    resolve_title,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")


# ---------------------------------------------------------------------------
# Promotion requests (#615): the queue, grant and decline. Under
# /promotion-requests (not /promotions/requests) so the int path of
# /promotions/{promotion_id} never shadows it.
# ---------------------------------------------------------------------------


class _PromotionRequestDeclineBody(BaseModel):
    reason: str = Field(max_length=PROMOTION_DECLINE_REASON_MAX_CHARS)


@router.get("/promotion-requests", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_BROWSE, scope=RATE_LIMIT_SCOPE_ADMIN_READ)
async def admin_list_promotion_requests(
    request: Request,
    request_status: str = Query(PROMOTION_REQUEST_STATUS_PENDING, alias="status"),
    limit: int = Query(
        ADMIN_PROMOTION_REQUESTS_PAGE_SIZE,
        ge=PAGINATION_MIN_LIMIT,
        le=ADMIN_PROMOTIONS_MAX_PAGE_SIZE,
    ),
    offset: int = Query(
        PAGINATION_MIN_OFFSET, ge=PAGINATION_MIN_OFFSET, le=PAGINATION_MAX_OFFSET
    ),
) -> dict:
    """The request queue (pending by default, oldest first) with the pending
    count, each pending request's `not_eligible_reason` and its event's
    `promotion_restriction` tag."""
    if request_status not in VALID_PROMOTION_REQUEST_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_PROMOTION_REQUEST_INVALID_STATUS,
        )
    async with AsyncSessionLocal() as db:
        items, total = await list_promotion_requests(
            db, status=request_status, limit=limit, offset=offset, now=now_tallinn()
        )
        count = await pending_request_count(db)
    return {
        "pending_count": count,
        "requests": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
    }


@router.post(
    "/promotion-requests/{request_id}/grant",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_admin)],
)
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_grant_promotion_request(
    request_id: int, body: PromotionGrantBody, request: Request
) -> dict:
    """Grant a pending request from the form prefilled with it (dates and
    fields editable). Creates the Promotion and marks the request granted in
    one transaction, audited as promotion_request_grant. Same refusals as a
    direct grant, plus 409 request_not_pending / request_owner_changed. The
    Organizer is not emailed."""
    grant_request = GrantRequest(
        start_date=body.start_date,
        end_date=body.end_date,
        advertiser_legal_name=body.advertiser_legal_name.strip(),
        advertiser_registry_code=body.advertiser_registry_code.strip(),
        billing_email=str(body.billing_email) if body.billing_email else None,
        is_complimentary=body.is_complimentary,
        complimentary_note=body.complimentary_note,
        invoice_reference=(body.invoice_reference or "").strip() or None,
        restriction_clearance_confirmed=body.restriction_clearance_confirmed,
        restriction_clearance_note=body.restriction_clearance_note,
    )
    if not grant_request.advertiser_legal_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_PROMOTION_ADVERTISER_LEGAL_NAME_REQUIRED,
        )

    async def _run() -> dict:
        now = now_tallinn()
        async with AsyncSessionLocal() as db:
            try:
                promotion_request, promotion = await grant_promotion_request(
                    db, request_id, grant_request, now
                )
            except RequestNotFound:
                await db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=ERROR_PROMOTION_REQUEST_NOT_FOUND,
                ) from None
            except PromotionRefused as refused:
                await db.rollback()
                raise promotion_refusal(refused) from None
            emit_admin_log = log_admin_action(
                db,
                ADMIN_ACTION_PROMOTION_REQUEST_GRANT,
                promotion_request.id,
                {
                    "request_id": promotion_request.id,
                    "promotion_id": promotion.id,
                    "event_id": promotion.event_id,
                    "organizer_id": promotion.organizer_id,
                    "start_date": promotion.start_date.isoformat(),
                    "end_date": promotion.end_date.isoformat(),
                    "is_complimentary": promotion.is_complimentary,
                },
            )
            event = await db.get(Event, promotion.event_id)
            organizer = await db.get(Organizer, promotion.organizer_id)
            payload = serialize_promotion(
                promotion,
                event.title_orig if event else "",
                organizer.name if organizer else None,
                tallinn_today(now),
            )
            payload["request_id"] = promotion_request.id
            await db.commit()
            emit_admin_log()
            return payload

    return await run_admin_job("Grant promotion request", _run())


@router.post(
    "/promotion-requests/{request_id}/decline", dependencies=[Depends(get_current_admin)]
)
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_decline_promotion_request(
    request_id: int, body: _PromotionRequestDeclineBody, request: Request
) -> dict:
    """Decline a pending request. A reason is required (422 reason_required);
    it is emailed to the Organizer in their locale after the commit, and
    audited as promotion_request_decline."""
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": PROMOTION_ERROR_REASON_REQUIRED,
                "message": PROMOTION_ERROR_MESSAGES[PROMOTION_ERROR_REASON_REQUIRED],
            },
        )

    async def _run() -> dict:
        now = now_tallinn()
        async with AsyncSessionLocal() as db:
            try:
                promotion_request = await decline_promotion_request(db, request_id, reason, now)
            except RequestNotFound:
                await db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=ERROR_PROMOTION_REQUEST_NOT_FOUND,
                ) from None
            except PromotionRefused as refused:
                await db.rollback()
                raise promotion_refusal(refused) from None
            emit_admin_log = log_admin_action(
                db,
                ADMIN_ACTION_PROMOTION_REQUEST_DECLINE,
                promotion_request.id,
                {
                    "request_id": promotion_request.id,
                    "event_id": promotion_request.event_id,
                    "organizer_id": promotion_request.organizer_id,
                    "reason": reason,
                },
            )
            organizer = await db.get(Organizer, promotion_request.organizer_id)
            event = await db.get(Event, promotion_request.event_id)
            payload = {
                "id": promotion_request.id,
                "status": promotion_request.status,
                "decline_reason": promotion_request.decline_reason,
            }
            await db.commit()
            emit_admin_log()
            if organizer is not None and event is not None:
                try:
                    await send_promotion_request_declined_email(
                        organizer.email,
                        resolve_title(event, organizer.locale),
                        promotion_request.start_date,
                        promotion_request.end_date,
                        reason,
                        organizer.locale,
                    )
                except Exception:
                    log.error(
                        "Failed to send promotion request declined email (request_id=%s)",
                        promotion_request.id,
                        exc_info=True,
                        extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
                    )
            return payload

    return await run_admin_job("Decline promotion request", _run())
