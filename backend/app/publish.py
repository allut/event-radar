"""Publish gate — promotes qualifying classified events to published."""

from datetime import datetime
from typing import cast

from sqlalchemy import and_, func, or_, select, update
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


async def publish_pending(db: AsyncSession) -> dict:
    """Promote classified events that pass the publish gate to published.

    Single bulk UPDATE, no N+1. The caller commits. Idempotent: only reads
    'classified' and writes 'published', so re-running after the backlog
    drains is a no-op — scheduler ordering relative to classify_pending
    doesn't matter, stragglers are picked up on the next cycle.

    Gate (all must hold): quality_score >= PUBLISH_MIN_QUALITY_SCORE (joined
    from event_classifications), starts_at in the future, title_orig present,
    is_explicit is false, is_out_of_area is false (LLM location signal), and
    present lat/lng coords must fall within the Tallinn region bbox (defense-in-depth;
    coords-less events pass).
    """
    now = datetime.now(TALLINN_TZ)
    lat_min, lat_max, lng_min, lng_max = TALLINN_REGION_BBOX
    qualifying_ids = select(EventClassification.event_id).where(
        EventClassification.quality_score >= PUBLISH_MIN_QUALITY_SCORE
    )
    stmt = (
        update(Event)
        .where(
            Event.status == EVENT_STATUS_CLASSIFIED,
            Event.is_explicit.is_(False),
            Event.is_out_of_area.is_(False),
            Event.starts_at >= now,
            func.trim(Event.title_orig) != "",
            Event.id.in_(qualifying_ids),
            or_(
                and_(Event.lat.is_(None), Event.lng.is_(None)),
                and_(
                    Event.lat.is_not(None),
                    Event.lng.is_not(None),
                    Event.lat.between(lat_min, lat_max),
                    Event.lng.between(lng_min, lng_max),
                ),
            ),
        )
        .values(status=EVENT_STATUS_PUBLISHED)
    )
    result = await db.execute(stmt)
    return {"published": cast(CursorResult, result).rowcount}
