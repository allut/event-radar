"""POST /feedback — record user feedback signals and invalidate cached scores."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import RATE_LIMIT_FEEDBACK, VALID_SIGNALS
from app.db import get_db
from app.models.models import Event, User, UserEventFeedback, UserEventScore
from app.rate_limit import limiter
from app.routers.auth import get_current_user
from app.routers.utils import public_event_filter

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
    """
    Record a feedback signal for an event.
    Invalidates the cached user_event_scores row so the next scoring pass is fresh.
    """
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

    db.add(
        UserEventFeedback(
            user_id=current_user.id,
            event_id=body.event_id,
            signal=body.signal,
        )
    )

    # Invalidate ALL cached scores for this user — not just the (user, event)
    # row. A signal on event A also moves the indirect-feedback term on any
    # other event that shares a category with A; per-row invalidation would
    # leave those neighbours' cached scores stale until the next direct signal.
    await db.execute(
        delete(UserEventScore).where(UserEventScore.user_id == current_user.id)
    )

    await db.commit()
    return {"ok": True}
