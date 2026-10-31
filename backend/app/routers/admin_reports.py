"""Admin report queue — list, resolve and take down reported events."""


from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select, true
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_admin
from app._generated.shared_constants import (
    ADMIN_REPORTS_QUEUE_PAGE_SIZE,
    DEFAULT_USER_LOCALE,
    PAGINATION_MAX_OFFSET,
)
from app.constants.admin import (
    ADMIN_ACTION_RESOLVE_REPORTS,
    ADMIN_ACTION_TAKEDOWN_REPORTED_EVENT,
    ADMIN_REPORTS_QUEUE_MAX_PAGE_SIZE,
)
from app.constants.core import SQL_BIGINT_MAX
from app.constants.events import (
    EVENT_CANCELLATION_REASON_REPORT_TAKEDOWN,
    EVENT_STATUS_CANCELLED,
)
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
    REPORT_STATUS_OPEN,
)
from app.db import AsyncSessionLocal
from app.promotions.promoted import promoted_clause
from app.promotions.windows import now_tallinn, tallinn_today
from app.models.events import Event, EventReport
from app.events.cancellation import (
    cancel_event_and_resolve_reports,
    resolve_open_reports,
    send_report_resolution_emails,
)
from app.rate_limit import limiter
from app.routers.utils import (
    ResolutionBody,
    event_or_404,
    validated_resolution_note,
    log_admin_action,
    run_admin_job,
    validate_report_reason,
)
from app.events.venue import (
    resolve_venue_name,
)

router = APIRouter(prefix="/admin")


@router.get("/reports", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_BROWSE, scope=RATE_LIMIT_SCOPE_ADMIN_READ)
async def admin_list_reports(
    request: Request,
    reason: str | None = Query(None),
    illegal_only: bool = Query(False),
    limit: int = Query(
        ADMIN_REPORTS_QUEUE_PAGE_SIZE,
        ge=PAGINATION_MIN_LIMIT,
        le=ADMIN_REPORTS_QUEUE_MAX_PAGE_SIZE,
    ),
    offset: int = Query(
        PAGINATION_MIN_OFFSET, ge=PAGINATION_MIN_OFFSET, le=PAGINATION_MAX_OFFSET
    ),
    report: int | None = Query(None, ge=1, le=SQL_BIGINT_MAX),
) -> dict:
    """Content-moderation review queue: one row per event aggregating its
    REPORT_STATUS_OPEN reports (distinct from GET /admin/submissions, which
    is organizer-trust review — see CONTEXT.md's Report/Resolve glossary).
    Excludes cancelled events. ``reason``/``illegal_only`` narrow which
    events qualify for the queue (an event with at least one matching open
    report); each qualifying event's row still aggregates *all* of its open
    reports, not just the matching ones. Ordered promoted-first (an event with a live paid Promotion, `is_promoted`), then illegal-first, then by
    report count, then oldest-waiting first, then event id (so offset paging
    never repeats or skips rows that tie on the first three keys).

    ``report=<event_id>`` (the admin email deep link) locates that event's row
    in the queue and returns the page holding it, with the real ``offset``;
    the ``offset`` param is ignored. If the event is no longer in the queue
    (already resolved), page 1 is returned with ``report_not_found`` true.
    """
    if reason is not None:
        validate_report_reason(reason)

    agg_conditions = [
        EventReport.status == REPORT_STATUS_OPEN,
        Event.status != EVENT_STATUS_CANCELLED,
    ]
    # With no reason/illegal_only filter, "at least one matching open report"
    # degenerates to "has an open report" — already covered by the OPEN
    # condition above, so the DISTINCT event_id subquery (a full scan of
    # open reports on every plain queue load, the console's default view)
    # is a no-op and skipped (Big-O audit #5, item 2.10).
    if reason is not None or illegal_only:
        match_conditions = [EventReport.status == REPORT_STATUS_OPEN]
        if reason is not None:
            match_conditions.append(EventReport.reason == reason)
        if illegal_only:
            match_conditions.append(EventReport.is_illegal_allegation == true())
        matching_event_ids = (
            select(EventReport.event_id).where(*match_conditions).distinct()
        )
        agg_conditions.append(EventReport.event_id.in_(matching_event_ids))

    has_illegal_col = func.bool_or(EventReport.is_illegal_allegation).label(
        "has_illegal_allegation"
    )
    report_count_col = func.count(EventReport.id).label("report_count")
    oldest_col = func.min(EventReport.created_at).label("oldest_open_report_at")
    # "Promoted" (#612): a live paid Promotion on the event. Sorts first.
    promoted_col = promoted_clause(
        EventReport.event_id, tallinn_today(now_tallinn())
    ).label("is_promoted")

    agg = (
        select(
            EventReport.event_id,
            promoted_col,
            has_illegal_col,
            report_count_col,
            oldest_col,
        )
        .join(Event, Event.id == EventReport.event_id)
        .where(*agg_conditions)
        .group_by(EventReport.event_id)
    )

    order_keys = (
        promoted_col.desc(),
        has_illegal_col.desc(),
        report_count_col.desc(),
        oldest_col.asc(),
        EventReport.event_id.asc(),
    )

    async with AsyncSessionLocal() as db:
        # Exact total on every page (spec #551): the numbered pager derives
        # its last page and past-end clamp from it.
        total = (
            await db.scalar(select(func.count()).select_from(agg.subquery()))
        ) or 0

        report_not_found = False
        if report is not None:
            # One ROW_NUMBER() over the same four sort keys gives the row's
            # position; its page starts at the multiple of limit at or below.
            ranked = agg.add_columns(
                func.row_number().over(order_by=order_keys).label("position")
            ).subquery()
            position = await db.scalar(
                select(ranked.c.position).where(ranked.c.event_id == report)
            )
            if position is None:
                report_not_found = True
                offset = PAGINATION_MIN_OFFSET
            else:
                offset = (position - 1) // limit * limit

        page = (
            await db.execute(
                agg.order_by(*order_keys).limit(limit + 1).offset(offset)
            )
        ).all()
        has_more = len(page) > limit
        page = page[:limit]

        event_ids = [row.event_id for row in page]
        events_by_id: dict[int, Event] = {}
        reports_by_event: dict[int, list[EventReport]] = {}
        if event_ids:
            events = (
                await db.scalars(
                    select(Event)
                    .options(selectinload(Event.venue))
                    .where(Event.id.in_(event_ids))
                )
            ).all()
            events_by_id = {e.id: e for e in events}

            reports = (
                await db.scalars(
                    select(EventReport)
                    .where(
                        EventReport.event_id.in_(event_ids),
                        EventReport.status == REPORT_STATUS_OPEN,
                    )
                    .order_by(EventReport.created_at.asc())
                )
            ).all()
            for r in reports:
                reports_by_event.setdefault(r.event_id, []).append(r)

    rows = []
    for row in page:
        event = events_by_id.get(row.event_id)
        if event is None:
            continue
        event_reports = reports_by_event.get(row.event_id, [])
        rows.append(
            {
                "event_id": event.id,
                "title": event.title_orig,
                "status": event.status,
                "venue": resolve_venue_name(event, DEFAULT_USER_LOCALE),
                "submitted_by_organizer_id": event.submitted_by_organizer_id,
                "report_count": row.report_count,
                "reasons": sorted({r.reason for r in event_reports}),
                "has_illegal_allegation": bool(row.has_illegal_allegation),
                "is_promoted": bool(row.is_promoted),
                "reports": [
                    {
                        "reason": r.reason,
                        "detail": r.detail,
                        "is_illegal_allegation": r.is_illegal_allegation,
                        "created_at": r.created_at,
                    }
                    for r in event_reports
                ],
                "oldest_open_report_at": row.oldest_open_report_at,
            }
        )

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "events": rows,
        "report_not_found": report_not_found,
    }


@router.post(
    "/reports/{event_id}/resolve", dependencies=[Depends(get_current_admin)]
)
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_resolve_reports(
    event_id: int, body: ResolutionBody, request: Request
) -> dict:
    """Close every open report on the event with an admin-supplied note.
    No event mutation — the lightweight "this is fine" action. Never
    immunizes the event: a fresh report on a resolved row reopens it (see
    routers/reports.py's upsert-reopen semantics)."""
    note = validated_resolution_note(body)

    async def _run() -> dict:
        async with AsyncSessionLocal() as db:
            event = await event_or_404(db, event_id)
            resolved = await resolve_open_reports(db, event, note)
            result = {"event_id": event.id, "resolved_count": len(resolved)}
            emit_admin_log = log_admin_action(
                db, ADMIN_ACTION_RESOLVE_REPORTS, event_id, result
            )
            await db.commit()
            emit_admin_log()
            await send_report_resolution_emails(db, event, resolved, note)
            return result

    return await run_admin_job("Resolve reports", _run())


@router.post(
    "/reports/{event_id}/takedown", dependencies=[Depends(get_current_admin)]
)
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_takedown_reported_event(
    event_id: int, body: ResolutionBody, request: Request
) -> dict:
    """Cancel the event and auto-resolve its open reports with the same
    note — the decisive action for content that actually needs to come
    down. Never touches Organizer.verified."""
    note = validated_resolution_note(body)

    async def _run() -> dict:
        async with AsyncSessionLocal() as db:
            event = await event_or_404(db, event_id)
            resolved = await cancel_event_and_resolve_reports(
                db, event, EVENT_CANCELLATION_REASON_REPORT_TAKEDOWN, note
            )
            result = {
                "event_id": event.id,
                "status": event.status,
                "resolved_count": len(resolved),
            }
            emit_admin_log = log_admin_action(
                db, ADMIN_ACTION_TAKEDOWN_REPORTED_EVENT, event_id, result
            )
            await db.commit()
            emit_admin_log()
            await send_report_resolution_emails(db, event, resolved, note)
            return result

    return await run_admin_job("Takedown reported event", _run())
