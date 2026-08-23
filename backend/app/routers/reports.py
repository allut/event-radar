"""POST /reports — file a report that a specific event is inappropriate.

Distinct from POST /feedback (a preference signal): a report is a
content-moderation notice with its own lifecycle (event_reports table,
open/resolved), reviewed by the admin over GET /admin/reports (a later
ticket). One row per (user, event) — re-reporting merges into the existing
row rather than creating a duplicate, and reopens it if it was resolved.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    ERROR_EVENT_NOT_FOUND,
    ERROR_REPORT_DETAIL_REQUIRED,
    ERROR_REPORT_DETAIL_TOO_LONG,
    LOG_EVENT_REPORT_SUBMITTED,
    RATE_LIMIT_REPORT,
    REPORT_DETAIL_MAX_CHARS,
    REPORT_REASON_OTHER,
    REPORT_STATUS_OPEN,
)
from app.db import get_db
from app.models.models import Event, EventReport, User
from app.rate_limit import limiter
from app.routers.auth import get_current_user
from app.routers.utils import public_event_filter, validate_report_reason

log = logging.getLogger(__name__)
router = APIRouter(prefix="/reports", tags=["reports"])


class ReportBody(BaseModel):
    event_id: int
    reason: str
    is_illegal_allegation: bool = False
    detail: str | None = None


@router.post("", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_REPORT)
async def submit_report(
    body: ReportBody,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    validate_report_reason(body.reason)

    detail = (body.detail or "").strip() or None
    if not detail and (body.reason == REPORT_REASON_OTHER or body.is_illegal_allegation):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=ERROR_REPORT_DETAIL_REQUIRED,
        )
    if detail and len(detail) > REPORT_DETAIL_MAX_CHARS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=ERROR_REPORT_DETAIL_TOO_LONG.format(max_chars=REPORT_DETAIL_MAX_CHARS),
        )

    # Filtered to the same public-visibility predicate as POST /feedback — an
    # authenticated caller must not be able to enumerate draft/internal event
    # IDs via 200-vs-404 responses.
    event = await db.scalar(
        select(Event).where(Event.id == body.event_id, public_event_filter())
    )
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_EVENT_NOT_FOUND
        )

    # Upsert against the (user_id, event_id) unique index. Re-reporting an
    # already-open row merges the latest reason/detail into it rather than
    # creating a duplicate; re-reporting a resolved row reopens it — both
    # cases are covered by the same unconditional DO UPDATE.
    stmt = (
        pg_insert(EventReport)
        .values(
            user_id=current_user.id,
            event_id=body.event_id,
            reason=body.reason,
            is_illegal_allegation=body.is_illegal_allegation,
            detail=detail,
        )
        .on_conflict_do_update(
            index_elements=[EventReport.user_id, EventReport.event_id],
            set_={
                "reason": body.reason,
                "is_illegal_allegation": body.is_illegal_allegation,
                "detail": detail,
                "status": REPORT_STATUS_OPEN,
                "resolved_at": None,
                "resolution_note": None,
            },
        )
    )
    await db.execute(stmt)
    await db.commit()

    log.info(
        "report submitted: event_id=%s illegal=%s",
        body.event_id,
        body.is_illegal_allegation,
        extra={
            "event": LOG_EVENT_REPORT_SUBMITTED,
            "event_id": body.event_id,
            "is_illegal_allegation": body.is_illegal_allegation,
        },
    )
    return {"ok": True}
