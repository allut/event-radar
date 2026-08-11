"""GET /events/{event_id} — full event detail."""

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import DEFAULT_USER_LOCALE, RATE_LIMIT_EVENTS_DETAIL, SESSION_COOKIE_NAME
from app.db import get_db
from app.models.models import Event, User
from app.rate_limit import limiter
from app.routers.utils import (
    load_user_signals,
    parse_session_cookie_user,
    public_event_filter,
    resolve_locale_param,
    select_events_with_classification,
    serialize_event,
)

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/{event_id}")
@limiter.limit(RATE_LIMIT_EVENTS_DETAIL)
async def get_event(
    event_id: int,
    request: Request,
    locale_query: str | None = Query(None, alias="locale"),
    db: AsyncSession = Depends(get_db),
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
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

    # Parse the session cookie once and reuse it for both locale and signal
    # hydration — avoids a second token parse and a second user lookup.
    parsed = parse_session_cookie_user(session)
    locale = DEFAULT_USER_LOCALE
    sigs: dict[int, str] = {}
    if parsed is not None:
        user_id, token_version = parsed
        user = await db.get(User, user_id)
        # A revoked token (post logout-all) must not resolve a user here —
        # otherwise this optional-auth endpoint leaks locale + my_signal after
        # the user believed all sessions were signed out.
        if user is not None and token_version == user.session_token_version:
            locale = user.locale
            sigs = await load_user_signals(db, user_id, [event.id])

    effective_locale = resolve_locale_param(locale_query, locale)

    return serialize_event(event, locale=effective_locale, feedback_by_event=sigs)
