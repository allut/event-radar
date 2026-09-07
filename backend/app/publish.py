"""Publish gate — promotes qualifying classified events to published."""

from datetime import datetime
from typing import cast

from sqlalchemy import and_, case, func, literal, or_, select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    EVENT_STATUS_CLASSIFIED,
    EVENT_STATUS_PUBLISHED,
    PUBLISH_DIAGNOSTICS_WINDOW_DAYS,
    PUBLISH_MIN_QUALITY_SCORE,
    TALLINN_REGION_BBOX,
    TALLINN_TZ,
)
from app.models.models import Event, EventClassification, Organizer
from app.routers.utils import event_ended_filter, event_not_ended_filter


async def publish_pending(
    db: AsyncSession,
    *,
    event_ids: list[int] | None = None,
    diagnostics: bool = True,
) -> dict:
    """Promote classified events that pass the publish gate to published.

    Single bulk UPDATE, no N+1. The caller commits. Idempotent: only reads
    'classified' and writes 'published', so re-running after the backlog
    drains is a no-op — scheduler ordering relative to classify_pending
    doesn't matter, stragglers are picked up on the next cycle.

    ``event_ids``, when given, additionally scopes the UPDATE to those rows —
    used by callers that just inserted/classified a single known event and
    don't need (or want to pay for) a full-table scan. Leave it ``None`` when
    other now-eligible rows might also need to flip (e.g. approving an
    organizer's first submission makes their whole backlog eligible, not just
    the approved row).

    ``diagnostics=False`` skips the reject-breakdown SELECT below and returns
    only ``published``. That SELECT aggregates over every event still stuck in
    'classified' — a set that only grows, since a permanently-failing event
    never leaves that status — so its cost is proportional to all-time reject
    history, not to this call's work. Fine on the scheduled job; too expensive
    to pay inline on a request. Callers that don't consume the breakdown
    fields should pass ``False``.

    Gate (all must hold): quality_score >= PUBLISH_MIN_QUALITY_SCORE (joined
    from event_classifications), event not yet ended (live until ``ends_at``,
    or ``starts_at`` when ``ends_at`` is unset — see ``event_not_ended_filter``),
    title_orig present, is_explicit is false, is_non_event is false (gift
    cards, merch, online webinars — keyword prefilter + LLM signal), is_out_of_area
    is false (LLM location signal), present lat/lng coords must fall within
    the Tallinn region bbox (defense-in-depth; coords-less events pass), and —
    for an organizer submission — the submitting ``Organizer.verified`` is
    true (a brand-new self-registered organizer's first submission stays
    ``classified``/``needs_review`` until an admin approves it via
    ``POST /admin/submissions/{id}/approve``, which flips ``verified``; every
    non-organizer event is unaffected).

    After the UPDATE, a diagnostic SELECT over the events still left in
    'classified' (the rejects) breaks down per-reason counts. Reasons are
    non-exclusive — one event can fail several gates — so they need not sum
    to the total reject count. Bounded to the last PUBLISH_DIAGNOSTICS_WINDOW_DAYS
    (by starts_at) — an operator signal about recent rejects, not an all-time
    audit total; see PUBLISH_DIAGNOSTICS_WINDOW_DAYS in constants.py.
    """
    now = datetime.now(TALLINN_TZ)
    lat_min, lat_max, lng_min, lng_max = TALLINN_REGION_BBOX
    bbox_ok = or_(
        and_(Event.lat.is_(None), Event.lng.is_(None)),
        and_(
            Event.lat.is_not(None),
            Event.lng.is_not(None),
            Event.lat.between(lat_min, lat_max),
            Event.lng.between(lng_min, lng_max),
        ),
    )
    qualifying_ids = select(EventClassification.event_id).where(
        EventClassification.quality_score >= PUBLISH_MIN_QUALITY_SCORE
    )
    unverified_organizer_ids = select(Organizer.id).where(
        Organizer.verified.is_(False)
    )
    # NULL-safe: a non-organizer event's submitted_by_organizer_id is NULL, and
    # "NULL NOT IN (...)" evaluates to SQL NULL (not TRUE) regardless of the
    # subquery's contents, which would silently exclude every non-organizer
    # event from the gate — the explicit IS NULL branch avoids that.
    organizer_ok = or_(
        Event.submitted_by_organizer_id.is_(None),
        Event.submitted_by_organizer_id.not_in(unverified_organizer_ids),
    )
    update_conds = [
        Event.status == EVENT_STATUS_CLASSIFIED,
        Event.is_explicit.is_(False),
        Event.is_non_event.is_(False),
        Event.is_out_of_area.is_(False),
        event_not_ended_filter(now),
        func.trim(Event.title_orig) != "",
        Event.id.in_(qualifying_ids),
        bbox_ok,
        organizer_ok,
    ]
    if event_ids is not None:
        update_conds.append(Event.id.in_(event_ids))
    stmt = update(Event).where(*update_conds).values(status=EVENT_STATUS_PUBLISHED)
    result = await db.execute(stmt)
    summary: dict = {"published": cast(CursorResult, result).rowcount}

    if not diagnostics:
        return summary

    reject_stmt = (
        select(
            func.count().label("unpublished"),
            func.sum(
                case(
                    (
                        or_(
                            EventClassification.quality_score.is_(None),
                            EventClassification.quality_score
                            < PUBLISH_MIN_QUALITY_SCORE,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("fail_quality"),
            func.sum(case((Event.is_explicit.is_(True), 1), else_=0)).label(
                "fail_explicit"
            ),
            func.sum(case((Event.is_non_event.is_(True), 1), else_=0)).label(
                "fail_non_event"
            ),
            func.sum(case((Event.is_out_of_area.is_(True), 1), else_=0)).label(
                "fail_out_of_area"
            ),
            func.sum(case((event_ended_filter(now), 1), else_=0)).label(
                "fail_ended"
            ),
            func.sum(
                case(
                    (
                        or_(
                            Event.title_orig.is_(None),
                            func.trim(Event.title_orig) == "",
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("fail_no_title"),
            func.sum(case((~bbox_ok, 1), else_=0)).label("fail_coords_bbox"),
            func.sum(case((~organizer_ok, 1), else_=0)).label(
                "fail_unverified_organizer"
            ),
        )
        .select_from(Event)
        .outerjoin(EventClassification, EventClassification.event_id == Event.id)
        .where(
            Event.status == EVENT_STATUS_CLASSIFIED,
            Event.starts_at
            # f-string is safe here only because PUBLISH_DIAGNOSTICS_WINDOW_DAYS is a
            # fixed int constant, never request-derived — do not parameterize this with
            # request input without switching to a bound parameter.
            >= literal(now)
            - text(f"INTERVAL '{PUBLISH_DIAGNOSTICS_WINDOW_DAYS} days'"),
        )
    )
    reject_row = (await db.execute(reject_stmt)).one()
    summary.update(
        {
            "unpublished": reject_row.unpublished or 0,
            "fail_quality": reject_row.fail_quality or 0,
            "fail_explicit": reject_row.fail_explicit or 0,
            "fail_non_event": reject_row.fail_non_event or 0,
            "fail_out_of_area": reject_row.fail_out_of_area or 0,
            "fail_unverified_organizer": reject_row.fail_unverified_organizer or 0,
            "fail_ended": reject_row.fail_ended or 0,
            "fail_no_title": reject_row.fail_no_title or 0,
            "fail_coords_bbox": reject_row.fail_coords_bbox or 0,
        }
    )
    return summary
