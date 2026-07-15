"""POST /feedback, DELETE /feedback/{event_id}, GET /feedback/events.

Preference signals (like/dislike/bookmark, PREFERENCE_SIGNALS) are a
current-state model: one row per (user, event), enforced by a partial unique
index (migration 0019) — POST upserts, DELETE removes it. "view"/
"click_external" (the rest of VALID_SIGNALS) are passive analytics signals
fired on every page view / ticket-link click (frontend's
trackExternalClick()) and stay append-only/multi-row — they are NOT covered
by that index, so POST always inserts a fresh row for them and DELETE/GET
never touch them. Mixing the two under one upsert-by-(user,event) rule would
let a ticket click silently overwrite a user's bookmark.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    BROWSE_MAX_PAGE_SIZE,
    BROWSE_PAGE_SIZE,
    PREFERENCE_SIGNALS,
    PREFERENCE_SIGNALS_SQL_PREDICATE,
    RATE_LIMIT_FEEDBACK,
    VALID_SIGNALS,
)
from app.db import get_db
from app.models.models import Event, User, UserEventFeedback, UserEventScore
from app.rate_limit import limiter
from app.routers.auth import get_current_user
from app.routers.utils import (
    public_event_filter,
    select_events_with_classification,
    serialize_event,
)

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackBody(BaseModel):
    event_id: int
    signal: str


async def _invalidate_scores(db: AsyncSession, user_id: int) -> None:
    """Invalidate ALL cached scores for this user — not just the (user, event)
    row. A signal on event A also moves the indirect-feedback term on any
    other event that shares a category with A; per-row invalidation would
    leave those neighbours' cached scores stale until the next direct signal.
    """
    await db.execute(delete(UserEventScore).where(UserEventScore.user_id == user_id))


@router.post("", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_FEEDBACK)
async def record_feedback(
    body: FeedbackBody,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upsert a feedback signal for an event and invalidate cached scores."""
    if body.signal not in VALID_SIGNALS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid signal. Must be one of: {sorted(VALID_SIGNALS)}",
        )

    # Filtered to the same public-visibility predicate as GET /events/{id} —
    # db.get() would let an authenticated caller probe internal event-ID
    # existence (200 vs 404) and record signals against draft/hidden rows,
    # skewing personalization for events that were never publicly surfaced.
    event = await db.scalar(
        select(Event).where(Event.id == body.event_id, public_event_filter())
    )
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Event not found"
        )

    if body.signal in PREFERENCE_SIGNALS:
        # Upsert against the partial unique index — one current row per
        # (user, event) among like/dislike/bookmark only.
        stmt = (
            pg_insert(UserEventFeedback)
            .values(
                user_id=current_user.id,
                event_id=body.event_id,
                signal=body.signal,
            )
            .on_conflict_do_update(
                index_elements=[
                    UserEventFeedback.user_id,
                    UserEventFeedback.event_id,
                ],
                index_where=text(PREFERENCE_SIGNALS_SQL_PREDICATE),
                set_={"signal": body.signal, "created_at": func.now()},
            )
        )
        await db.execute(stmt)
    else:
        # Passive analytics signal (view/click_external) — always append a
        # fresh row, never upsert; not covered by the partial unique index.
        db.add(
            UserEventFeedback(
                user_id=current_user.id,
                event_id=body.event_id,
                signal=body.signal,
            )
        )

    await _invalidate_scores(db, current_user.id)
    await db.commit()
    return {"ok": True}


@router.delete("/{event_id}", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_FEEDBACK)
async def delete_feedback(
    event_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remove the current user's preference signal for an event (uncheck).

    Scoped to PREFERENCE_SIGNALS only — this must never delete the
    view/click_external analytics history for the event. Idempotent — no 404
    if nothing matched. Invalidates cached scores same as a POST, since
    removing a signal changes ranking too.
    """
    await db.execute(
        delete(UserEventFeedback).where(
            UserEventFeedback.user_id == current_user.id,
            UserEventFeedback.event_id == event_id,
            UserEventFeedback.signal.in_(PREFERENCE_SIGNALS),
        )
    )
    await _invalidate_scores(db, current_user.id)
    await db.commit()
    return {"ok": True}


@router.get("/events")
@limiter.limit(RATE_LIMIT_FEEDBACK)
async def list_feedback_events(
    request: Request,
    signal: str,
    limit: int = Query(BROWSE_PAGE_SIZE, ge=1, le=BROWSE_MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List the current user's public events carrying a given preference
    signal, most-recently-signaled first. Powers the Saved Events page tabs.

    Restricted to PREFERENCE_SIGNALS (not the full VALID_SIGNALS): view/
    click_external can have multiple rows per (user, event), which would
    otherwise return the same event more than once.
    """
    if signal not in PREFERENCE_SIGNALS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"signal must be one of: {sorted(PREFERENCE_SIGNALS)}",
        )

    total = (
        await db.scalar(
            select(func.count(UserEventFeedback.id))
            .select_from(UserEventFeedback)
            .join(Event, Event.id == UserEventFeedback.event_id)
            .where(
                UserEventFeedback.user_id == current_user.id,
                UserEventFeedback.signal == signal,
                public_event_filter(),
            )
        )
    ) or 0

    page_stmt = (
        select_events_with_classification()
        .join(
            UserEventFeedback,
            UserEventFeedback.event_id == Event.id,
        )
        .where(
            UserEventFeedback.user_id == current_user.id,
            UserEventFeedback.signal == signal,
            public_event_filter(),
        )
        .order_by(UserEventFeedback.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    events = list((await db.scalars(page_stmt)).all())

    feedback_by_event = {e.id: signal for e in events}

    return {
        "events": [
            serialize_event(e, locale=current_user.locale, feedback_by_event=feedback_by_event)
            for e in events
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(events) < total,
    }
