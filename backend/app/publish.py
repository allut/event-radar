"""Publish gate — promotes qualifying classified events to published."""

from datetime import datetime
from typing import cast

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    EVENT_STATUS_CLASSIFIED,
    EVENT_STATUS_PUBLISHED,
    PUBLISH_MIN_QUALITY_SCORE,
    TALLINN_REGION_BBOX,
    TALLINN_TZ,
)
from app.models.models import Event, EventClassification
from app.routers.utils import event_ended_filter, event_not_ended_filter


async def publish_pending(db: AsyncSession) -> dict:
    """Promote classified events that pass the publish gate to published.

    Single bulk UPDATE, no N+1. The caller commits. Idempotent: only reads
    'classified' and writes 'published', so re-running after the backlog
    drains is a no-op — scheduler ordering relative to classify_pending
    doesn't matter, stragglers are picked up on the next cycle.

    Gate (all must hold): quality_score >= PUBLISH_MIN_QUALITY_SCORE (joined
    from event_classifications), event not yet ended (live until ``ends_at``,
    or ``starts_at`` when ``ends_at`` is unset — see ``event_not_ended_filter``),
    title_orig present, is_explicit is false, is_non_event is false (gift
    cards, merch, online webinars — keyword prefilter + LLM signal), is_out_of_area
    is false (LLM location signal), and present lat/lng coords must fall within
    the Tallinn region bbox (defense-in-depth; coords-less events pass).

    After the UPDATE, a diagnostic SELECT over the events still left in
    'classified' (the rejects) breaks down per-reason counts. Reasons are
    non-exclusive — one event can fail several gates — so they need not sum
    to the total reject count.
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
    stmt = (
        update(Event)
        .where(
            Event.status == EVENT_STATUS_CLASSIFIED,
            Event.is_explicit.is_(False),
            Event.is_non_event.is_(False),
            Event.is_out_of_area.is_(False),
            event_not_ended_filter(now),
            func.trim(Event.title_orig) != "",
            Event.id.in_(qualifying_ids),
            bbox_ok,
        )
        .values(status=EVENT_STATUS_PUBLISHED)
    )
    result = await db.execute(stmt)
    summary: dict = {"published": cast(CursorResult, result).rowcount}

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
        )
        .select_from(Event)
        .outerjoin(EventClassification, EventClassification.event_id == Event.id)
        .where(Event.status == EVENT_STATUS_CLASSIFIED)
    )
    reject_row = (await db.execute(reject_stmt)).one()
    summary.update(
        {
            "unpublished": reject_row.unpublished or 0,
            "fail_quality": reject_row.fail_quality or 0,
            "fail_explicit": reject_row.fail_explicit or 0,
            "fail_non_event": reject_row.fail_non_event or 0,
            "fail_out_of_area": reject_row.fail_out_of_area or 0,
            "fail_ended": reject_row.fail_ended or 0,
            "fail_no_title": reject_row.fail_no_title or 0,
            "fail_coords_bbox": reject_row.fail_coords_bbox or 0,
        }
    )
    return summary
