"""GET /public/showcase — unauthenticated landing-page event teaser.

A small, fixed-size grid of top-quality upcoming published events for the public
landing page. No auth, no personalization, no PII — mirrors the pure-SQL quality
sort in browse.py::_browse_sql_path, minus every user/feedback/persona concern.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    DEFAULT_USER_LOCALE,
    RATE_LIMIT_PUBLIC,
    SHOWCASE_EVENT_COUNT,
    TALLINN_TZ,
    VALID_LOCALES,
)
from app.db import get_db
from app.models.models import Event, EventClassification
from app.rate_limit import limiter
from app.routers.utils import (
    canonical_event_filter,
    event_not_ended_filter,
    public_event_filter,
    select_events_with_classification,
    serialize_event,
)

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/showcase")
@limiter.limit(RATE_LIMIT_PUBLIC)
async def showcase(
    request: Request,
    locale: str = Query(DEFAULT_USER_LOCALE),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Top-quality upcoming published events for the public landing page.

    No auth: anonymous visitors must be able to see real events before signing
    up. serialize_event is called without feedback signals (no user context).
    """
    if locale not in VALID_LOCALES:
        locale = DEFAULT_USER_LOCALE

    now = datetime.now(TALLINN_TZ)
    stmt = (
        select_events_with_classification()
        .join(Event.classification)
        .where(
            public_event_filter(),
            event_not_ended_filter(now),
            canonical_event_filter(),
        )
        .order_by(EventClassification.quality_score.desc().nulls_last())
        .limit(SHOWCASE_EVENT_COUNT)
    )
    events = list((await db.scalars(stmt)).all())
    return {"events": [serialize_event(e, locale=locale) for e in events]}
