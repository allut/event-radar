"""Backfill: publishers/event_sources.publisher_id for currently-claimable
events (#409/#411). Fienta resolves in two steps: one bulk SQL read of each
listing's freshest `raw_events.payload->>'organizer_id'` stamp (a row that
predates the stamp simply has none), then a live organizer re-query only for
what is still unresolved and past its retry cooldown. Piletilevi is out of
scope: its Publisher resolves live, at claim time, from the event page's promoter identity
(`app.claims.target_resolution`, #427) — never backfilled here.

Batch-job discipline: bulk-load, no N+1,
fixed DB-query count independent of row count. Fienta's HTTP re-query is
bounded by configured organizer count, not by event/row count.
"""

import logging
from datetime import datetime
from typing import cast
from urllib.parse import urlsplit

import httpx
from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants.core import SQL_IN_CHUNK_SIZE, TALLINN_TZ
from app.constants.events import EVENT_STATUS_PUBLISHED
from app.constants.http import HTTP_TIMEOUT_SECONDS
from app.constants.ingestion import (
    FIENTA_MIN_REQUEST_INTERVAL_SECONDS,
    PUBLISHER_BACKFILL_SOURCE_SLUGS,
    PUBLISHER_RESOLVE_RETRY_COOLDOWN,
    SOURCE_SLUG_ESTONIA_CONCERT_HALL,
    SOURCE_SLUG_FIENTA,
    SOURCE_SLUG_KUMU,
)
from app.ingestion.adapter import load_publisher_lookup
from app.ingestion.http_client import AsyncRateLimiter, host_guard_hook
from app.ingestion.sources.fienta import FientaAdapter
from app.models.ingestion import RawEvent, Source
from app.models.events import Event, EventSource
from app.events.queries import event_not_ended_filter

log = logging.getLogger(__name__)

def _claimable_event_filter(now: datetime):
    return (
        EventSource.publisher_id.is_(None),
        Event.status == EVENT_STATUS_PUBLISHED,
        event_not_ended_filter(now),
    )


async def _claimable_event_sources(
    db: AsyncSession, source_id: int, now: datetime
) -> list[EventSource]:
    rows = (
        await db.scalars(
            select(EventSource)
            .join(Event, Event.id == EventSource.event_id)
            .where(EventSource.source_id == source_id, *_claimable_event_filter(now))
        )
    ).all()
    return list(rows)


async def _raw_organizer_by_external_id(
    db: AsyncSession, source_id: int, external_ids: list[str]
) -> dict[str, int]:
    """external_id -> organizer_id from each listing's freshest raw_events row
    carrying an organizer_id stamp — one query per SQL_IN_CHUNK_SIZE listings."""
    organizer_expr = RawEvent.payload["organizer_id"].as_string()
    resolved: dict[str, int] = {}
    for i in range(0, len(external_ids), SQL_IN_CHUNK_SIZE):
        rows = (
            await db.execute(
                select(RawEvent.external_id, organizer_expr)
                .where(
                    RawEvent.source_id == source_id,
                    RawEvent.external_id.in_(external_ids[i : i + SQL_IN_CHUNK_SIZE]),
                    organizer_expr.is_not(None),
                )
                .distinct(RawEvent.external_id)
                .order_by(RawEvent.external_id, RawEvent.fetched_at.desc())
            )
        ).all()
        for external_id, organizer_id in rows:
            try:
                resolved[external_id] = int(organizer_id)
            except (TypeError, ValueError):
                continue
    return resolved


async def _backfill_fienta(db: AsyncSession, source: Source, now: datetime) -> int:
    """Bulk-resolve claimable event_sources rows against the already-mirrored
    publishers lookup — first from raw_events' organizer_id stamps, then, only
    for rows still unresolved, by re-querying each configured organizer's live
    listing once (FientaAdapter.fetch_organizer stamps organizer_id onto every
    item) to build external_id -> organizer_id."""
    event_sources = await _claimable_event_sources(db, source.id, now)
    if not event_sources:
        return 0

    publisher_lookup = await load_publisher_lookup(db, source.id)
    organizer_by_external_id = await _raw_organizer_by_external_id(
        db, source.id, [es.external_id for es in event_sources if es.external_id]
    )
    updated = 0
    unresolved: list[EventSource] = []
    for event_source in event_sources:
        raw_org_id = organizer_by_external_id.get(event_source.external_id or "")
        publisher_id = (
            publisher_lookup.get(str(raw_org_id)) if raw_org_id is not None else None
        )
        if publisher_id is None:
            unresolved.append(event_source)
            continue
        event_source.publisher_id = publisher_id
        updated += 1
    # Rows the live crawl already failed on wait out the cooldown; the crawl
    # itself is skipped when nothing is due.
    cooldown_cutoff = now - PUBLISHER_RESOLVE_RETRY_COOLDOWN
    due = [
        es
        for es in unresolved
        if es.publisher_resolve_attempted_at is None
        or es.publisher_resolve_attempted_at <= cooldown_cutoff
    ]
    if not due:
        await db.flush()
        return updated

    # Include retired organizers too: a claimable (published, not-yet-ended)
    # event can trace back to an organizer that has since gone fully stale
    # and dropped out of the live organizer_ids filter (#411 review finding)
    # — excluding it here would leave that event permanently unresolved,
    # since this is a one-time script with no later retry.
    organizer_ids: list[int] = [
        int(x)
        for x in (
            list(source.config.get("organizer_ids", []))
            + list(source.config.get("retired_organizer_ids", []))
        )
    ]
    base_url: str = source.config.get("base_url", settings.FIENTA_BASE_URL)
    adapter = FientaAdapter(source)
    live_organizer_by_external_id: dict[str, int] = {}
    limiter = AsyncRateLimiter(FIENTA_MIN_REQUEST_INTERVAL_SECONDS)
    crawl_complete = True
    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT_SECONDS,
        event_hooks={"request": [host_guard_hook(urlsplit(base_url).hostname)]},
    ) as client:
        for org_id in organizer_ids:
            try:
                items = await adapter.fetch_organizer(client, base_url, org_id, limiter)
            except (httpx.HTTPError, ValueError) as exc:
                # ValueError: host_guard_hook rejected a links.next hop.
                log.warning(
                    "publisher_backfill: fienta organizer=%s failed: %s", org_id, exc
                )
                crawl_complete = False
                continue
            for item in items:
                external_id = str(item.get("id", ""))
                if external_id:
                    live_organizer_by_external_id[external_id] = org_id

    for event_source in due:
        matched_org_id = live_organizer_by_external_id.get(
            event_source.external_id or ""
        )
        publisher_id = (
            publisher_lookup.get(str(matched_org_id))
            if matched_org_id is not None
            else None
        )
        if publisher_id is not None:
            event_source.publisher_id = publisher_id
            updated += 1
        elif crawl_complete:
            # Only a full crawl proves the listing unresolvable — a failed
            # organizer fetch must not start a cooldown.
            event_source.publisher_resolve_attempted_at = now
    await db.flush()
    return updated


async def _backfill_constant_publisher(
    db: AsyncSession, source: Source, now: datetime
) -> int:
    """KUMU/Estonia Concert Hall: a single UPDATE against the source's one
    seeded Publisher row — fixed cost regardless of row count."""
    publisher_lookup = await load_publisher_lookup(db, source.id)
    publisher_id = publisher_lookup.get(None)
    if publisher_id is None:
        log.warning(
            "publisher_backfill: no seeded constant Publisher for source=%s — "
            "run seed_publishers() first",
            source.slug,
        )
        return 0

    # Scoped to this source's own event_sources rows (not a platform-wide
    # published-event scan) — the outer UPDATE re-filters by source_id too,
    # but an unscoped subquery here would still force the planner to
    # evaluate every published event across every source (#411 review
    # finding).
    claimable_event_ids = (
        select(EventSource.event_id)
        .join(Event, Event.id == EventSource.event_id)
        .where(
            EventSource.source_id == source.id,
            Event.status == EVENT_STATUS_PUBLISHED,
            event_not_ended_filter(now),
        )
    )
    result = await db.execute(
        update(EventSource)
        .where(
            EventSource.source_id == source.id,
            EventSource.publisher_id.is_(None),
            EventSource.event_id.in_(claimable_event_ids),
        )
        .values(publisher_id=publisher_id)
    )
    return cast(CursorResult, result).rowcount or 0


async def backfill_publisher_ids(db: AsyncSession) -> dict[str, int]:
    """Populate publishers/event_sources.publisher_id for currently-claimable
    (published, not-yet-ended) events only. Caller is responsible for
    committing the session after this returns."""
    now = datetime.now(tz=TALLINN_TZ)
    sources_by_slug = {
        s.slug: s
        for s in (
            await db.scalars(
                select(Source).where(Source.slug.in_(PUBLISHER_BACKFILL_SOURCE_SLUGS))
            )
        ).all()
    }

    results: dict[str, int] = {}
    fienta = sources_by_slug.get(SOURCE_SLUG_FIENTA)
    if fienta is not None:
        results[SOURCE_SLUG_FIENTA] = await _backfill_fienta(db, fienta, now)
    for slug in (SOURCE_SLUG_KUMU, SOURCE_SLUG_ESTONIA_CONCERT_HALL):
        source = sources_by_slug.get(slug)
        if source is not None:
            results[slug] = await _backfill_constant_publisher(db, source, now)
    return results
