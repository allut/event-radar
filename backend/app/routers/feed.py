"""GET /feed — today's personalized Daily 5 for the authenticated user."""
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.constants import TALLINN_TZ
from app.db import get_db
from app.models.models import DailyFeed, Event, User
from app.routers.auth import get_current_user

router = APIRouter(prefix="/feed", tags=["feed"])


def _serialize_event(event: Event) -> dict:
    cl = event.classification
    return {
        "id": event.id,
        "slug": event.slug,
        "title": event.title_orig,
        "starts_at": event.starts_at.isoformat(),
        "ends_at": event.ends_at.isoformat() if event.ends_at else None,
        "venue_name": event.venue_name,
        "venue_address": event.venue_address,
        "lat": event.lat,
        "lng": event.lng,
        "url": event.url,
        "image_url": event.image_url,
        "price_min": float(event.price_min) if event.price_min is not None else None,
        "price_max": float(event.price_max) if event.price_max is not None else None,
        "currency": event.currency,
        "categories": cl.categories if cl else [],
        "vibes": cl.vibes if cl else [],
        "why_go": cl.why_go_bullets if cl else [],
        "quality_score": cl.quality_score if cl else None,
        "language": cl.language_detected if cl else None,
    }


@router.get("")
async def get_feed(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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
        select(Event)
        .where(Event.id.in_(feed.event_ids))
        .options(selectinload(Event.classification))
    )).all()

    event_map = {e.id: e for e in event_rows}
    # Preserve the feed ordering from daily_feeds.event_ids
    events = [event_map[eid] for eid in feed.event_ids if eid in event_map]

    return {
        "feed_date": today.isoformat(),
        "events": [_serialize_event(e) for e in events],
        "built_at": feed.built_at.isoformat(),
    }
