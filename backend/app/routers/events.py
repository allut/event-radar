"""GET /events/{event_id} — full event detail."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.constants import EVENT_STATUS_PUBLISHED
from app.db import get_db
from app.models.models import Event
from app.routers.utils import serialize_event

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

    return serialize_event(event)
