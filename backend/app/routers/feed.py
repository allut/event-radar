"""GET /feed — today's personalized Daily 5 for the authenticated user."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import RATE_LIMIT_BROWSE, TALLINN_TZ
from app.db import get_db
from app.models.models import DailyFeed, Event, User
from app.rate_limit import limiter
from app.auth.dependencies import get_current_user
from app.routers.utils import (
    load_user_reported_events,
    load_user_signals,
    public_event_filter,
    resolve_locale_param,
    select_events_with_classification,
    serialize_event,
)

router = APIRouter(prefix="/feed", tags=["feed"])


@router.get("")
@limiter.limit(RATE_LIMIT_BROWSE)
async def get_feed(
    request: Request,
    locale: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return today's Daily 5 feed. Falls back to the most recent prior non-empty
    feed (flagged via `is_stale`) if today's has not been built yet."""
    today = datetime.now(TALLINN_TZ).date()

    feed = await db.scalar(
        select(DailyFeed).where(
            DailyFeed.user_id == current_user.id,
            DailyFeed.feed_date == today,
        )
    )

    if feed is None or not feed.event_ids:
        feed = await db.scalar(
            select(DailyFeed)
            .where(
                DailyFeed.user_id == current_user.id,
                DailyFeed.feed_date < today,
                func.cardinality(DailyFeed.event_ids) > 0,
            )
            .order_by(DailyFeed.feed_date.desc())
            .limit(1)
        )

    if feed is None or not feed.event_ids:
        return {
            "feed_date": today.isoformat(),
            "events": [],
            "built_at": None,
            "is_stale": False,
        }

    is_stale = feed.feed_date != today

    event_rows = (
        await db.scalars(
            select_events_with_classification().where(
                Event.id.in_(feed.event_ids),
                public_event_filter(),
            )
        )
    ).all()

    event_map = {e.id: e for e in event_rows}
    # Preserve the feed ordering from daily_feeds.event_ids
    events = [event_map[eid] for eid in feed.event_ids if eid in event_map]

    if not events:
        # Every event in this feed has since ended or been unpublished — a
        # stale feed hydrating to nothing is indistinguishable from "not
        # built yet" for the caller, so keep the same empty/not-stale shape
        # rather than returning is_stale: true with an empty events list.
        return {
            "feed_date": today.isoformat(),
            "events": [],
            "built_at": None,
            "is_stale": False,
        }

    event_ids = [e.id for e in events]
    sigs = await load_user_signals(db, current_user.id, event_ids)
    reported = await load_user_reported_events(db, current_user.id, event_ids)
    effective_locale = resolve_locale_param(locale, current_user.locale)

    return {
        "feed_date": feed.feed_date.isoformat(),
        "events": [
            serialize_event(
                e,
                locale=effective_locale,
                feedback_by_event=sigs,
                reported_event_ids=reported,
            )
            for e in events
        ],
        "built_at": feed.built_at.isoformat(),
        "is_stale": is_stale,
    }
