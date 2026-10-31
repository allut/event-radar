"""GET /explore — searchable, filterable, personalized event discovery grid.

Two execution paths: Path A is pure SQL for the "All events" view
sorted by date/price/quality. Path B does Python-side scoring (ranking/score.py)
whenever For-you narrowing or relevance ranking is requested, since persona
affinity and the feedback-based soft-filter aren't expressible as SQL ORDER BY.
"""

import asyncio
import logging
import time
from array import array
from collections import OrderedDict
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

from app._generated.shared_constants import (
    BROWSE_PAGE_SIZE,
    BROWSE_QUERY_MAX_LEN,
    DEFAULT_USER_LOCALE,
    PAGINATION_MAX_OFFSET,
    VALID_CATEGORIES,
    VALID_VIBES,
)
from app.constants.ranking import (
    BROWSE_ANON_CACHE_SENTINEL,
    BROWSE_FORYOU_MIN_AFFINITY,
    BROWSE_MAX_PAGE_SIZE,
    BROWSE_NEG_INF,
    BROWSE_RELEVANCE_CEILING,
    BROWSE_SCORE_CACHE_ID_TYPECODE,
    BROWSE_SCORE_CACHE_MAX_ENTRIES,
    BROWSE_SCORE_CACHE_TTL_SECONDS,
    BROWSE_SORT_DATE,
    BROWSE_SORT_PRICE,
    BROWSE_SORT_QUALITY,
    BROWSE_SORT_RELEVANCE,
    BROWSE_SQL_SORTS,
    ERROR_INVALID_SORT,
    FEEDBACK_HISTORY_LOOKBACK_DAYS,
    PAGINATION_MIN_LIMIT,
    PAGINATION_MIN_OFFSET,
    SIGNAL_DISLIKE,
    SIGNAL_LIKE,
    VALID_BROWSE_SORTS,
)
from app.constants.log_events import LOG_EVENT_EXPLORE_CEILING_OVERFLOW
from app.constants.promotions import (
    PROMOTION_EXPLANATION_FILTERS,
    PROMOTION_EXPLANATION_NONE,
    PROMOTION_EXPLORE_MIN_ORGANIC,
    PROMOTION_EXPLORE_SLOT_TILE,
    PROMOTION_STAT_EXPLORE_SERVED,
)
from app.constants.rate_limits import RATE_LIMIT_BROWSE
from app.db import get_db
from app.models.events import Event, EventClassification
from app.models.feeds import UserEventFeedback
from app.models.users import User, UserPersona
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
    load_user_reported_events,
    load_user_signals,
    resolve_locale_param,
    serialize_event,
)
from app.promotions.counters import bump
from app.promotions.fill import (
    GateResult,
    explore_eligible,
    explore_seed,
    gate_closed_reason,
    load_visible,
    rotation_pick,
    surviving,
    without_viewer_excluded,
)
from app.promotions.windows import now_tallinn, tallinn_today
from app.events.queries import (
    facet_conditions,
    public_event_filter,
    select_events_with_classification,
)

logger = logging.getLogger(__name__)

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


def _sql_order_cols(sort: str) -> list[ColumnElement]:
    if sort == BROWSE_SORT_DATE:
        return [Event.starts_at.asc(), Event.id.asc()]
    if sort == BROWSE_SORT_PRICE:
        return [Event.price_min.asc().nulls_last(), Event.id.asc()]
    return [EventClassification.quality_score.desc().nulls_last(), Event.id.asc()]


async def _browse_sql_path(
    db: AsyncSession,
    conds: list[ColumnElement[bool]],
    sort: str,
    limit: int,
    offset: int,
    locale: str,
    user_id: int | None,
) -> dict:
    """Path A — pure SQL. Only reachable for for_you=False with sort in
    {date, price, quality}; relevance sort always needs Python scoring.
    ``user_id`` is None for an anonymous caller (#234) — no per-user signals
    or reported-event state to hydrate.

    Every sort pages on OFFSET with an exact ``total`` on every page, which
    the numbered pager needs for its range label and last page (spec #551).
    Each order ends in ``id`` as a tie-breaker, so rows sharing a sort value
    keep one stable order across pages.
    """
    order_cols = _sql_order_cols(sort)

    total = (
        await db.scalar(
            select(func.count(Event.id))
            .select_from(Event)
            .join(Event.classification)
            .where(*conds)
        )
    ) or 0

    # `has_more` comes from one extra row past `limit`, not from `total`.
    page_stmt = (
        select_events_with_classification()
        .join(Event.classification)
        .where(*conds)
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
# (cached_at monotonic, ranked ids, total_is_lower_bound). The ids are an
# array("q") at 8 bytes each (Event.id is a BigInteger). See
# BROWSE_SCORE_CACHE_TTL_SECONDS.
_RankedIds = tuple[array, bool]
_score_cache: OrderedDict[tuple, tuple[float, array, bool]] = OrderedDict()


def _score_cache_get(key: tuple) -> _RankedIds | None:
    entry = _score_cache.get(key)
    if entry is None:
        return None
    cached_at, ids, lower_bound = entry
    if time.monotonic() - cached_at > BROWSE_SCORE_CACHE_TTL_SECONDS:
        del _score_cache[key]
        return None
    _score_cache.move_to_end(key)
    return ids, lower_bound


def _evict_lru(od: OrderedDict, max_entries: int) -> None:
    while len(od) > max_entries:
        od.popitem(last=False)


def _score_cache_set(key: tuple, ids: array, lower_bound: bool) -> None:
    _score_cache[key] = (time.monotonic(), ids, lower_bound)
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
) -> _RankedIds:
    """Score and sort the candidate pool; return its ids and the lower-bound flag.

    The query fetches BROWSE_RELEVANCE_CEILING + 1 rows soonest-first. One extra
    row means the pool overflowed: only the soonest ceiling are scored and the
    flag is set, even when the filters below then leave fewer.
    """
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
        .order_by(Event.starts_at.asc(), Event.id.asc())
        .limit(BROWSE_RELEVANCE_CEILING + 1)
    )
    candidates = list((await db.scalars(candidate_stmt)).all())
    lower_bound = len(candidates) > BROWSE_RELEVANCE_CEILING
    if lower_bound:
        candidates = candidates[:BROWSE_RELEVANCE_CEILING]
        logger.warning(
            "explore candidate pool exceeded the ceiling; ranking the soonest %d",
            BROWSE_RELEVANCE_CEILING,
            extra={
                "event": LOG_EVENT_EXPLORE_CEILING_OVERFLOW,
                "ceiling": BROWSE_RELEVANCE_CEILING,
            },
        )

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
    ids = array(BROWSE_SCORE_CACHE_ID_TYPECODE, (event.id for _, event in survivors))
    return ids, lower_bound


async def _ranked_candidates(
    db: AsyncSession,
    conds: list[ColumnElement[bool]],
    for_you: bool,
    sort: str,
    current_user: User | None,
    now: datetime,
    cache_key: tuple | None,
) -> _RankedIds:
    ranked = _score_cache_get(cache_key) if cache_key is not None else None
    if ranked is None:
        if cache_key is not None:
            async with _score_cache_lock(cache_key):
                # Re-check: another caller may have populated the cache while
                # this one was waiting on the lock.
                ranked = _score_cache_get(cache_key)
                if ranked is None:
                    ranked = await _score_and_rank_candidates(
                        db, conds, for_you, sort, current_user, now
                    )
                    _score_cache_set(cache_key, *ranked)
        else:
            ranked = await _score_and_rank_candidates(
                db, conds, for_you, sort, current_user, now
            )
    return ranked


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
    so paging through /explore's numbered pager re-scores the candidate pool
    once instead of once per page. ``cache_key=None`` (the default) skips the
    cache entirely — always re-scores. When a cache miss occurs, a per-key
    asyncio.Lock coalesces concurrent misses on the same key so only one
    caller recomputes; the rest await the lock and then read the now-populated
    cache — load-bearing for anonymous traffic, which shares one cache key
    (BROWSE_ANON_CACHE_SENTINEL) across all callers.
    """
    ranked = await _ranked_candidates(
        db, conds, for_you, sort, current_user, now, cache_key
    )
    ranked_ids, lower_bound = ranked

    # `total` is the reachable count: the whole matching set below
    # BROWSE_RELEVANCE_CEILING, the ranked soonest pool when `lower_bound` is set.
    total = len(ranked_ids)
    page_ids = list(ranked_ids[offset : offset + limit])

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

    response: dict = {
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
    if lower_bound:
        response["total_is_lower_bound"] = True
    return response


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
    locale: str | None = Query(None),
    sponsored_slot: bool = Query(False),
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
    now = now_tallinn()
    conds = facet_conditions(categories, vibes, free, q, date_from, date_to, now)
    user_locale = current_user.locale if current_user is not None else DEFAULT_USER_LOCALE
    effective_locale = resolve_locale_param(locale, user_locale)

    user_id = current_user.id if current_user is not None else None
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

    async def serve(page_limit: int, page_offset: int) -> dict:
        if not for_you and sort in BROWSE_SQL_SORTS:
            return await _browse_sql_path(
                db, conds, sort, page_limit, page_offset, effective_locale, user_id
            )
        return await _browse_scored_path(
            db,
            conds,
            for_you,
            sort,
            page_limit,
            page_offset,
            current_user,
            now,
            effective_locale,
            cache_key,
        )

    if not sponsored_slot:
        return await serve(limit, offset)
    if gate_closed_reason(request.headers.get("user-agent")):
        response = await serve(limit, offset)
        response["page1_has_slot"] = False
        return response

    # Sponsored slot (#603). Organic ranking is untouched: the slot only moves
    # the page window by one, and only when a Promotion is eligible.
    eligible = await explore_eligible(db, now, conds)
    survivors: list[GateResult] = []
    if eligible:
        page_one_ids = await _page_one_ids(
            db, conds, for_you, sort, limit, current_user, now, cache_key
        )
        if min(len(page_one_ids), limit - 1) >= PROMOTION_EXPLORE_MIN_ORGANIC:
            visible = await load_visible(db, page_one_ids)
            survivors = await without_viewer_excluded(
                db, user_id, surviving(eligible, visible)
            )
    if not survivors:
        response = await serve(limit, offset)
        response["page1_has_slot"] = False
        return response

    # Page 1 gives up its last organic row to the slot; every later page starts
    # one result earlier so nothing is skipped or repeated.
    if offset == 0:
        response = await serve(limit - 1, 0)
        response["limit"] = limit
        picked = rotation_pick(survivors, explore_seed(user_id, tallinn_today(now)))
        bump(picked.promotion.id, tallinn_today(now), PROMOTION_STAT_EXPLORE_SERVED)
        sigs, reported = await _load_signals_and_reported(db, user_id, [picked.event.id])
        response["sponsored_slot"] = {
            **serialize_event(
                picked.event,
                locale=effective_locale,
                feedback_by_event=sigs,
                reported_event_ids=reported,
            ),
            "advertiser": picked.promotion.advertiser_legal_name,
            "explanation": (
                PROMOTION_EXPLANATION_FILTERS
                if (categories or vibes or free or q or date_from or date_to)
                else PROMOTION_EXPLANATION_NONE
            ),
            "tile": PROMOTION_EXPLORE_SLOT_TILE,
        }
    else:
        response = await serve(limit, offset - 1)
        response["offset"] = offset
    response["page1_has_slot"] = True
    return response


async def _page_one_ids(
    db: AsyncSession,
    conds: list[ColumnElement[bool]],
    for_you: bool,
    sort: str,
    limit: int,
    current_user: User | None,
    now: datetime,
    cache_key: tuple | None,
) -> list[int]:
    """The first ``limit`` organic ids, in the order page 1 would show them."""
    if not for_you and sort in BROWSE_SQL_SORTS:
        stmt = (
            select(Event.id)
            .join(Event.classification)
            .where(*conds)
            .order_by(*_sql_order_cols(sort))
            .limit(limit)
        )
        return list((await db.scalars(stmt)).all())
    ranked_ids, _ = await _ranked_candidates(
        db, conds, for_you, sort, current_user, now, cache_key
    )
    return list(ranked_ids[:limit])
