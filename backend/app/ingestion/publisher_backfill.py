"""One-time backfill: publishers/event_sources.publisher_id for currently-
claimable events (#409/#411). Live re-query only — never replays
raw_events.payload history (Publisher rows didn't always exist, so a historic
raw_events row's payload may predate the organizer_id stamp fix in
sources/fienta.py). Piletilevi is out of scope: its Publisher resolves from a
promoter id, handled by a later verification-mechanisms ticket, never via
event_sources.publisher_id directly.

Batch-job discipline (CLAUDE.md's Code Quality Rules): bulk-load, no N+1,
fixed DB-query count independent of row count. Fienta's HTTP re-query is
bounded by configured organizer count, not by event/row count.
"""

import logging
from datetime import datetime
from typing import cast

import httpx
from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import (
    EVENT_STATUS_PUBLISHED,
    FIENTA_MIN_REQUEST_INTERVAL_SECONDS,
    HTTP_TIMEOUT_SECONDS,
    SOURCE_SLUG_ESTONIA_CONCERT_HALL,
    SOURCE_SLUG_FIENTA,
    SOURCE_SLUG_KUMU,
    TALLINN_TZ,
)
from app.ingestion.adapter import load_publisher_lookup
from app.ingestion.http_client import AsyncRateLimiter
from app.ingestion.sources.fienta import FientaAdapter
from app.models.models import Event, EventSource, Source
from app.routers.utils import event_not_ended_filter

log = logging.getLogger(__name__)

_BACKFILL_SOURCE_SLUGS = (
    SOURCE_SLUG_FIENTA,
    SOURCE_SLUG_KUMU,
    SOURCE_SLUG_ESTONIA_CONCERT_HALL,
)


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


async def _backfill_fienta(db: AsyncSession, source: Source, now: datetime) -> int:
    """Re-query each configured organizer's live listing once — reusing
    FientaAdapter.fetch_organizer, which stamps organizer_id onto every
    item — to build external_id -> organizer_id, then bulk-resolve claimable
    event_sources rows against the already-mirrored publishers lookup."""
    event_sources = await _claimable_event_sources(db, source.id, now)
    if not event_sources:
        return 0

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
    organizer_by_external_id: dict[str, int] = {}
    limiter = AsyncRateLimiter(FIENTA_MIN_REQUEST_INTERVAL_SECONDS)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        for org_id in organizer_ids:
            try:
                items = await adapter.fetch_organizer(client, base_url, org_id, limiter)
            except httpx.HTTPError as exc:
                log.warning(
                    "publisher_backfill: fienta organizer=%s failed: %s", org_id, exc
                )
                continue
            for item in items:
                external_id = str(item.get("id", ""))
                if external_id:
                    organizer_by_external_id[external_id] = org_id

    publisher_lookup = await load_publisher_lookup(db, source.id)
    updated = 0
    for event_source in event_sources:
        matched_org_id = organizer_by_external_id.get(event_source.external_id or "")
        if matched_org_id is None:
            continue
        publisher_id = publisher_lookup.get(str(matched_org_id))
        if publisher_id is None:
            continue
        event_source.publisher_id = publisher_id
        updated += 1
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
                select(Source).where(Source.slug.in_(_BACKFILL_SOURCE_SLUGS))
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
