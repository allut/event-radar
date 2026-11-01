"""POST /feedback, DELETE /feedback/{event_id}, GET /feedback/events.

Preference signals (like/dislike/bookmark, PREFERENCE_SIGNALS) are a
current-state model: one row per (user, event), enforced by a partial unique
index (migration 0019) — POST upserts, DELETE removes it. "view"/
"click_external" (the rest of VALID_SIGNALS) are passive analytics signals
fired on every page view / ticket-link click (frontend's
trackExternalClick()) and stay append-only/multi-row — they are NOT covered
by that index; a second partial unique index (migration 0055) caps them at
one row per (user, event, signal, UTC day), so POST inserts them with ON
CONFLICT DO NOTHING and DELETE/GET never touch them. Mixing the two under one upsert-by-(user,event) rule would
let a ticket click silently overwrite a user's bookmark.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app._generated.shared_constants import (
    BROWSE_PAGE_SIZE,
    PAGINATION_MAX_OFFSET,
    PROMOTION_REF_AD,
    VALID_SIGNALS,
)
from app.constants.events import ERROR_EVENT_NOT_FOUND
from app.constants.ranking import (
    BROWSE_MAX_PAGE_SIZE,
    ERROR_INVALID_PREFERENCE_SIGNAL,
    ERROR_INVALID_SIGNAL,
    PAGINATION_MIN_LIMIT,
    PAGINATION_MIN_OFFSET,
    PREFERENCE_SIGNALS,
    PREFERENCE_SIGNALS_SQL_PREDICATE,
    SIGNAL_DISLIKE,
)
from app.constants.promotions import PROMOTION_STAT_SLOT_DISLIKES
from app.constants.rate_limits import RATE_LIMIT_FEEDBACK
from app.db import get_db
from app.models.events import Event
from app.models.feeds import UserEventFeedback
from app.models.users import User
from app.promotions.counters import record_ref_hit
from app.rate_limit import limiter
from app.auth.dependencies import get_current_user
from app.routers.utils.serializers import (
    load_user_reported_events,
    resolve_locale_param,
    serialize_event,
)
from app.events.queries import public_event_filter, select_events_with_classification

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackBody(BaseModel):
    event_id: int
    signal: str
    # "ad" when the signal came from a Sponsored slot card (#606).
    ref: str | None = None


@router.post("", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_FEEDBACK)
async def record_feedback(
    body: FeedbackBody,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Record a feedback signal for an event."""
    if body.signal not in VALID_SIGNALS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_INVALID_SIGNAL.format(signals=sorted(VALID_SIGNALS)),
        )

    # Filtered to the same public-visibility predicate as GET /events/{id} —
    # db.get() would let an authenticated caller probe internal event-ID
    # existence (200 vs 404) and record signals against draft/hidden rows,
    # skewing personalization for events that were never publicly surfaced.
    event_id = await db.scalar(
        select(Event.id).where(Event.id == body.event_id, public_event_filter())
    )
    if event_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_EVENT_NOT_FOUND
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
        # Passive analytics signal (view/click_external) — append-only, but
        # bounded to one row per (user, event, signal, UTC day) by the partial
        # unique index (migration 0055, OWASP audit #9): a repeat within the
        # day is a silent no-op, so spamming the endpoint can't grow the
        # table. Target-less DO NOTHING — the day bucket is an expression
        # index, which ON CONFLICT can't name via index_elements.
        await db.execute(
            pg_insert(UserEventFeedback)
            .values(
                user_id=current_user.id,
                event_id=body.event_id,
                signal=body.signal,
            )
            .on_conflict_do_nothing()
        )

    if body.signal == SIGNAL_DISLIKE and body.ref == PROMOTION_REF_AD:
        await record_ref_hit(db, event_id, PROMOTION_STAT_SLOT_DISLIKES)

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
    if nothing matched.
    """
    await db.execute(
        delete(UserEventFeedback).where(
            UserEventFeedback.user_id == current_user.id,
            UserEventFeedback.event_id == event_id,
            UserEventFeedback.signal.in_(PREFERENCE_SIGNALS),
        )
    )
    await db.commit()
    return {"ok": True}


@router.get("/events")
@limiter.limit(RATE_LIMIT_FEEDBACK)
async def list_feedback_events(
    request: Request,
    signal: str,
    limit: int = Query(BROWSE_PAGE_SIZE, ge=PAGINATION_MIN_LIMIT, le=BROWSE_MAX_PAGE_SIZE),
    offset: int = Query(
        PAGINATION_MIN_OFFSET, ge=PAGINATION_MIN_OFFSET, le=PAGINATION_MAX_OFFSET
    ),
    locale: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List the current user's public events carrying a given preference
    signal, most-recently-signaled first. Powers the Saved Events page tabs.

    Restricted to PREFERENCE_SIGNALS (not the full VALID_SIGNALS): view/
    click_external can have multiple rows per (user, event), which would
    otherwise return the same event more than once.

    Offset-paged for the numbered pager (spec #551): every request returns
    the exact ``total`` with ``limit``/``offset``/``has_more``. The order is
    ``(created_at, feedback id)`` descending, so rows signaled in the same
    instant keep one order across pages.
    """
    if signal not in PREFERENCE_SIGNALS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_INVALID_PREFERENCE_SIGNAL.format(
                signals=sorted(PREFERENCE_SIGNALS)
            ),
        )

    page_conds = [
        UserEventFeedback.user_id == current_user.id,
        UserEventFeedback.signal == signal,
        public_event_filter(),
    ]
    total = (
        await db.scalar(
            select(func.count(UserEventFeedback.id))
            .select_from(UserEventFeedback)
            .join(Event, Event.id == UserEventFeedback.event_id)
            .where(*page_conds)
        )
    ) or 0
    # has_more via a limit+1 sentinel row, so it never depends on a COUNT that
    # can drift from the page query between the two statements.
    page_stmt = (
        select_events_with_classification()
        .join(
            UserEventFeedback,
            UserEventFeedback.event_id == Event.id,
        )
        .where(*page_conds)
        .order_by(UserEventFeedback.created_at.desc(), UserEventFeedback.id.desc())
        .limit(limit + 1)
        .offset(offset)
    )
    rows = (await db.execute(page_stmt)).all()
    has_more = len(rows) > limit
    events = [row[0] for row in rows[:limit]]

    feedback_by_event = {e.id: signal for e in events}
    reported = await load_user_reported_events(
        db, current_user.id, [e.id for e in events]
    )
    effective_locale = resolve_locale_param(locale, current_user.locale)

    return {
        "events": [
            serialize_event(
                e,
                locale=effective_locale,
                feedback_by_event=feedback_by_event,
                reported_event_ids=reported,
            )
            for e in events
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
    }
