"""Claim-time Publisher/Series target resolution (#427) — the single
resolution step reused by claim creation, claim recheck, and verification
dispatch. Unlike the sync `resolve_claim_target()` in `app.claims.lifecycle`
(a cheap, HTTP-free lookup for *existing* claims that trusts an already-
stamped `EventSource.publisher_id`), `resolve_claim_target_live()` is the one
place a *new* claim's target gets decided, and does not trust an unstamped
row alone: it re-resolves live per source, stamping the row on success so a
later call for the same listing skips re-resolving. Fienta never crawls live
here — see `_resolve_fienta_publisher`. See
CONTEXT.md's Event Claiming glossary and docs/pipeline.md's Publisher
mirroring section.
"""

import logging
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.claims.piletilevi_promoter import resolve_promoter_identity
from app.constants import (
    CLAIM_KIND_PUBLISHER,
    CLAIM_KIND_SERIES,
    ORGANIZER_NAME_MAX_LEN,
    PUBLISHER_STATUS_ACTIVE,
    SOURCE_SLUG_ESTONIA_CONCERT_HALL,
    SOURCE_SLUG_FIENTA,
    SOURCE_SLUG_KUMU,
    SOURCE_SLUG_PILETILEVI,
)
from app.ingestion.http_client import http_get_stored_url
from app.models.models import Event, EventSource, Publisher, RawEvent, Source
from app.events.venue import resolve_venue_name
from app.events.queries import event_series_key, serialize_event_series_key

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClaimTarget:
    kind: str
    publisher_id: int | None
    event_series_key: str | None
    # (#439) The Piletilevi event page's HTML, when this resolution fetched it
    # to decide Publisher-vs-Series — set only on that first-fetch path, so
    # `create_claim` can hand it straight to `verify_piletilevi_claim` instead
    # of a second live fetch of the same `event.url`. None for every other
    # source, and for a Piletilevi target whose Publisher was already
    # stamped (no fetch needed here). `recheck_claim` never sees this value —
    # it re-verifies live on purpose (current DNS/contact state), never via
    # this dataclass.
    event_page_html: str | None = None


class ClaimTargetError(Exception):
    """`es` has no resolvable Publisher and isn't Piletilevi — the caller
    (`app.claims.lifecycle`) maps this onto ClaimError(422,
    ERROR_CLAIM_NOT_CLAIMABLE) rather than silently downgrading to a Series
    or admin-review claim (#427's acceptance criteria)."""


async def _get_or_create_publisher(
    db: AsyncSession, *, source_id: int, external_id: str | None, name: str
) -> Publisher:
    """Get-or-create keyed on (source_id, external_id) — a savepoint absorbs
    a concurrent resolution racing to create the same row (the partial
    unique indexes on `publishers` are what it's racing against)."""
    existing = await db.scalar(
        select(Publisher).where(
            Publisher.source_id == source_id, Publisher.external_id == external_id
        )
    )
    if existing is not None:
        return existing

    publisher = Publisher(
        source_id=source_id,
        external_id=external_id,
        name=name[:ORGANIZER_NAME_MAX_LEN],
        status=PUBLISHER_STATUS_ACTIVE,
    )
    try:
        async with db.begin_nested():
            db.add(publisher)
            await db.flush()
    except IntegrityError:
        db.expunge(publisher)
        existing = await db.scalar(
            select(Publisher).where(
                Publisher.source_id == source_id, Publisher.external_id == external_id
            )
        )
        if existing is None:
            raise
        return existing
    return publisher


async def _fienta_organizer_id_from_raw_payload(
    db: AsyncSession, source_id: int, external_id: str | None
) -> int | None:
    """The freshest `raw_events` row for this listing's own organizer_id
    stamp (`sources/fienta.py::fetch_organizer` sets it on every item it
    collects) — cheaper than a live re-query and correct as long as this
    event has ever been ingested since that stamp existed."""
    if not external_id:
        return None
    raw = await db.scalar(
        select(RawEvent)
        .where(RawEvent.source_id == source_id, RawEvent.external_id == external_id)
        .order_by(RawEvent.fetched_at.desc())
        .limit(1)
    )
    if raw is None:
        return None
    organizer_id = raw.payload.get("organizer_id")
    if organizer_id is None:
        return None
    try:
        return int(organizer_id)
    except (TypeError, ValueError):
        return None


async def _resolve_fienta_publisher(
    db: AsyncSession, source: Source, es: EventSource
) -> Publisher | None:
    if es.publisher_id is not None:
        return es.publisher

    # Never live-crawl Fienta in the request path: an unresolved listing is
    # rejected as not-claimable until the 6-hourly `backfill_publisher_ids`
    # job stamps it (raw_events first, then a bounded live re-query).
    organizer_id = await _fienta_organizer_id_from_raw_payload(
        db, source.id, es.external_id
    )
    if organizer_id is None:
        return None

    external_id = str(organizer_id)
    name = str(source.config.get("organizer_names", {}).get(external_id, external_id))
    publisher = await _get_or_create_publisher(
        db, source_id=source.id, external_id=external_id, name=name
    )
    es.publisher_id = publisher.id
    es.publisher = publisher
    await db.flush()
    return publisher


async def _resolve_institutional_publisher(
    db: AsyncSession, source: Source, es: EventSource
) -> Publisher | None:
    """KUMU/Estonia Concert Hall: always the source's single seeded
    constant Publisher (`external_id IS NULL`) — independent of whatever
    `es.publisher_id` currently holds."""
    publisher = await db.scalar(
        select(Publisher).where(Publisher.source_id == source.id, Publisher.external_id.is_(None))
    )
    if publisher is None:
        return None
    es.publisher_id = publisher.id
    es.publisher = publisher
    return publisher


async def _resolve_piletilevi_target(
    db: AsyncSession,
    client: httpx.AsyncClient,
    source: Source,
    event: Event,
    es: EventSource,
) -> ClaimTarget:
    """Any promoter identity that resolves — domain or not — always yields a
    Publisher target; only a promoter that fails to resolve at all falls
    back to a Series target."""
    if es.publisher_id is not None:
        return ClaimTarget(CLAIM_KIND_PUBLISHER, es.publisher_id, None)

    identity = None
    html: str | None = None
    if event.url:
        try:
            response = await http_get_stored_url(client, event.url)
            html = response.text
            identity = resolve_promoter_identity(html, event.url)
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("claim target resolution: piletilevi event fetch failed: %s", exc)
            identity = None

    if identity is None:
        key = serialize_event_series_key(
            event_series_key(event.title_orig, resolve_venue_name(event))
        )
        return ClaimTarget(CLAIM_KIND_SERIES, None, key)

    name = identity.name or identity.external_id
    publisher = await _get_or_create_publisher(
        db, source_id=source.id, external_id=identity.external_id, name=name
    )
    es.publisher_id = publisher.id
    es.publisher = publisher
    await db.flush()
    return ClaimTarget(CLAIM_KIND_PUBLISHER, publisher.id, None, event_page_html=html)


async def resolve_claim_target_live(
    db: AsyncSession, client: httpx.AsyncClient, event: Event, es: EventSource
) -> ClaimTarget:
    """The real Publisher/Series target for `es`, resolved live per source
    rather than trusting a possibly-unstamped `EventSource.publisher_id`
    alone. Raises `ClaimTargetError` for a non-Piletilevi source with no
    resolvable Publisher — that case is rejected as not-claimable, never
    silently downgraded to a Series or admin-review claim."""
    source = es.source
    slug = source.slug if source is not None else None

    if slug == SOURCE_SLUG_FIENTA:
        publisher = await _resolve_fienta_publisher(db, source, es)
        if publisher is None:
            raise ClaimTargetError(f"no resolvable Fienta publisher for event_source={es.id}")
        return ClaimTarget(CLAIM_KIND_PUBLISHER, publisher.id, None)

    if slug in (SOURCE_SLUG_KUMU, SOURCE_SLUG_ESTONIA_CONCERT_HALL):
        publisher = await _resolve_institutional_publisher(db, source, es)
        if publisher is None:
            raise ClaimTargetError(f"no seeded constant publisher for source={slug}")
        return ClaimTarget(CLAIM_KIND_PUBLISHER, publisher.id, None)

    if slug == SOURCE_SLUG_PILETILEVI:
        return await _resolve_piletilevi_target(db, client, source, event, es)

    raise ClaimTargetError(f"source={slug} has no resolvable claim target")
