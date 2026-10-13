"""GET /explore — searchable, filterable, personalized event discovery grid.

Two execution paths: Path A is pure SQL for the "All events" view
sorted by date/price/quality. Path B does Python-side scoring (ranking/score.py)
whenever For-you narrowing or relevance ranking is requested, since persona
affinity and the feedback-based soft-filter aren't expressible as SQL ORDER BY.
"""

import asyncio
import time
from collections import OrderedDict
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import ColumnElement, func, literal, or_, select, true, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

from app._generated.shared_constants import (
    BROWSE_PAGE_SIZE,
    PAGINATION_MAX_OFFSET,
    DEFAULT_USER_LOCALE,
    VALID_CATEGORIES,
    VALID_VIBES,
)
from app.constants.core import TALLINN_TZ
from app.constants.ranking import (
    BROWSE_ANON_CACHE_SENTINEL,
    BROWSE_FORYOU_MIN_AFFINITY,
    BROWSE_MAX_PAGE_SIZE,
    BROWSE_NEG_INF,
    BROWSE_QUERY_MAX_LEN,
    BROWSE_RELEVANCE_MAX_CANDIDATES,
    BROWSE_SCORE_CACHE_MAX_ENTRIES,
    BROWSE_SCORE_CACHE_TTL_SECONDS,
    BROWSE_SORT_DATE,
    BROWSE_SORT_PRICE,
    BROWSE_SORT_QUALITY,
    BROWSE_SORT_RELEVANCE,
    BROWSE_SQL_SORTS,
    ERROR_INVALID_SORT,
    FEEDBACK_HISTORY_LOOKBACK_DAYS,
    PAGINATION_CURSOR_MAX_LEN,
    PAGINATION_MIN_LIMIT,
    PAGINATION_MIN_OFFSET,
    SIGNAL_DISLIKE,
    SIGNAL_LIKE,
    VALID_BROWSE_SORTS,
)
from app.constants.rate_limits import RATE_LIMIT_BROWSE
from app.db import get_db
from app.models.models import Event, EventClassification, User, UserEventFeedback, UserPersona
from app.ranking.score import (
    AffinityCache,
    FeedbackContext,
    anonymous_score_event,
    persona_affinity,
    persona_weight_tuple,
    score_event,
)
from app.rate_limit import limiter
from app.auth.dependencies import get_optional_user
from app.routers.utils import (
    decode_page_cursor,
    encode_page_cursor,
    escape_ilike_pattern,
    load_user_reported_events,
    load_user_signals,
    resolve_locale_param,
    serialize_event,
)
from app.events.queries import (
    canonical_event_filter,
    event_date_range_filter,
    event_not_ended_filter,
    public_event_filter,
    select_events_with_classification,
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
    return or_(Event.price_min == 0, Event.has_free_tier == true())


def _keyword_filter(q: str) -> ColumnElement[bool]:
    pattern = escape_ilike_pattern(q)
    return or_(
        Event.title_orig.ilike(pattern, escape="\\"),
        Event.description_orig.ilike(pattern, escape="\\"),
    )


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
    date_cond = event_date_range_filter(date_from, date_to)
    if date_cond is not None:
        conds.append(date_cond)
    return conds


async def _load_signals_and_reported(
    db: AsyncSession, user_id: int | None, event_ids: list[int]
) -> tuple[dict[int, str], set[int]]:
    """Per-user signal/report hydration for a page of events — empty for an
    anonymous caller (#234, ``user_id is None``), which has no signals or
    reports to hydrate."""
    if user_id is None:
        return {}, set()
    sigs = await load_user_signals(db, user_id, event_ids)
    reported = await load_user_reported_events(db, user_id, event_ids)
    return sigs, reported


async def _browse_sql_path(
    db: AsyncSession,
    conds: list[ColumnElement[bool]],
    sort: str,
    limit: int,
    offset: int,
    locale: str,
    user_id: int | None,
    cursor: tuple[datetime, int] | None = None,
) -> dict:
    """Path A — pure SQL. Only reachable for for_you=False with sort in
    {date, price, quality}; relevance sort always needs Python scoring.
    ``user_id`` is None for an anonymous caller (#234) — no per-user signals
    or reported-event state to hydrate.

    The ``date`` sort is keyset-paginated on ``(starts_at, id)``: ``cursor``
    (decoded from the opaque ``next_cursor`` of the previous page) replaces
    ``offset`` so page N costs the same as page 1. ``price``/``quality`` sort
    on a nullable column, so they stay on OFFSET (``cursor`` is ignored) —
    with ``id`` as a tie-breaker so the order is at least total and stable.
    """
    keyset = sort == BROWSE_SORT_DATE
    order_cols: list[ColumnElement]
    if keyset:
        order_cols = [Event.starts_at.asc(), Event.id.asc()]
    elif sort == BROWSE_SORT_PRICE:
        order_cols = [Event.price_min.asc().nulls_last(), Event.id.asc()]
    else:
        order_cols = [
            EventClassification.quality_score.desc().nulls_last(),
            Event.id.asc(),
        ]
    page_conds = list(conds)
    by_cursor = keyset and cursor is not None
    if keyset and cursor is not None:
        cursor_ts, cursor_id = cursor
        page_conds.append(
            tuple_(Event.starts_at, Event.id) > tuple_(literal(cursor_ts), literal(cursor_id))
        )
        offset = 0

    # `total` is a full-set aggregate over every matching row — expensive to
    # re-run identically for page 2, 3, 4... of the same infinite scroll, so
    # it's computed only for the first page; the frontend holds it across
    # subsequent pages via React Query. `has_more` no longer needs `total` at
    # all: fetch one extra row past `limit` and check whether it showed up.
    total: int | None = None
    if offset == 0 and not by_cursor:
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
        .where(*page_conds)
        .order_by(*order_cols)
        .limit(limit + 1)
        .offset(offset)
    )
    events = list((await db.scalars(page_stmt)).all())
    has_more = len(events) > limit
    events = events[:limit]
    event_ids = [e.id for e in events]
    sigs, reported = await _load_signals_and_reported(db, user_id, event_ids)

    return {
        "events": [
            serialize_event(
                e, locale=locale, feedback_by_event=sigs, reported_event_ids=reported
            )
            for e in events
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "next_cursor": (
            encode_page_cursor(events[-1].starts_at, events[-1].id)
            if keyset and has_more
            else None
        ),
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
    preserved indefinitely (see docs/backend-ops.md "Data Retention"), so an unbounded load
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
                selectinload(UserEventFeedback.event)
                .load_only(Event.id, Event.dedup_group_id)
                .selectinload(Event.classification)
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



# (user_id, for_you, sort, categories, vibes, free, q, date_from, date_to) ->
# (cached_at monotonic, ranked id list). See BROWSE_SCORE_CACHE_TTL_SECONDS.
_score_cache: OrderedDict[tuple, tuple[float, list[int]]] = OrderedDict()


def _score_cache_get(key: tuple) -> list[int] | None:
    entry = _score_cache.get(key)
    if entry is None:
        return None
    cached_at, ids = entry
    if time.monotonic() - cached_at > BROWSE_SCORE_CACHE_TTL_SECONDS:
        del _score_cache[key]
        return None
    _score_cache.move_to_end(key)
    return ids


def _evict_lru(od: OrderedDict, max_entries: int) -> None:
    while len(od) > max_entries:
        od.popitem(last=False)


def _score_cache_set(key: tuple, ids: list[int]) -> None:
    _score_cache[key] = (time.monotonic(), ids)
    _score_cache.move_to_end(key)
    _evict_lru(_score_cache, BROWSE_SCORE_CACHE_MAX_ENTRIES)


# Per-cache-key locks, coalescing concurrent misses on the same key (#234) —
# anonymous traffic collapses onto BROWSE_ANON_CACHE_SENTINEL, so without this
# a burst of concurrent anonymous requests for the same filter/sort combo
# would all miss the cache and recompute the same candidate scoring pass in
# parallel. Bounded and evicted in lockstep with _score_cache (same TTL/size
# regime; a lock outliving its cache entry is harmless, just wasted memory
# until it's evicted here too).
_score_cache_locks: OrderedDict[tuple, asyncio.Lock] = OrderedDict()


def _score_cache_lock(key: tuple) -> asyncio.Lock:
    lock = _score_cache_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _score_cache_locks[key] = lock
    else:
        _score_cache_locks.move_to_end(key)
    _evict_lru(_score_cache_locks, BROWSE_SCORE_CACHE_MAX_ENTRIES)
    return lock


async def _score_and_rank_candidates(
    db: AsyncSession,
    conds: list[ColumnElement[bool]],
    for_you: bool,
    sort: str,
    current_user: User | None,
    now: datetime,
) -> list[int]:
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
                Event.venue_id,
            ),
            selectinload(Event.classification),
            selectinload(Event.venue),
        )
        .where(*conds)
        .order_by(Event.starts_at.asc())
        .limit(BROWSE_RELEVANCE_MAX_CANDIDATES)
    )
    candidates = list((await db.scalars(candidate_stmt)).all())

    # Anonymous caller (#234): no persona/feedback rows to load, and the
    # locked anonymous formula drops feedback_signal entirely rather than
    # treating it as neutral — see anonymous_score_event's docstring.
    fb_ctx: FeedbackContext | None
    if current_user is not None:
        user_persona_weights = await _load_user_persona_weights(db, current_user.id)
        loaded_fb_ctx = await _load_feedback_context(db, current_user.id, now)
        fb_ctx = loaded_fb_ctx
        disliked_categories = loaded_fb_ctx.disliked_categories
    else:
        user_persona_weights = []
        fb_ctx = None
        disliked_categories = frozenset()

    # Request-scoped memo shared by score_event() and the for-you affinity
    # filter below — the persona vectors outlive the loop, so id()-keying is safe.
    affinity_cache: AffinityCache = {}
    survivors: list[tuple[float | None, Event]] = []
    for event in candidates:
        cl = event.classification
        categories = cl.categories if cl else []
        vibes = cl.vibes if cl else []
        if fb_ctx is not None:
            s = score_event(
                user_persona_weights,
                fb_ctx,
                event,
                now,
                affinity_cache=affinity_cache,
            )
        else:
            s = anonymous_score_event(event, now)

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
            affinity = persona_affinity(
                user_persona_weights, categories, vibes, cache=affinity_cache
            )
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
    return [event.id for _, event in survivors]


async def _browse_scored_path(
    db: AsyncSession,
    conds: list[ColumnElement[bool]],
    for_you: bool,
    sort: str,
    limit: int,
    offset: int,
    current_user: User | None,
    now: datetime,
    locale: str,
    cache_key: tuple | None = None,
) -> dict:
    """Path B — Python scoring. Used whenever for_you=True or sort=relevance.
    ``current_user`` is None for an anonymous caller (#234).

    The scored-and-sorted id list is cached (see BROWSE_SCORE_CACHE_TTL_SECONDS)
    so paging through /explore's infinite scroll re-scores the candidate pool
    once instead of once per page. ``cache_key=None`` (the default) skips the
    cache entirely — always re-scores. When a cache miss occurs, a per-key
    asyncio.Lock coalesces concurrent misses on the same key so only one
    caller recomputes; the rest await the lock and then read the now-populated
    cache — load-bearing for anonymous traffic, which shares one cache key
    (BROWSE_ANON_CACHE_SENTINEL) across all callers.
    """
    ranked_ids = _score_cache_get(cache_key) if cache_key is not None else None
    if ranked_ids is None:
        if cache_key is not None:
            async with _score_cache_lock(cache_key):
                # Re-check: another caller may have populated the cache while
                # this one was waiting on the lock.
                ranked_ids = _score_cache_get(cache_key)
                if ranked_ids is None:
                    ranked_ids = await _score_and_rank_candidates(
                        db, conds, for_you, sort, current_user, now
                    )
                    _score_cache_set(cache_key, ranked_ids)
        else:
            ranked_ids = await _score_and_rank_candidates(
                db, conds, for_you, sort, current_user, now
            )

    # `total` is capped at BROWSE_RELEVANCE_MAX_CANDIDATES when the candidate
    # pool hit the cap — an accepted Path-B approximation.
    total = len(ranked_ids)
    page_ids = ranked_ids[offset : offset + limit]

    events_by_id: dict[int, Event] = {}
    if page_ids:
        # public_event_filter() re-applied here, not just in the scoring query
        # above — the scored id list is cached for BROWSE_SCORE_CACHE_TTL_SECONDS,
        # so without this an id that went non-public in the meantime (e.g. a
        # takedown) would keep hydrating for every caller sharing that cache
        # entry until it expires (OWASP audit G-3). ordered_events' `if eid in
        # events_by_id` guard below already handles an id silently dropping out.
        full_rows = (
            await db.scalars(
                select_events_with_classification().where(
                    Event.id.in_(page_ids), public_event_filter()
                )
            )
        ).all()
        events_by_id = {e.id: e for e in full_rows}

    ordered_events = [events_by_id[eid] for eid in page_ids if eid in events_by_id]
    user_id = current_user.id if current_user is not None else None
    sigs, reported = await _load_signals_and_reported(db, user_id, page_ids)

    return {
        "events": [
            serialize_event(
                e, locale=locale, feedback_by_event=sigs, reported_event_ids=reported
            )
            for e in ordered_events
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(page_ids) < total,
    }


@router.get("/explore")
@limiter.limit(RATE_LIMIT_BROWSE)
async def explore_events(
    request: Request,
    q: str | None = Query(None, max_length=BROWSE_QUERY_MAX_LEN),
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
    cursor: str | None = Query(None, max_length=PAGINATION_CURSOR_MAX_LEN),
    locale: str | None = Query(None),
    current_user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Browse/search all upcoming published events, personalized when for_you=True.

    Anonymous callers (no/invalid session, current_user is None) get the same
    result set as signed-in callers, scored via the persona-free formula in
    anonymous_score_event() (#234) instead of a 401.
    """
    if sort not in VALID_BROWSE_SORTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_INVALID_SORT.format(sorts=sorted(VALID_BROWSE_SORTS)),
        )

    categories = _parse_slug_list(category, VALID_CATEGORIES)
    vibes = _parse_slug_list(vibe, VALID_VIBES)
    now = datetime.now(TALLINN_TZ)
    conds = _facet_conditions(categories, vibes, free, q, date_from, date_to, now)
    user_locale = current_user.locale if current_user is not None else DEFAULT_USER_LOCALE
    effective_locale = resolve_locale_param(locale, user_locale)

    if not for_you and sort in BROWSE_SQL_SORTS:
        user_id = current_user.id if current_user is not None else None
        return await _browse_sql_path(
            db,
            conds,
            sort,
            limit,
            offset,
            effective_locale,
            user_id,
            decode_page_cursor(cursor) if cursor else None,
        )

    cache_key = (
        current_user.id if current_user is not None else BROWSE_ANON_CACHE_SENTINEL,
        for_you,
        sort,
        tuple(sorted(categories)),
        tuple(sorted(vibes)),
        free,
        q,
        date_from,
        date_to,
    )
    return await _browse_scored_path(
        db,
        conds,
        for_you,
        sort,
        limit,
        offset,
        current_user,
        now,
        effective_locale,
        cache_key,
    )
