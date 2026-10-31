"""Admin endpoints — protected by the admin console session cookie."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, true

from app.auth.dependencies import get_current_admin
from app._generated.shared_constants import (
    ADMIN_PROMOTION_REQUESTS_PAGE_SIZE,
    CLAIM_STATUS_PENDING,
    PAGINATION_MAX_OFFSET,
    PROMOTION_DECLINE_REASON_MAX_CHARS,
)
from app.constants.admin import (
    ADMIN_ACTION_PROMOTION_REQUEST_DECLINE,
    ADMIN_ACTION_PROMOTION_REQUEST_GRANT,
)
from app.constants.events import (
    EVENT_STATUS_CANCELLED,
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
from app.constants.reports import (
    REPORT_STATUS_OPEN,
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
from app.models.models import (
    Claim,
    Event,
    EventReport,
    Organizer,
    Source,
)
from app.rate_limit import limiter
from app.routers.utils import (
    PromotionGrantBody,
    log_admin_action,
    promotion_refusal,
    run_admin_job,
)
from app.events.localize import (
    resolve_title,
)
from app.events.queries import canonical_event_filter

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")


# ---------------------------------------------------------------------------
# Claims queue (#420): grant/decline an admin-review-routed claim, revoke an
# already-granted one. Distinct from /admin/submissions (organizer-trust
# review) and /admin/reports (content moderation) — a claim's grant/decline/
# revoke is its own decision shape. See CONTEXT.md's Event Claiming glossary
# and app/claims/lifecycle.py for the organizer-facing create/cancel/recheck
# endpoints this complements.
# ---------------------------------------------------------------------------


@router.get("/counts", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_BROWSE, scope=RATE_LIMIT_SCOPE_ADMIN_READ)
async def admin_counts(request: Request) -> dict:
    """Open-reports + pending-submissions + pending-claims counts for the
    admin console landing screen (issue #154, extended #420). Mirrors the
    filters admin_list_reports/admin_list_submissions/admin_list_claims use
    for their own totals, so the landing tiles match what those screens show."""
    async with AsyncSessionLocal() as db:
        open_reports = (
            await db.scalar(
                select(func.count(func.distinct(EventReport.event_id)))
                .select_from(EventReport)
                .join(Event, Event.id == EventReport.event_id)
                .where(
                    EventReport.status == REPORT_STATUS_OPEN,
                    Event.status != EVENT_STATUS_CANCELLED,
                )
            )
        ) or 0
        pending_submissions = (
            await db.scalar(
                select(func.count(Event.id)).where(
                    Event.needs_review == true(),
                    Event.status != EVENT_STATUS_CANCELLED,
                )
            )
        ) or 0
        pending_claims = (
            await db.scalar(
                select(func.count(Claim.id)).where(Claim.status == CLAIM_STATUS_PENDING)
            )
        ) or 0

    return {
        "open_reports": open_reports,
        "pending_submissions": pending_submissions,
        "pending_claims": pending_claims,
    }


@router.get("/stats", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_stats(request: Request) -> dict:
    """Aggregate counts used by checkpoint tests and manual monitoring."""
    async with AsyncSessionLocal() as db:
        total, canonical = (
            await db.execute(
                select(
                    func.count(Event.id),
                    func.count(Event.id).filter(canonical_event_filter()),
                ).where(Event.status != EVENT_STATUS_CANCELLED)
            )
        ).one()

        sources_total = (await db.scalar(select(func.count(Source.id)))) or 0
        sources_enabled = (
            await db.scalar(
                select(func.count(Source.id)).where(Source.enabled == true())
            )
        ) or 0

    return {
        "events": {"total": total, "canonical": canonical},
        "sources": {"total": sources_total, "enabled": sources_enabled},
    }


# ---------------------------------------------------------------------------
# Promotions (#600): JSON API for the cap strip, the list and the grant form.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Promotion lifecycle (#601): detail and commands. Each command runs under the
# cap lock, writes its audit row in the same transaction and returns the
# refreshed detail payload.
# ---------------------------------------------------------------------------


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


