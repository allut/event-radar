"""POST /reports — file a report that a specific event is inappropriate.

Distinct from POST /feedback (a preference signal): a report is a
content-moderation notice with its own lifecycle (event_reports table,
open/resolved), reviewed by the admin over GET /admin/reports (a later
ticket). One row per (user, event) — re-reporting merges into the existing
row rather than creating a duplicate, and reopens it if it was resolved.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.events import ERROR_EVENT_NOT_FOUND
from app.constants.log_events import LOG_EVENT_REPORT_SUBMITTED
from app.constants.rate_limits import RATE_LIMIT_REPORT
from app._generated.shared_constants import REPORT_DETAIL_MAX_CHARS, REPORT_REASON_OTHER
from app.constants.reports import (
    ERROR_REPORT_DETAIL_REQUIRED,
    ERROR_REPORT_DETAIL_TOO_LONG,
    REPORT_STATUS_OPEN,
)
from app.db import get_db
from app.email.report_notify import send_report_notification
from app.models.events import Event, EventReport
from app.models.users import User
from app.rate_limit import limiter
from app.auth.dependencies import get_current_user
from app.promotions.promoted import is_event_promoted
from app.promotions.windows import now_tallinn, tallinn_today
from app.routers.utils import validate_report_reason
from app.events.queries import public_event_filter

log = logging.getLogger(__name__)
router = APIRouter(prefix="/reports", tags=["reports"])


class ReportBody(BaseModel):
    event_id: int
    reason: str
    is_illegal_allegation: bool = False
    # max_length rejects an oversized value during validation, before it's
    # fully materialized — the len() check below still runs (it also checks
    # the *stripped* length, which max_length can't express) but a multi-MB
    # payload no longer has to be parsed in full first (OWASP audit F16).
    detail: str | None = Field(default=None, max_length=REPORT_DETAIL_MAX_CHARS)


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
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_REPORT_DETAIL_REQUIRED,
        )
    if detail and len(detail) > REPORT_DETAIL_MAX_CHARS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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

    # Snapshot the open-report count *before* the upsert — the gate for the
    # first-open-report notification. Counting after the upsert can't tell a
    # genuine 0-to-1 transition apart from the same user re-submitting an
    # already-open report (the upsert unconditionally sets status=open, so a
    # post-commit COUNT would read 1 both times and re-notify on every edit).
    pre_upsert_open_count = await db.scalar(
        select(func.count())
        .select_from(EventReport)
        .where(
            EventReport.event_id == body.event_id,
            EventReport.status == REPORT_STATUS_OPEN,
        )
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

    # Fires only when this call is the genuine zero-to-one transition —
    # covers both a brand-new report and one that reopens a previously
    # fully-resolved event, but not a same-user edit of an already-open
    # report (pre_upsert_open_count would already be >= 1 in that case).
    if pre_upsert_open_count == 0:
        try:
            is_promoted = await is_event_promoted(
                db, body.event_id, tallinn_today(now_tallinn())
            )
            await send_report_notification(
                event,
                body.reason,
                detail,
                body.is_illegal_allegation,
                1,
                current_user.email,
                is_promoted=is_promoted,
            )
        except Exception:
            log.exception(
                "Failed to send report notification for event_id=%s", body.event_id
            )

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
