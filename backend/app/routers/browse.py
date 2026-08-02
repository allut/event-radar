"""GET /explore — searchable, filterable, personalized event discovery grid.

Two execution paths: Path A is pure SQL for the "All events" view
sorted by date/price/quality. Path B does Python-side scoring (ranking/score.py)
whenever For-you narrowing or relevance ranking is requested, since persona
affinity and the feedback-based soft-filter aren't expressible as SQL ORDER BY.
"""

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

from app.constants import (
    BROWSE_FORYOU_MIN_AFFINITY,
    BROWSE_MAX_PAGE_SIZE,
    BROWSE_NEG_INF,
    BROWSE_PAGE_SIZE,
    BROWSE_RELEVANCE_MAX_CANDIDATES,
    BROWSE_SORT_DATE,
    BROWSE_SORT_PRICE,
    BROWSE_SORT_QUALITY,
    BROWSE_SORT_RELEVANCE,
    BROWSE_SQL_SORTS,
    FEEDBACK_HISTORY_LOOKBACK_DAYS,
    PAGINATION_MAX_OFFSET,
    PAGINATION_MIN_LIMIT,
    PAGINATION_MIN_OFFSET,
    RATE_LIMIT_BROWSE,
    SIGNAL_DISLIKE,
    SIGNAL_LIKE,
    TALLINN_TZ,
    VALID_BROWSE_SORTS,
    VALID_CATEGORIES,
    VALID_VIBES,
)
from app.db import get_db
from app.models.models import Event, EventClassification, User, UserEventFeedback, UserPersona
from app.ranking.score import FeedbackContext, persona_affinity, score_event
from app.rate_limit import limiter
from app.routers.auth import get_current_user
from app.routers.utils import (
    canonical_event_filter,
    event_not_ended_filter,
    load_user_signals,
    persona_weight_tuple,
    public_event_filter,
    resolve_locale_param,
    select_events_with_classification,
    serialize_event,
)

router = APIRouter(tags=["browse"])


def _parse_slug_list(raw: str | None, valid: frozenset[str]) -> list[str]:
    """Comma-split, dedupe, silently drop anything outside `valid` — mirrors the
    taxonomy-filtering convention in llm/classifier.py::_parse_classification."""
    if not raw:
        return []
    seen: list[str] = []
    for slug in raw.split(","):
        slug = slug.strip()
        if slug and slug in valid and slug not in seen:
            seen.append(slug)
    return seen


def _free_filter() -> ColumnElement[bool]:
    return or_(Event.price_min == 0, Event.has_free_tier.is_(True))


def _keyword_filter(q: str) -> ColumnElement[bool]:
    """Escape SQL LIKE wildcards in user input before building the pattern —
    otherwise a literal '%' or '_' in the search box would wildcard-match."""
    escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    return or_(
        Event.title_orig.ilike(pattern, escape="\\"),
        Event.description_orig.ilike(pattern, escape="\\"),
    )


def _date_range_filter(
    date_from: date | None, date_to: date | None
) -> ColumnElement[bool] | None:
    """Overlap check, not starts_at-only: an ongoing exhibition that started
    last month must still match a "Today" filter. Bounds are Tallinn-midnight
    datetimes; date_to is exclusive (next-day midnight)."""
    if date_from is None and date_to is None:
        return None
    conditions: list[ColumnElement[bool]] = []
    if date_to is not None:
        date_to_end = datetime.combine(
            date_to + timedelta(days=1), datetime.min.time(), tzinfo=TALLINN_TZ
        )
        conditions.append(Event.starts_at < date_to_end)
    if date_from is not None:
        date_from_start = datetime.combine(
            date_from, datetime.min.time(), tzinfo=TALLINN_TZ
        )
        conditions.append(func.coalesce(Event.ends_at, Event.starts_at) >= date_from_start)
    return and_(*conditions)


def _facet_conditions(
    categories: list[str],
    vibes: list[str],
    free: bool,
    q: str | None,
    date_from: date | None,
    date_to: date | None,
    now: datetime,
) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = [
        public_event_filter(),
        event_not_ended_filter(now),
        canonical_event_filter(),
    ]
    if categories:
        conds.append(EventClassification.categories.overlap(categories))
    if vibes:
        conds.append(EventClassification.vibes.overlap(vibes))
    if free:
        conds.append(_free_filter())
    if q:
        conds.append(_keyword_filter(q))
    date_cond = _date_range_filter(date_from, date_to)
    if date_cond is not None:
        conds.append(date_cond)
    return conds


async def _browse_sql_path(
    db: AsyncSession,
    conds: list[ColumnElement[bool]],
    sort: str,
    limit: int,
    offset: int,
    locale: str,
    user_id: int,
) -> dict:
    """Path A — pure SQL. Only reachable for for_you=False with sort in
    {date, price, quality}; relevance sort always needs Python scoring."""
    order_col: ColumnElement
    if sort == BROWSE_SORT_DATE:
        order_col = Event.starts_at.asc()
    elif sort == BROWSE_SORT_PRICE:
        order_col = Event.price_min.asc().nulls_last()
    else:
        order_col = EventClassification.quality_score.desc().nulls_last()

    total = (
        await db.scalar(
            select(func.count(Event.id))
            .select_from(Event)
            .join(Event.classification)
            .where(*conds)
        )
    ) or 0

    page_stmt = (
        select_events_with_classification()
        .join(Event.classification)
        .where(*conds)
        .order_by(order_col)
        .limit(limit)
        .offset(offset)
    )
    events = list((await db.scalars(page_stmt)).all())
    sigs = await load_user_signals(db, user_id, [e.id for e in events])

    return {
        "events": [
            serialize_event(e, locale=locale, feedback_by_event=sigs) for e in events
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(events) < total,
    }


async def _load_user_persona_weights(
    db: AsyncSession, user_id: int
) -> list[tuple[float, dict]]:
    rows = (
        await db.scalars(
            select(UserPersona)
            .where(UserPersona.user_id == user_id)
            .options(selectinload(UserPersona.persona))
        )
    ).all()
    return [persona_weight_tuple(row) for row in rows]


async def _load_feedback_context(
    db: AsyncSession, user_id: int, now: datetime
) -> FeedbackContext:
    """Bounded to the last FEEDBACK_HISTORY_LOOKBACK_DAYS — user_event_feedback is
    preserved indefinitely (see CLAUDE.md Data Retention), so an unbounded load
    here grows with the user's lifetime activity on every /explore request.
    FEEDBACK_DECAY_BASE's per-day decay makes older signals numerically
    negligible to score_event() anyway, so this drops no meaningfully-weighted
    signal."""
    cutoff = now - timedelta(days=FEEDBACK_HISTORY_LOOKBACK_DAYS)
    rows = (
        await db.scalars(
            select(UserEventFeedback)
            .where(
                UserEventFeedback.user_id == user_id,
                UserEventFeedback.signal.in_((SIGNAL_LIKE, SIGNAL_DISLIKE)),
                UserEventFeedback.created_at >= cutoff,
            )
            .options(
                selectinload(UserEventFeedback.event).selectinload(
                    Event.classification
                )
            )
        )
    ).all()
    return FeedbackContext.from_orm_rows(list(rows))


def _sort_key_and_reverse(
    sort: str,
) -> tuple[Callable[[tuple[float | None, Event]], Any], bool]:
    if sort == BROWSE_SORT_DATE:
        return (lambda item: item[1].starts_at), False
    if sort == BROWSE_SORT_PRICE:
        return (
            lambda item: (
                item[1].price_min is None,
                item[1].price_min if item[1].price_min is not None else 0.0,
            )
        ), False
    if sort == BROWSE_SORT_QUALITY:

        def _quality_key(item: tuple[float | None, Event]) -> float:
            cl = item[1].classification
            return cl.quality_score if cl and cl.quality_score is not None else BROWSE_NEG_INF

        return _quality_key, True

    def _relevance_key(item: tuple[float | None, Event]) -> float:
        return item[0] if item[0] is not None else BROWSE_NEG_INF

    return _relevance_key, True


async def _browse_scored_path(
    db: AsyncSession,
    conds: list[ColumnElement[bool]],
    for_you: bool,
    sort: str,
    limit: int,
    offset: int,
    current_user: User,
    now: datetime,
    locale: str,
) -> dict:
    """Path B — Python scoring. Used whenever for_you=True or sort=relevance."""
    candidate_stmt = (
        select(Event)
        .join(Event.classification)
        .options(
            load_only(
                Event.id,
                Event.starts_at,
                Event.ends_at,
                Event.price_min,
                Event.lat,
                Event.lng,
                Event.dedup_group_id,
            ),
            selectinload(Event.classification),
        )
        .where(*conds)
        .order_by(Event.starts_at.asc())
        .limit(BROWSE_RELEVANCE_MAX_CANDIDATES)
    )
    candidates = list((await db.scalars(candidate_stmt)).all())

    user_persona_weights = await _load_user_persona_weights(db, current_user.id)
    fb_ctx = await _load_feedback_context(db, current_user.id, now)

    disliked_categories = fb_ctx.disliked_categories

    survivors: list[tuple[float | None, Event]] = []
    for event in candidates:
        cl = event.classification
        categories = cl.categories if cl else []
        vibes = cl.vibes if cl else []
        s = score_event(user_persona_weights, fb_ctx, event, now)

        if for_you:
            # Hard excludes (dislike / disliked dedup group) and the soft
            # filters (disliked category, below-affinity) all hide the event.
            if s is None:
                continue
            if categories and disliked_categories.intersection(categories):
                continue
            # Deliberately time-blind (no time_slots, unlike score_event() below):
            # the soft filter gates on content match (category/vibe) only, so an
            # event isn't hidden from For-you just because it falls outside the
            # user's usual time-of-day/day-of-week pattern — score_event() still
            # weighs that signal for *ranking* the survivors.
            affinity = persona_affinity(user_persona_weights, categories, vibes)
            if affinity < BROWSE_FORYOU_MIN_AFFINITY:
                continue
            survivors.append((s, event))
        else:
            # All-events relevance: keep hard-excluded events too, ranked last
            # (score_event returns None for them; the sort key maps that to
            # -inf). "All events" must show everything.
            survivors.append((s, event))

    key_func, reverse = _sort_key_and_reverse(sort)
    survivors.sort(key=key_func, reverse=reverse)

    # `total` is capped at BROWSE_RELEVANCE_MAX_CANDIDATES when the candidate
    # pool hit the cap — an accepted Path-B approximation.
    total = len(survivors)
    page = survivors[offset : offset + limit]
    page_ids = [event.id for _, event in page]

    events_by_id: dict[int, Event] = {}
    if page_ids:
        full_rows = (
            await db.scalars(
                select_events_with_classification().where(Event.id.in_(page_ids))
            )
        ).all()
        events_by_id = {e.id: e for e in full_rows}

    ordered_events = [events_by_id[eid] for eid in page_ids if eid in events_by_id]
    sigs = await load_user_signals(db, current_user.id, page_ids)

    return {
        "events": [
            serialize_event(e, locale=locale, feedback_by_event=sigs)
            for e in ordered_events
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(page) < total,
    }


@router.get("/explore")
@limiter.limit(RATE_LIMIT_BROWSE)
async def explore_events(
    request: Request,
    q: str | None = None,
    category: str | None = None,
    vibe: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    free: bool = False,
    for_you: bool = True,
    sort: str = BROWSE_SORT_RELEVANCE,
    limit: int = Query(BROWSE_PAGE_SIZE, ge=PAGINATION_MIN_LIMIT, le=BROWSE_MAX_PAGE_SIZE),
    offset: int = Query(
        PAGINATION_MIN_OFFSET, ge=PAGINATION_MIN_OFFSET, le=PAGINATION_MAX_OFFSET
    ),
    locale: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Browse/search all upcoming published events, personalized when for_you=True."""
    if sort not in VALID_BROWSE_SORTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"sort must be one of {sorted(VALID_BROWSE_SORTS)}",
        )

    categories = _parse_slug_list(category, VALID_CATEGORIES)
    vibes = _parse_slug_list(vibe, VALID_VIBES)
    now = datetime.now(TALLINN_TZ)
    conds = _facet_conditions(categories, vibes, free, q, date_from, date_to, now)
    effective_locale = resolve_locale_param(locale, current_user.locale)

    if not for_you and sort in BROWSE_SQL_SORTS:
        return await _browse_sql_path(
            db, conds, sort, limit, offset, effective_locale, current_user.id
        )

    return await _browse_scored_path(
        db, conds, for_you, sort, limit, offset, current_user, now, effective_locale
    )
