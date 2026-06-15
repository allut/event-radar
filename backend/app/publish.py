"""Publish gate — promotes qualifying classified events to published."""

from datetime import datetime
from typing import cast

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    EVENT_STATUS_CLASSIFIED,
    EVENT_STATUS_PUBLISHED,
    PUBLISH_MIN_QUALITY_SCORE,
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
    and is_explicit is false. Events that fail the gate stay 'classified' for
    admin audit and are never served.
    """
    now = datetime.now(TALLINN_TZ)
    qualifying_ids = select(EventClassification.event_id).where(
        EventClassification.quality_score >= PUBLISH_MIN_QUALITY_SCORE
    )
    stmt = (
        update(Event)
        .where(
            Event.status == EVENT_STATUS_CLASSIFIED,
            Event.is_explicit.is_(False),
            Event.starts_at >= now,
            func.trim(Event.title_orig) != "",
            Event.id.in_(qualifying_ids),
        )
        .values(status=EVENT_STATUS_PUBLISHED)
    )
    result = await db.execute(stmt)
    return {"published": cast(CursorResult, result).rowcount}
