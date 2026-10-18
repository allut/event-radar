"""Admin read side of Promotion requests (#615): the queue with each request's
not-eligible reason and restriction tag."""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.promotions import (
    PROMOTION_ERROR_NOT_PROMOTABLE,
    PROMOTION_NOT_SHOWING_NOT_OWNED,
    PROMOTION_REQUEST_STATUS_PENDING,
    PROMOTION_DAY_PRICE_CENTS,
    PROMOTION_VAT_RATE_PERCENT,
)
from app.models.models import Event, Organizer, PromotionRequest
from app.promotions.grant import validate_grant
from app.promotions.owners import resolve_owner_ids
from app.promotions.requests import promotable_event_ids
from app.promotions.views import price_breakdown


async def pending_count(db: AsyncSession) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(PromotionRequest)
            .where(PromotionRequest.status == PROMOTION_REQUEST_STATUS_PENDING)
        )
    ) or 0


async def list_requests(
    db: AsyncSession, *, status: str, limit: int, offset: int, now: datetime
) -> tuple[list[dict], int]:
    """One page of requests in a status, oldest first for the pending queue and
    newest first otherwise. A pending row carries `not_eligible_reason`: why a
    grant as requested would be refused right now (null when it would not), and
    `promotion_restriction` (null = unassessed, `none` = clear, else the tag)."""
    where = [PromotionRequest.status == status]
    total = (await db.scalar(select(func.count()).select_from(PromotionRequest).where(*where))) or 0
    pending = status == PROMOTION_REQUEST_STATUS_PENDING
    order = (
        (PromotionRequest.created_at, PromotionRequest.id)
        if pending
        else (PromotionRequest.created_at.desc(), PromotionRequest.id.desc())
    )
    rows = (
        await db.execute(
            select(PromotionRequest, Event, Organizer)
            .join(Event, Event.id == PromotionRequest.event_id)
            .join(Organizer, Organizer.id == PromotionRequest.organizer_id)
            .where(*where)
            .order_by(*order)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    events = [e for _, e, _ in rows]
    owners = await resolve_owner_ids(db, events) if pending else {}
    promotable = await promotable_event_ids(db, events, now) if pending else set()

    items: list[dict] = []
    for request, event, organizer in rows:
        reason: str | None = None
        if pending:
            if event.id not in promotable:
                reason = PROMOTION_ERROR_NOT_PROMOTABLE
            elif owners.get(event.id) != request.organizer_id:
                reason = PROMOTION_NOT_SHOWING_NOT_OWNED
            else:
                violations = await validate_grant(
                    db, event, request.start_date, request.end_date, now
                )
                reason = violations[0].code if violations else None
        days = (request.end_date - request.start_date).days + 1
        items.append(
            {
                "id": request.id,
                "event_id": event.id,
                "event_title": event.title_orig,
                "organizer_id": organizer.id,
                "organizer_name": organizer.name,
                "organizer_email": organizer.email,
                "status": request.status,
                "start_date": request.start_date.isoformat(),
                "end_date": request.end_date.isoformat(),
                "days": days,
                "price": price_breakdown(
                    days * PROMOTION_DAY_PRICE_CENTS, PROMOTION_VAT_RATE_PERCENT
                ),
                "advertiser_legal_name": request.advertiser_legal_name,
                "advertiser_registry_code": request.advertiser_registry_code,
                "billing_email": request.billing_email,
                "note": request.note,
                "decline_reason": request.decline_reason,
                "terms_version": request.terms_version,
                "promotion_restriction": event.promotion_restriction,
                "not_eligible_reason": reason,
                "created_at": request.created_at.isoformat(),
                "resolved_at": request.resolved_at.isoformat() if request.resolved_at else None,
            }
        )
    return items, total
