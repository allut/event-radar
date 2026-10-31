"""GET /feed — today's personalized Daily 5 for the authenticated user."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants.core import TALLINN_TZ
from app.constants.promotions import PROMOTION_EXPLANATION_DAILY5
from app.constants.rate_limits import RATE_LIMIT_BROWSE
from app.db import get_db
from app.models.events import Event
from app.models.feeds import DailyFeed
from app.models.users import User
from app.rate_limit import limiter
from app.auth.dependencies import get_current_user
from app.routers.utils import (
    load_user_reported_events,
    load_user_signals,
    resolve_locale_param,
    serialize_event,
)
from app.events.queries import public_event_filter, select_events_with_classification
from app.promotions.daily5 import resolve_feed_slot

router = APIRouter(prefix="/feed", tags=["feed"])


@router.get("")
@limiter.limit(RATE_LIMIT_BROWSE)
async def get_feed(
    request: Request,
    locale: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return today's Daily 5 feed. Falls back to the most recent prior non-empty
    feed (flagged via `is_stale`) if today's has not been built yet."""
    now = datetime.now(TALLINN_TZ)
    today = now.date()

    feed = await db.scalar(
        select(DailyFeed).where(
            DailyFeed.user_id == current_user.id,
            DailyFeed.feed_date == today,
        )
    )

    if feed is None or not feed.event_ids:
        feed = await db.scalar(
            select(DailyFeed)
            .where(
                DailyFeed.user_id == current_user.id,
                DailyFeed.feed_date < today,
                func.cardinality(DailyFeed.event_ids) > 0,
            )
            .order_by(DailyFeed.feed_date.desc())
            .limit(1)
        )

    if feed is None or not feed.event_ids:
        return {
            "feed_date": today.isoformat(),
            "events": [],
            "built_at": None,
            "is_stale": False,
        }

    is_stale = feed.feed_date != today

    event_rows = (
        await db.scalars(
            select_events_with_classification().where(
                Event.id.in_(feed.event_ids),
                public_event_filter(),
            )
        )
    ).all()

    event_map = {e.id: e for e in event_rows}
    # Preserve the feed ordering from daily_feeds.event_ids
    events = [event_map[eid] for eid in feed.event_ids if eid in event_map]

    if not events:
        # Every event in this feed has since ended or been unpublished — a
        # stale feed hydrating to nothing is indistinguishable from "not
        # built yet" for the caller, so keep the same empty/not-stale shape
        # rather than returning is_stale: true with an empty events list.
        return {
            "feed_date": today.isoformat(),
            "events": [],
            "built_at": None,
            "is_stale": False,
        }

    event_ids = [e.id for e in events]
    # Sponsored slot (#607): a separate card after the five, from the stored
    # pick re-gated now. The five never depend on it; its event joins the
    # five's signal batch.
    picked = None
    if settings.PROMOTIONS_SLOTS_ENABLED and not is_stale:
        slot = await resolve_feed_slot(
            db, current_user.id, now, event_ids, request.headers.get("user-agent")
        )
        if slot.swapped:
            await db.commit()
        picked = slot.result
    signal_ids = event_ids + ([picked.event.id] if picked is not None else [])
    sigs = await load_user_signals(db, current_user.id, signal_ids)
    reported = await load_user_reported_events(db, current_user.id, signal_ids)
    effective_locale = resolve_locale_param(locale, current_user.locale)

    response: dict = {
        "feed_date": feed.feed_date.isoformat(),
        "events": [
            serialize_event(
                e,
                locale=effective_locale,
                feedback_by_event=sigs,
                reported_event_ids=reported,
            )
            for e in events
        ],
        "built_at": feed.built_at.isoformat(),
        "is_stale": is_stale,
    }

    if picked is not None:
        response["sponsored_slot"] = {
            **serialize_event(
                picked.event,
                locale=effective_locale,
                feedback_by_event=sigs,
                reported_event_ids=reported,
            ),
            "advertiser": picked.promotion.advertiser_legal_name,
            "explanation": PROMOTION_EXPLANATION_DAILY5,
        }
    return response
