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
    ERROR_EVENT_NOT_FOUND,
    ERROR_INVALID_PREFERENCE_SIGNAL,
    ERROR_INVALID_SIGNAL,
    PAGINATION_MAX_OFFSET,
    PAGINATION_MIN_LIMIT,
    PAGINATION_MIN_OFFSET,
    PREFERENCE_SIGNALS,
    PREFERENCE_SIGNALS_SQL_PREDICATE,
    RATE_LIMIT_FEEDBACK,
    SCORE_AFFECTING_SIGNALS,
    VALID_SIGNALS,
)
from app.db import get_db
from app.models.models import Event, User, UserEventFeedback
from app.rate_limit import limiter
from app.routers.auth import get_current_user
from app.routers.utils import (
    invalidate_user_scores,
    load_user_reported_events,
    public_event_filter,
    resolve_locale_param,
    select_events_with_classification,
    serialize_event,
)

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackBody(BaseModel):
    event_id: int
    signal: str


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
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_INVALID_SIGNAL.format(signals=sorted(VALID_SIGNALS)),
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
        # Passive analytics signal (view/click_external) — always append a
        # fresh row, never upsert; not covered by the partial unique index.
        db.add(
            UserEventFeedback(
                user_id=current_user.id,
                event_id=body.event_id,
                signal=body.signal,
            )
        )

    # Only like/dislike feed into ranking/score.py's scoring — a bookmark or a
    # passive view/click_external signal never changes a score, so gating here
    # keeps the cache warm across ticket clicks and bookmarks (see
    # SCORE_AFFECTING_SIGNALS).
    if body.signal in SCORE_AFFECTING_SIGNALS:
        await invalidate_user_scores(db, current_user.id)
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
    if nothing matched. Invalidates cached scores only if the removed signal
    was one that actually affects scoring (see SCORE_AFFECTING_SIGNALS) — the
    deleted row's signal isn't known up front, so RETURNING reports it.
    """
    deleted_signals = (
        await db.execute(
            delete(UserEventFeedback)
            .where(
                UserEventFeedback.user_id == current_user.id,
                UserEventFeedback.event_id == event_id,
                UserEventFeedback.signal.in_(PREFERENCE_SIGNALS),
            )
            .returning(UserEventFeedback.signal)
        )
    ).scalars().all()
    if SCORE_AFFECTING_SIGNALS.intersection(deleted_signals):
        await invalidate_user_scores(db, current_user.id)
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
    """
    if signal not in PREFERENCE_SIGNALS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_INVALID_PREFERENCE_SIGNAL.format(
                signals=sorted(PREFERENCE_SIGNALS)
            ),
        )

    # See browse.py's _browse_sql_path for the rationale: total only on the
    # first page, has_more via a limit+1 sentinel row instead of total.
    total: int | None = None
    if offset == 0:
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
        .limit(limit + 1)
        .offset(offset)
    )
    events = list((await db.scalars(page_stmt)).all())
    has_more = len(events) > limit
    events = events[:limit]

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
