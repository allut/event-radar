"""Geocoding pipeline: backfill lat/lng for events with an address but no coords.

Sub-passes live in their own modules; ``geocode_pending`` orchestrates them:
self-heal out-of-bbox coords -> organizer-Venue pass + coord sync
(venue_pass.py) -> venue_extract (LLM address mining) -> sibling_copy ->
Nominatim lookup (nominatim.py).
"""

import asyncio
import logging
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import cast

import httpx
from sqlalchemy import false, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    GEOCODE_COMMIT_INTERVAL_SECONDS,
    GEOCODE_DONOR_LOOKBACK_DAYS,
    GEOCODE_MAX_PER_RUN,
    GEOCODE_REQUEST_DELAY_SECONDS,
    GEOCODE_RETRY_INTERVAL_DAYS,
    HTTP_TIMEOUT_SECONDS,
    TALLINN_REGION_BBOX,
    TALLINN_TZ,
)
from app.ingestion.adapter import coords_in_tallinn
from app.ingestion.geocode.nominatim import (
    geocode_address,
    normalize_address_for_geocoding,
)
from app.ingestion.geocode.sibling_copy import (
    canonical_venue_name,
    copy_venue_from_siblings,
)
from app.ingestion.geocode.venue_extract import (
    extract_address_from_venue_name,
    is_suspect_venue_name,
)
from app.ingestion.geocode.venue_pass import geocode_pending_venues
from app.models.models import Event, Venue

__all__ = [
    "canonical_venue_name",
    "copy_venue_from_siblings",
    "extract_address_from_venue_name",
    "geocode_address",
    "geocode_pending",
    "geocode_pending_venues",
    "is_suspect_venue_name",
    "normalize_address_for_geocoding",
]

log = logging.getLogger(__name__)


async def _self_heal_out_of_bbox_coords(db: AsyncSession) -> int:
    """NULL lat/lng (and reset the cooldown) for events mis-geocoded outside Tallinn.

    Targets only rows where ``is_out_of_area`` is False — the event genuinely
    belongs in the target city, so a stored coord outside ``TALLINN_REGION_BBOX``
    is a wrong match (e.g. a same-named place elsewhere in Estonia), not a
    legitimately out-of-area event (those have ``is_out_of_area`` True and never
    publish anyway, so are left untouched). One bulk UPDATE, no N+1. NULLing
    re-enters the row into the pending query below within the same run, where
    ``geocode_address``'s bbox gate now prevents re-storing the same wrong coord.
    """
    stmt = (
        update(Event)
        .where(
            Event.is_out_of_area == false(),
            Event.lat.is_not(None),
            Event.lng.is_not(None),
            or_(
                ~Event.lat.between(*TALLINN_REGION_BBOX[0:2]),
                ~Event.lng.between(*TALLINN_REGION_BBOX[2:4]),
            ),
        )
        .values(lat=None, lng=None, geocode_attempted_at=None)
    )
    result = await db.execute(stmt)
    healed = cast(CursorResult, result).rowcount
    if healed:
        log.info("self-healed %d event(s) with out-of-bbox coords", healed)
    return healed


async def _sync_venue_linked_coords(db: AsyncSession) -> int:
    """Copy a linked Venue's resolved coords onto its Events (#179).

    Covers two cases with one bulk UPDATE...FROM (fixed query count, no N+1):
    an event submitted before its venue's geocode resolved (event.lat IS NULL),
    and a later venue address correction (organizer_venues.py clears the
    venue's own lat/lng/geocode_attempted_at on edit, then geocode_pending_venues
    re-resolves them to a new coord) propagating forward onto already-published
    events at that venue. The one deliberate, scoped exception to this feature's
    otherwise forward-only/no-backfill behavior — it only touches events already
    linked via venue_id, never retroactively links unlinked ones. Rows already
    matching the venue's coords are excluded from the WHERE clause so the
    rowcount reflects only rows actually changed.
    """
    stmt = (
        update(Event)
        .where(
            Event.venue_id == Venue.id,
            Venue.lat.is_not(None),
            Venue.lng.is_not(None),
            or_(
                Event.lat.is_(None),
                Event.lng.is_(None),
                Event.lat != Venue.lat,
                Event.lng != Venue.lng,
            ),
        )
        .values(lat=Venue.lat, lng=Venue.lng)
    )
    result = await db.execute(stmt)
    synced = cast(CursorResult, result).rowcount
    if synced:
        log.info("synced venue-linked coords onto %d event(s)", synced)
    return synced


async def _build_geocode_cache(
    db: AsyncSession,
    now: datetime,
) -> dict[str, tuple[float, float] | None]:
    """Seed a normalized-query → coords cache from recently-geocoded events.

    Avoids re-hitting Nominatim for venues we already know, including
    spelling/unit variants (the key is the normalized query). Most-common
    coord wins per key (lex tie-break). Donors outside the Tallinn bbox are
    dropped so a bad stored coord can't seed the cache for a sibling address
    (belt-and-suspenders alongside the self-heal pass).

    Bounded to the last GEOCODE_DONOR_LOOKBACK_DAYS — events rows are never
    deleted, so an unbounded scan here grows with all-time ingestion volume.
    Grouped in SQL (not hauled into Python row-by-row) so a venue with many
    events costs one row here, not one per event.
    """
    cutoff = now - timedelta(days=GEOCODE_DONOR_LOOKBACK_DAYS)
    donor_rows = (
        await db.execute(
            select(Event.venue_address, Event.lat, Event.lng, func.count())
            .where(
                Event.venue_address.is_not(None),
                Event.lat.is_not(None),
                Event.starts_at >= cutoff,
            )
            .group_by(Event.venue_address, Event.lat, Event.lng)
        )
    ).all()
    coords_by_query: dict[str, Counter[tuple[float, float]]] = defaultdict(Counter)
    for address, lat, lng, count in donor_rows:
        if not coords_in_tallinn(lat, lng):
            continue
        coords_by_query[normalize_address_for_geocoding(address)][(lat, lng)] += count
    return {
        query: min(counter.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        for query, counter in coords_by_query.items()
    }


async def _run_nominatim_pass(
    db: AsyncSession,
    pending: list[Event],
    cache: dict[str, tuple[float, float] | None],
    now: datetime,
) -> tuple[int, int]:
    """Geocode pending events serially (Nominatim policy: max 1 req/s).

    Returns (geocoded, failed). A transient HTTP failure does NOT start the
    retry cooldown (geocode_attempted_at) — only a definitive
    no-match/bbox-reject does, mirroring refetch's throttle behavior.
    Commits mid-loop on the Neon keep-alive cadence.
    """
    geocoded = 0
    failed = 0
    transient_failure_queries: set[str] = set()
    last_commit = time.monotonic()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        for event in pending:
            raw_address = event.venue_address
            assert raw_address is not None  # guaranteed by the pending query
            query = normalize_address_for_geocoding(raw_address)

            if query not in cache:
                try:
                    cache[query] = await geocode_address(client, query, original=raw_address)
                except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                    log.warning("geocode failed address=%s: %s", raw_address, exc)
                    cache[query] = None
                    transient_failure_queries.add(query)
                await asyncio.sleep(GEOCODE_REQUEST_DELAY_SECONDS)

            coords = cache[query]
            if coords is None:
                failed += 1
                if query not in transient_failure_queries:
                    event.geocode_attempted_at = now
            else:
                event.lat, event.lng = coords
                event.geocode_attempted_at = now
                geocoded += 1
            if time.monotonic() - last_commit >= GEOCODE_COMMIT_INTERVAL_SECONDS:
                await db.commit()
                last_commit = time.monotonic()
    return geocoded, failed


async def geocode_pending(db: AsyncSession) -> dict:
    """Backfill lat/lng for events with a venue_address but no coordinates.

    The Nominatim pass itself is two queries regardless of row count: one for
    pending events (capped at GEOCODE_MAX_PER_RUN), one to seed a
    normalized-query→coords cache from **all** geocoded events (not just
    pending-address matches) — avoids re-hitting
    Nominatim for venues we already know, including spelling/unit variants of an
    address that some other event already resolved. The cache is keyed by the
    *normalized* query so format variants of one venue (e.g. "60a/9" vs "60a / 9")
    share a single Nominatim call.
    Remaining distinct addresses are geocoded serially with a delay between calls
    per Nominatim's usage policy (max 1 req/s).

    Before any of that, self-heals events whose stored coord is outside the
    Tallinn bbox despite being in-area (see _self_heal_out_of_bbox_coords) — done
    first so a bad donor coord can't propagate to copy_venue_from_siblings or the
    Nominatim cache below within the same run.

    Next, resolves any organizer-saved Venue with a pending address
    (geocode_pending_venues, #179) and syncs each linked Venue's resolved coords
    onto its Events (_sync_venue_linked_coords) — a venue-linked event has
    venue_name/venue_address left NULL at write time (#176), so it never enters
    the venue_address-driven passes below; this is its only coordinate path.

    First copies venue data between same-name siblings (copy_venue_from_siblings),
    so copied coords count toward the run; any copied row still missing coords
    falls through to the Nominatim pass below. The sibling copy makes no Nominatim
    calls and sets lat, so copied rows are excluded from the pending query — the
    Nominatim-call ceiling stays GEOCODE_MAX_PER_RUN even though total DB writes
    across both passes (copy + geocode) can reach 2x that on disjoint event sets.

    The pending query also excludes addresses that failed within the last
    GEOCODE_RETRY_INTERVAL_DAYS (geocode_attempted_at), so a permanently
    un-resolvable address isn't re-sent to Nominatim every run.
    """
    now = datetime.now(TALLINN_TZ)
    healed = await _self_heal_out_of_bbox_coords(db)
    venues_geocoded, venues_failed = await geocode_pending_venues(db, now)
    synced = await _sync_venue_linked_coords(db)
    extracted = await extract_address_from_venue_name(db)
    copied = await copy_venue_from_siblings(db, now)

    due_before = now - timedelta(days=GEOCODE_RETRY_INTERVAL_DAYS)
    pending = (
        await db.scalars(
            select(Event)
            .where(
                Event.venue_address.is_not(None),
                Event.lat.is_(None),
                or_(
                    Event.geocode_attempted_at.is_(None),
                    Event.geocode_attempted_at < due_before,
                ),
            )
            .order_by(Event.geocode_attempted_at.asc().nulls_first())
            .limit(GEOCODE_MAX_PER_RUN)
        )
    ).all()
    if not pending:
        return {
            "pending": 0,
            "geocoded": 0,
            "failed": 0,
            "copied": copied,
            "extracted": extracted,
            "healed": healed,
            "venues_geocoded": venues_geocoded,
            "venues_failed": venues_failed,
            "synced": synced,
        }

    cache = await _build_geocode_cache(db, now)
    geocoded, failed = await _run_nominatim_pass(db, list(pending), cache, now)

    return {
        "pending": len(pending),
        "geocoded": geocoded,
        "failed": failed,
        "copied": copied,
        "extracted": extracted,
        "healed": healed,
        "venues_geocoded": venues_geocoded,
        "venues_failed": venues_failed,
        "synced": synced,
    }
