"""GET /public/showcase — unauthenticated landing-page event teaser.

A small, fixed-size grid of top-quality published events happening this week, for
the public landing page. No auth, no personalization, no PII — mirrors the
pure-SQL quality sort in browse.py::_browse_sql_path, minus every
user/feedback/persona concern, plus a symmetric date window (see _showcase_stmt).
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    DEFAULT_USER_LOCALE,
    RATE_LIMIT_PUBLIC,
    SHOWCASE_EVENT_COUNT,
    SHOWCASE_FALLBACK_WINDOW_DAYS,
    SHOWCASE_WINDOW_DAYS,
    TALLINN_TZ,
)
from app.db import get_db
from app.models.models import Event, EventClassification
from app.rate_limit import limiter
from app.routers.utils import (
    canonical_event_filter,
    event_not_ended_filter,
    public_event_filter,
    resolve_locale_param,
    select_events_with_classification,
    serialize_event,
)

router = APIRouter(prefix="/public", tags=["public"])


def _showcase_stmt(now: datetime, window_days: int) -> Select[tuple[Event]]:
    """Top-quality events starting within `window_days`, or already running and
    started within that same lookback — bounded on both sides so a long-lived
    listing (e.g. a museum's year-round entry ticket, valid for months) can't
    permanently occupy the "this week" grid just because it hasn't ended yet."""
    return (
        select_events_with_classification()
        .join(Event.classification)
        .where(
            public_event_filter(),
            event_not_ended_filter(now),
            canonical_event_filter(),
            Event.starts_at < now + timedelta(days=window_days),
            Event.starts_at >= now - timedelta(days=window_days),
        )
        .order_by(
            EventClassification.quality_score.desc().nulls_last(),
            Event.starts_at.asc(),
        )
        .limit(SHOWCASE_EVENT_COUNT)
    )


@router.get("/showcase")
@limiter.limit(RATE_LIMIT_PUBLIC)
async def showcase(
    request: Request,
    locale: str = Query(DEFAULT_USER_LOCALE),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Top-quality events happening this week, for the public landing page.

    No auth: anonymous visitors must be able to see real events before signing
    up. serialize_event is called without feedback signals (no user context).
    A thin week (fewer than SHOWCASE_EVENT_COUNT candidates) falls back to a
    wider window so the section never renders a near-empty grid.
    """
    locale = resolve_locale_param(locale, DEFAULT_USER_LOCALE)

    now = datetime.now(TALLINN_TZ)
    events = list((await db.scalars(_showcase_stmt(now, SHOWCASE_WINDOW_DAYS))).all())
    if len(events) < SHOWCASE_EVENT_COUNT:
        events = list(
            (
                await db.scalars(_showcase_stmt(now, SHOWCASE_FALLBACK_WINDOW_DAYS))
            ).all()
        )
    return {"events": [serialize_event(e, locale=locale) for e in events]}
