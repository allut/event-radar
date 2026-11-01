"""Admin submission review queue — list, retract and approve organizer submissions."""


from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_admin
from app._generated.shared_constants import (
    ADMIN_REVIEW_QUEUE_PAGE_SIZE,
    PAGINATION_MAX_OFFSET,
)
from app.constants.admin import (
    ADMIN_ACTION_APPROVE_SUBMISSION,
    ADMIN_ACTION_RETRACT_SUBMISSION,
    ADMIN_REVIEW_QUEUE_MAX_PAGE_SIZE,
)
from app.constants.events import (
    EVENT_CANCELLATION_REASON_ADMIN_RETRACT,
    EVENT_STATUS_CANCELLED,
    EVENT_STATUS_CLASSIFIED,
)
from app.constants.organizer import ERROR_SUBMISSION_NOT_FOUND
from app.constants.ranking import (
    PAGINATION_MIN_LIMIT,
    PAGINATION_MIN_OFFSET,
)
from app.constants.rate_limits import (
    RATE_LIMIT_ADMIN,
    RATE_LIMIT_BROWSE,
    RATE_LIMIT_SCOPE_ADMIN_READ,
)
from app.constants.reports import (
    REPORT_AUTO_RESOLVE_NOTE,
)
from app.db import AsyncSessionLocal
from app.models.events import Event
from app.models.organizers import Organizer
from app.events.cancellation import (
    cancel_event_and_resolve_reports,
    send_report_resolution_emails,
)
from app.publish import publish_pending
from app.rate_limit import limiter
from app.routers.utils.serializers import serialize_event
from app.routers.utils.admin import (
    ResolutionBody,
    validated_resolution_note,
    log_admin_action,
    run_admin_job,
)
from app.events.queries import select_events_with_classification

router = APIRouter(prefix="/admin")


@router.get("/submissions", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_BROWSE, scope=RATE_LIMIT_SCOPE_ADMIN_READ)
async def admin_list_submissions(
    request: Request,
    limit: int = Query(
        ADMIN_REVIEW_QUEUE_PAGE_SIZE,
        ge=PAGINATION_MIN_LIMIT,
        le=ADMIN_REVIEW_QUEUE_MAX_PAGE_SIZE,
    ),
    offset: int = Query(
        PAGINATION_MIN_OFFSET, ge=PAGINATION_MIN_OFFSET, le=PAGINATION_MAX_OFFSET
    ),
) -> dict:
    """Post-hoc review queue: organizer-submitted events still flagged
    ``needs_review`` (set on submit/edit — see routers/organizer_events.py).
    These are already live (auto-publish); this is eyeballing, not a gate.
    Excludes cancelled submissions — retract already clears ``needs_review``,
    but this filter is defense-in-depth so a cancelled row can never clutter
    the queue regardless of that flag's state. Most recently submitted/edited
    first.
    """
    async with AsyncSessionLocal() as db:
        queue_filter = (Event.needs_review == true(), Event.status != EVENT_STATUS_CANCELLED)
        # Exact total on every page (spec #551): the numbered pager derives
        # its last page and past-end clamp from it.
        total = (
            await db.scalar(select(func.count(Event.id)).where(*queue_filter))
        ) or 0

        # id breaks created_at ties, so offset paging never repeats or skips
        # rows that share a timestamp.
        stmt = (
            select_events_with_classification()
            .where(*queue_filter)
            .order_by(Event.created_at.desc(), Event.id.desc())
            .limit(limit + 1)
            .offset(offset)
        )
        events = list((await db.scalars(stmt)).all())
        has_more = len(events) > limit
        events = events[:limit]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "events": [
            {
                **serialize_event(e),
                "status": e.status,
                "submitted_by_organizer_id": e.submitted_by_organizer_id,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ],
    }


async def _submission_or_404(db: AsyncSession, event_id: int) -> Event:
    event = await db.get(Event, event_id)
    if event is None or event.submitted_by_organizer_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_SUBMISSION_NOT_FOUND
        )
    return event


@router.post(
    "/submissions/{event_id}/retract", dependencies=[Depends(get_current_admin)]
)
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_retract_submission(
    event_id: int, body: ResolutionBody, request: Request
) -> dict:
    """Cancel an organizer-submitted event (soft delete — mirrors organizer's
    own DELETE /organizer/events/{id}; events are never hard-deleted). Also
    clears needs_review so this resolves the review-queue entry outright —
    admin_list_submissions additionally excludes cancelled events regardless."""
    note = validated_resolution_note(body)

    async def _run() -> dict:
        async with AsyncSessionLocal() as db:
            event = await _submission_or_404(db, event_id)
            event.needs_review = False
            resolved = await cancel_event_and_resolve_reports(
                db,
                event,
                EVENT_CANCELLATION_REASON_ADMIN_RETRACT,
                REPORT_AUTO_RESOLVE_NOTE,
            )
            result = {"id": event.id, "status": event.status, "note": note}
            emit_admin_log = log_admin_action(
                db, ADMIN_ACTION_RETRACT_SUBMISSION, event_id, result
            )
            await db.commit()
            emit_admin_log()
            await send_report_resolution_emails(
                db, event, resolved, REPORT_AUTO_RESOLVE_NOTE
            )
            return result

    return await run_admin_job("Retract submission", _run())


@router.post(
    "/submissions/{event_id}/approve", dependencies=[Depends(get_current_admin)]
)
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_approve_submission(
    event_id: int, body: ResolutionBody, request: Request
) -> dict:
    """Clear needs_review — an admin has eyeballed the submission and it's fine
    as-is. Also flips the submitting organizer to ``verified`` (a first-time
    approval is what makes an organizer trusted going forward — see
    Organizer.verified / app/publish.py) and runs the publish gate so this
    event (and any other now-eligible backlog) goes live immediately rather
    than waiting for the next scheduled publish_pending pass."""
    note = validated_resolution_note(body)

    async def _run() -> dict:
        async with AsyncSessionLocal() as db:
            event = await _submission_or_404(db, event_id)
            event.needs_review = False
            if event.submitted_by_organizer_id is not None:
                organizer = await db.get(Organizer, event.submitted_by_organizer_id)
                # FAQ #first-event-not-live describes this behaviour — update the copy (all locales) if it changes
                if organizer is not None:
                    organizer.verified = True
            # organizer.verified flipping True can unlock this organizer's
            # whole backlog, not just this event: scope the gate to their
            # classified events, so the request never scans every classified
            # row. Anyone else's eligible rows wait for the scheduled pass.
            # Diagnostic breakdown is unused by this endpoint's response.
            backlog_ids = (
                await db.scalars(
                    select(Event.id).where(
                        Event.submitted_by_organizer_id == event.submitted_by_organizer_id,
                        Event.status == EVENT_STATUS_CLASSIFIED,
                    )
                )
            ).all()
            await publish_pending(
                db, event_ids=list({event.id, *backlog_ids}), diagnostics=False
            )
            result = {"id": event.id, "needs_review": event.needs_review, "note": note}
            emit_admin_log = log_admin_action(
                db, ADMIN_ACTION_APPROVE_SUBMISSION, event_id, result
            )
            await db.commit()
            emit_admin_log()
            return result

    return await run_admin_job("Approve submission", _run())
