"""GET /events/{event_id} — full event detail."""

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.claims.lifecycle import claim_status_for_event
from app.constants import (
    DEFAULT_USER_LOCALE,
    ERROR_EVENT_NOT_FOUND,
    RATE_LIMIT_EVENTS_DETAIL,
    SESSION_COOKIE_NAME,
)
from app.db import get_db
from app.models.models import Event, User
from app.rate_limit import limiter
from app.routers.utils import (
    load_user_reported_events,
    load_user_signals,
    parse_session_cookie_user,
    public_event_filter,
    resolve_locale_param,
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
    # joinedload, not select_events_with_classification()'s selectinload — this
    # is a single-row fetch, so one JOINed query beats the extra round trips
    # selectinload pays to stay O(1) across the bulk-listing callers that
    # share that helper (Big-O audit #5, item 2.10).
    event = await db.scalar(
        select(Event)
        .options(joinedload(Event.classification), joinedload(Event.venue))
        .where(
            Event.id == event_id,
            public_event_filter(),
        )
    )
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_EVENT_NOT_FOUND
        )

    # Parse the session cookie once and reuse it for both locale and signal
    # hydration — avoids a second token parse and a second user lookup.
    parsed = parse_session_cookie_user(session)
    locale = DEFAULT_USER_LOCALE
    sigs: dict[int, str] = {}
    reported: set[int] = set()
    if parsed is not None:
        user_id, token_version = parsed
        user = await db.get(User, user_id)
        # A revoked token (post logout-all) must not resolve a user here —
        # otherwise this optional-auth endpoint leaks locale + my_signal after
        # the user believed all sessions were signed out.
        if user is not None and token_version == user.session_token_version:
            locale = user.locale
            sigs = await load_user_signals(db, user_id, [event.id])
            reported = await load_user_reported_events(db, user_id, [event.id])

    effective_locale = resolve_locale_param(locale_query, locale)

    serialized = serialize_event(
        event,
        locale=effective_locale,
        feedback_by_event=sigs,
        reported_event_ids=reported,
    )
    # claim_status (#414) is computed only here, not in serialize_event
    # itself — the claim CTA is public-event-page-only, so the bulk-listing
    # callers of serialize_event (feed/explore/saved) shouldn't each pay for
    # a per-event EventSource+Claim lookup they never render.
    serialized["claim_status"] = await claim_status_for_event(db, event)
    return serialized
