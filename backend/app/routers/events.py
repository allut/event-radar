"""GET /events/{event_id} — full event detail."""

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import DEFAULT_USER_LOCALE, RATE_LIMIT_EVENTS_DETAIL
from app.db import get_db
from app.models.models import Event, User
from app.rate_limit import limiter
from app.routers.utils import (
    load_user_signals,
    parse_bearer_user,
    public_event_filter,
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
            public_event_filter(),
        )
    )
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Event not found"
        )

    # Parse the bearer token once and reuse it for both locale and signal
    # hydration — avoids a second token parse and a second user lookup.
    parsed = parse_bearer_user(authorization)
    locale = DEFAULT_USER_LOCALE
    sigs: dict[int, str] = {}
    if parsed is not None:
        user_id, _token_version = parsed
        user = await db.get(User, user_id)
        locale = user.locale if user else DEFAULT_USER_LOCALE
        sigs = await load_user_signals(db, user_id, [event.id])

    return serialize_event(event, locale=locale, feedback_by_event=sigs)
