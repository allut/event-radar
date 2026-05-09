"""GET /events/{event_id} — full event detail."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.constants import EVENT_STATUS_PUBLISHED
from app.db import get_db
from app.models.models import Event

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/{event_id}")
async def get_event(
    event_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Return full event detail by ID. No auth required — events are public."""
    event = await db.scalar(
        select(Event)
        .where(Event.id == event_id, Event.status == EVENT_STATUS_PUBLISHED)
        .options(selectinload(Event.classification))
    )
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

    cl = event.classification
    return {
        "id": event.id,
        "slug": event.slug,
        "title": event.title_orig,
        "description": event.description_orig,
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
