"""GET /events/{event_id} — full event detail."""

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import EVENT_STATUS_PUBLISHED, RATE_LIMIT_EVENTS_DETAIL
from app.db import get_db
from app.models.models import Event
from app.rate_limit import limiter
from app.routers.utils import (
    get_optional_user_locale,
    select_events_with_classification,
    serialize_event,
)

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/{event_id}")
@limiter.limit(RATE_LIMIT_EVENTS_DETAIL)
async def get_event(
    event_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> dict:
    """Return full event detail by ID. No auth required — events are public."""
    event = await db.scalar(
        select_events_with_classification().where(
            Event.id == event_id,
            Event.status == EVENT_STATUS_PUBLISHED,
            Event.is_explicit.is_(False),
            Event.is_non_event.is_(False),
        )
    )
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Event not found"
        )

    locale = await get_optional_user_locale(authorization, db)
    return serialize_event(event, locale=locale)
