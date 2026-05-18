"""GET /events/{event_id} — full event detail."""
from fastapi import APIRouter, Depends, Header, HTTPException, status
from itsdangerous import BadSignature, SignatureExpired
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.tokens import verify_session_token
from app.constants import DEFAULT_USER_LOCALE, EVENT_STATUS_PUBLISHED
from app.db import get_db
from app.models.models import Event, User
from app.routers.utils import serialize_event

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/{event_id}")
async def get_event(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    """Return full event detail by ID. No auth required — events are public."""
    event = await db.scalar(
        select(Event)
        .where(Event.id == event_id, Event.status == EVENT_STATUS_PUBLISHED)
        .options(selectinload(Event.classification))
    )
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

    locale = DEFAULT_USER_LOCALE
    if isinstance(authorization, str) and authorization.startswith("Bearer "):
        try:
            user_id = verify_session_token(authorization[len("Bearer "):])
            user = await db.get(User, user_id)
            if user:
                locale = user.locale
        except (SignatureExpired, BadSignature):
            pass

    return serialize_event(event, locale=locale)
