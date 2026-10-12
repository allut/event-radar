"""GET /public/showcase, GET /public/counts — unauthenticated landing-page data.

Showcase: a small, fixed-size grid of top-quality published events happening
this week. Counts: the live numbers (upcoming/venues/furthest-date/cheapest
ticket/tonight) Landing's hero, ticker and flat proof section render. No auth,
no personalization, no PII — mirrors the pure-SQL quality sort in
browse.py::_browse_sql_path, minus every user/feedback/persona concern, plus a
symmetric date window (see _showcase_stmt).
"""

import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import Select, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app._generated.shared_constants import DEFAULT_USER_LOCALE, VALID_LOCALES
from app.constants.core import TALLINN_TZ
from app.constants.events import (
    PUBLIC_COUNTS_CACHE_TTL_SECONDS,
    PUBLIC_COUNTS_FALLBACK_WINDOW_DAYS,
    PUBLIC_COUNTS_TONIGHT_CAP,
    SHOWCASE_EVENT_COUNT,
    SHOWCASE_FALLBACK_WINDOW_DAYS,
    SHOWCASE_WINDOW_DAYS,
)
from app.constants.rate_limits import RATE_LIMIT_PUBLIC
from app.db import get_db
from app.models.models import Event, EventClassification, Venue
from app.rate_limit import limiter
from app.routers.utils import resolve_locale_param, serialize_event
from app.events.queries import (
    canonical_event_filter,
    collapse_series_duplicates,
    event_date_range_filter,
    event_not_ended_filter,
    public_event_filter,
    select_events_with_classification,
)
from app.events.localize import resolve_title
from app.events.venue import resolve_venue_name

router = APIRouter(prefix="/public", tags=["public"])


def _showcase_stmt(now: datetime) -> Select[tuple[Event]]:
    """Top-quality events within SHOWCASE_FALLBACK_WINDOW_DAYS, preferring ones
    within the narrower SHOWCASE_WINDOW_DAYS ("this week") — a single query
    replacing the old narrow-then-fallback two-query shape (the narrow result
    is always a subset of this wider one: same filters, same tie-break order,
    just a looser date bound).

    Bounded on both sides so a long-lived listing (e.g. a museum's year-round
    entry ticket, valid for months) can't permanently occupy the grid just
    because it hasn't ended yet. ``in_narrow_window`` sorts first so a "this
    week" event is always preferred over a wider-window one regardless of
    quality_score, only spilling into the wider window when the narrow week
    doesn't have enough candidates to fill SHOWCASE_EVENT_COUNT — identical
    precedence to the old fallback-only-when-thin behavior, in one query.

    Deliberately unlimited: the caller (``showcase``) collapses same-series
    duplicates (``collapse_series_duplicates``) before slicing to
    SHOWCASE_EVENT_COUNT, so a SQL-level LIMIT here could discard a series'
    only surviving instance before the collapse ever saw it. Still bounded by
    the fallback window and public_event_filter() — the same shape of
    unbounded-but-window-bounded load ``_load_candidate_events`` already does
    for the Daily 5 builder.
    """
    in_narrow_window = (Event.starts_at >= now - timedelta(days=SHOWCASE_WINDOW_DAYS)) & (
        Event.starts_at < now + timedelta(days=SHOWCASE_WINDOW_DAYS)
    )
    return (
        select_events_with_classification()
        .join(Event.classification)
        .where(
            public_event_filter(),
            event_not_ended_filter(now),
            canonical_event_filter(),
            Event.starts_at < now + timedelta(days=SHOWCASE_FALLBACK_WINDOW_DAYS),
            Event.starts_at >= now - timedelta(days=SHOWCASE_FALLBACK_WINDOW_DAYS),
        )
        .order_by(
            case((in_narrow_window, 0), else_=1),
            EventClassification.quality_score.desc().nulls_last(),
            Event.starts_at.asc(),
        )
    )


# Process-local TTL cache — same shape as _counts_cache below, keyed by locale
# since the payload is locale-sensitive (event titles/venue names). This is the
# anonymous landing page, the highest-traffic unauthenticated endpoint, so a
# per-request 60-day hydrate+sort is not warranted for a grid that only
# meaningfully changes a few times a day (see docstring below).
_showcase_cache: dict[str, tuple[float, dict]] = {}


async def _load_showcase(db: AsyncSession, now: datetime) -> dict[str, dict]:
    """One window query + collapse + sort, serialized for every locale — the
    ranking is locale-independent, so loading per locale would repeat the
    same 60-day hydrate once per cold cache entry."""
    events = list((await db.scalars(_showcase_stmt(now))).all())
    collapsed, _ = collapse_series_duplicates(events)

    narrow_start = now - timedelta(days=SHOWCASE_WINDOW_DAYS)
    narrow_end = now + timedelta(days=SHOWCASE_WINDOW_DAYS)

    def _sort_key(event: Event) -> tuple[int, bool, float, datetime]:
        in_narrow_window = narrow_start <= event.starts_at < narrow_end
        quality_score = (
            event.classification.quality_score if event.classification else None
        )
        return (
            0 if in_narrow_window else 1,
            quality_score is None,
            -(quality_score or 0),
            event.starts_at,
        )

    collapsed.sort(key=_sort_key)
    events = collapsed[:SHOWCASE_EVENT_COUNT]
    return {
        loc: {"events": [serialize_event(e, locale=loc) for e in events]}
        for loc in VALID_LOCALES
    }


@router.get("/showcase")
@limiter.limit(RATE_LIMIT_PUBLIC)
async def showcase(
    request: Request,
    locale: str = Query(DEFAULT_USER_LOCALE),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Top-quality events happening this week, for the public landing page.

    No auth: anonymous visitors must be able to see real events before signing
    up. serialize_event is called without feedback signals (no user context).
    A thin week (fewer than SHOWCASE_EVENT_COUNT candidates) spills into a wider
    window — one query orders "this week" candidates first, so widening only
    changes results when the narrow week can't fill the grid on its own (see
    _showcase_stmt).

    Collapses same-series duplicates (collapse_series_duplicates) before
    slicing to SHOWCASE_EVENT_COUNT — a recurring multi-day listing (e.g. a
    Tue/Thu/Sat workshop) is never dedup-grouped across days, so each
    date-instance is its own canonical row and could otherwise independently
    qualify for the grid (docs/pipeline.md "Landing Showcase"). The collapse's surviving
    representative per series isn't guaranteed to be the one _showcase_stmt's
    SQL ORDER BY would have picked first, so the post-collapse order is
    recomputed in Python with the same three keys (narrow-window first,
    quality_score desc/nulls-last, starts_at asc) before the slice.

    Cached in-process for PUBLIC_COUNTS_CACHE_TTL_SECONDS, same TTL and pattern
    as /public/counts right below — this is the anonymous landing page, so an
    uncached full-window hydrate+sort per pageview isn't warranted (see H1 in
    the Big-O audit).
    """
    locale = resolve_locale_param(locale, DEFAULT_USER_LOCALE)

    cached = _showcase_cache.get(locale)
    now_monotonic = time.monotonic()
    if cached is not None and now_monotonic - cached[0] < PUBLIC_COUNTS_CACHE_TTL_SECONDS:
        return cached[1]

    now = datetime.now(TALLINN_TZ)
    payloads = await _load_showcase(db, now)
    for loc, loc_payload in payloads.items():
        _showcase_cache[loc] = (now_monotonic, loc_payload)
    return payloads[locale]


# Process-local TTL cache — single dict entry, keyed by locale, since the payload
# is locale-sensitive (event titles/venue names). No new dependency: the app is
# single-process/no-Redis (see CLAUDE.md "Architecture"), so a module-level dict is
# sufficient and matches the pattern of every other in-process cache here.
_counts_cache: dict[str, tuple[float, dict]] = {}


def _tonight_stmt(now: datetime) -> Select[tuple[Event]]:
    """Published events starting today (Europe/Tallinn), earliest first. Bounded
    by PUBLIC_COUNTS_TONIGHT_CAP — the ticker/hero panel are teasers, not a full
    listing."""
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    return (
        select_events_with_classification()
        .where(
            public_event_filter(),
            canonical_event_filter(),
            Event.starts_at >= today_start,
            Event.starts_at < today_end,
        )
        .order_by(Event.starts_at.asc())
        .limit(PUBLIC_COUNTS_TONIGHT_CAP)
    )


def _tonight_fallback_stmt(now: datetime) -> Select[tuple[Event]]:
    """A real empty-tonight is a valid, non-error state (Landing copy,
    docs/design-system.md §11) — this widens to the next PUBLIC_COUNTS_FALLBACK_WINDOW_DAYS
    days rather than rendering an empty ticker."""
    return (
        select_events_with_classification()
        .where(
            public_event_filter(),
            event_not_ended_filter(now),
            canonical_event_filter(),
            Event.starts_at >= now,
            Event.starts_at < now + timedelta(days=PUBLIC_COUNTS_FALLBACK_WINDOW_DAYS),
        )
        .order_by(Event.starts_at.asc())
        .limit(PUBLIC_COUNTS_TONIGHT_CAP)
    )


def _today_count_stmt(now: datetime) -> Select[tuple[int]]:
    """Exact count of what ``/explore?date=today`` lists: the Explore base
    filters plus the shared overlap predicate, so ongoing exhibitions count.
    A separate scalar rather than a FILTER on ``_aggregates_stmt`` — that
    statement's ``starts_at >= now`` WHERE would drop exactly those runs."""
    today = now.astimezone(TALLINN_TZ).date()
    overlaps_today = event_date_range_filter(today, today)
    assert overlaps_today is not None  # both bounds given
    return select(func.count(Event.id)).where(
        public_event_filter(),
        canonical_event_filter(),
        event_not_ended_filter(now),
        overlaps_today,
    )


def _aggregates_stmt(
    now: datetime,
) -> Select[tuple[int, int, datetime, float | None]]:
    """Single-row aggregate query: upcoming count, distinct venue count, furthest
    booked date, cheapest paid ticket. One query, no per-row loop — bulk
    aggregates, not a scan hydrated into Python.

    Distinct-venue count is coalesced over the linked Venue's name so a
    venue-linked event (whose own venue_name is left NULL, #176) isn't
    silently dropped from the count — see resolve_venue_name()."""
    venue_name = func.coalesce(Venue.name, Event.venue_name)
    return (
        select(
            func.count(Event.id).label("upcoming_count"),
            func.count(func.distinct(venue_name)).label("venue_count"),
            func.max(Event.starts_at).label("furthest_date"),
            func.min(Event.price_min)
            .filter(Event.price_min > 0)
            .label("cheapest_price"),
        )
        .select_from(Event)
        .outerjoin(Event.venue)
        .where(public_event_filter(), Event.starts_at >= now)
    )


async def _load_counts(db: AsyncSession, locale: str, now: datetime) -> dict:
    agg_row = (await db.execute(_aggregates_stmt(now))).one()

    today_count = await db.scalar(_today_count_stmt(now))

    tonight = list((await db.scalars(_tonight_stmt(now))).all())
    tonight_is_fallback = False
    if not tonight:
        tonight = list((await db.scalars(_tonight_fallback_stmt(now))).all())
        tonight_is_fallback = True

    return {
        "upcoming_count": agg_row.upcoming_count,
        "venue_count": agg_row.venue_count,
        "furthest_date": agg_row.furthest_date.date().isoformat() if agg_row.furthest_date else None,
        "cheapest_price": float(agg_row.cheapest_price) if agg_row.cheapest_price is not None else None,
        "today_count": today_count or 0,
        "tonight_is_fallback": tonight_is_fallback,
        "tonight_events": [
            {
                "title": resolve_title(e, locale),
                "starts_at": e.starts_at.isoformat(),
                "venue_name": resolve_venue_name(e, locale),
            }
            for e in tonight
        ],
    }


@router.get("/counts")
@limiter.limit(RATE_LIMIT_PUBLIC)
async def counts(
    request: Request,
    locale: str = Query(DEFAULT_USER_LOCALE),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Live numbers for the public landing page: upcoming/venue/category counts,
    the furthest-booked date, the cheapest paid ticket, and tonight's events (for
    the hero counter, the tonight ticker, and the flat proof section's stat row),
    plus ``today_count`` — the top bar pulse chip's exact count of what
    ``/explore?date=today`` lists (ongoing exhibitions included).

    Cached in-process for PUBLIC_COUNTS_CACHE_TTL_SECONDS — Landing client-fetches
    this live via React Query on every real visit (not just at prerender-build
    time), so an unbounded query per pageview isn't warranted for numbers that
    only meaningfully change a few times a day.
    """
    locale = resolve_locale_param(locale, DEFAULT_USER_LOCALE)

    cached = _counts_cache.get(locale)
    now_monotonic = time.monotonic()
    if cached is not None and now_monotonic - cached[0] < PUBLIC_COUNTS_CACHE_TTL_SECONDS:
        return cached[1]

    now = datetime.now(TALLINN_TZ)
    payload = await _load_counts(db, locale, now)
    _counts_cache[locale] = (now_monotonic, payload)
    return payload


def _prerender_event_ids_stmt(now: datetime) -> Select[tuple[int, datetime]]:
    """Every (id, updated_at) pair that should get a prerendered snapshot /
    sitemap entry: published + not explicit/non-event (``public_event_filter``),
    still live (``event_not_ended_filter``), and dedup-canonical
    (``canonical_event_filter``).

    Deliberately narrower than what GET /events/{id} itself serves — that
    endpoint applies only ``public_event_filter`` and will keep returning 200
    for an event that has since ended or fallen out of canonical status (an
    already-indexed URL shouldn't 404 on its own), so this id set is a subset
    of what's reachable, not an exact mirror of it. That's intentional: an
    ended/non-canonical event shouldn't get a *new* snapshot or sitemap entry,
    even though its last snapshot (if any) is only cleaned up by the next
    prerender run — the accepted staleness bound is one prerender cycle.

    ``updated_at`` (issue #80) is the prerender pipeline's change-detection
    marker — it lets ``prerender.ts`` tell which routes actually need
    re-rendering versus which can be copied forward from the currently-live
    production page.
    """
    return (
        select(Event.id, Event.updated_at)
        .where(
            public_event_filter(),
            event_not_ended_filter(now),
            canonical_event_filter(),
        )
        .order_by(Event.id)
    )


# Process-local TTL cache — single entry (payload isn't locale-sensitive),
# same pattern as _showcase_cache/_counts_cache above. This endpoint is public
# and RATE_LIMIT_PUBLIC-only, so it can be hit far more often than its actual
# build-time consumer calls it; caching bounds the cost of a repeated full
# table scan without weakening the atomic-snapshot guarantee below — each
# refresh is still one atomic query, just reused for the TTL window (Big-O
# audit #5, item 1.3).
_prerender_event_ids_cache: tuple[float, dict] | None = None


@router.get("/prerender-events")
@limiter.limit(RATE_LIMIT_PUBLIC)
async def prerender_events(request: Request, db: AsyncSession = Depends(get_db)) -> dict:
    """Events eligible for a prerendered snapshot — the build-time prerender
    script's single source of truth for "which events to prerender" (issue
    #50), reused as-is by sitemap.xml generation (issue #51) so the sitemap
    and the prerendered snapshot pages it lists always agree with each
    other (see _prerender_event_ids_stmt for how this compares to what GET
    /events/{id} serves). Each row's ``updated_at`` (issue #80) is the
    change-detection marker the pipeline diffs against each route's
    currently-live snapshot to decide render-vs-copy-forward.

    Deliberately unpaginated and un-LIMIT-ed: the build-time consumer needs a
    single atomic snapshot of the *entire* published id set, and a row-count
    cap would silently drop events from prerendering rather than just being
    slower to compute. The payload is small per row (``{id, updated_at}``).
    Cached for PUBLIC_COUNTS_CACHE_TTL_SECONDS — see _prerender_event_ids_cache.
    """
    global _prerender_event_ids_cache
    now_monotonic = time.monotonic()
    if (
        _prerender_event_ids_cache is not None
        and now_monotonic - _prerender_event_ids_cache[0] < PUBLIC_COUNTS_CACHE_TTL_SECONDS
    ):
        return _prerender_event_ids_cache[1]

    now = datetime.now(TALLINN_TZ)
    rows = (await db.execute(_prerender_event_ids_stmt(now))).all()
    payload = {
        "events": [
            {"id": event_id, "updated_at": updated_at.isoformat()}
            for event_id, updated_at in rows
        ]
    }
    _prerender_event_ids_cache = (now_monotonic, payload)
    return payload
