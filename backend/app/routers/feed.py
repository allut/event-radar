"""GET /feed — today's personalized Daily 5 for the authenticated user."""
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import TALLINN_TZ
from app.db import get_db
from app.models.models import DailyFeed, Event, User
from app.routers.auth import get_current_user
from app.routers.utils import select_events_with_classification, serialize_event

router = APIRouter(prefix="/feed", tags=["feed"])



@router.get("")
async def get_feed(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return today's Daily 5 feed. Empty events list if feed has not been built yet."""
    today = datetime.now(TALLINN_TZ).date()

    feed = await db.scalar(
        select(DailyFeed).where(
            DailyFeed.user_id == current_user.id,
            DailyFeed.feed_date == today,
        )
    )

    if feed is None or not feed.event_ids:
        return {
            "feed_date": today.isoformat(),
            "events": [],
            "built_at": None,
        }

    event_rows = (await db.scalars(
        select_events_with_classification().where(Event.id.in_(feed.event_ids))
    )).all()

    event_map = {e.id: e for e in event_rows}
    # Preserve the feed ordering from daily_feeds.event_ids
    events = [event_map[eid] for eid in feed.event_ids if eid in event_map]

    return {
        "feed_date": today.isoformat(),
        "events": [serialize_event(e, locale=current_user.locale) for e in events],
        "built_at": feed.built_at.isoformat(),
    }
