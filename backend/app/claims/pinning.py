"""Claim-editing surface (#416): resolving "the event" a granted claim edits,
per-field pin/unpin bookkeeping, and the price-mismatch diff. See CONTEXT.md's
Event Claiming glossary and app/claims/lifecycle.py for claim create/cancel/
recheck.
"""

from dataclasses import dataclass
from datetime import datetime

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import false, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    CLAIM_KIND_PUBLISHER,
    CLAIM_KIND_SERIES,
    CLAIM_STATUS_APPROVED,
    HTML_PARSER,
    ORGANIZER_CLAIM_EDIT_CAP_CEILING,
    ORGANIZER_CLAIM_EDIT_CAP_PER_EVENT,
    ORGANIZER_DAILY_CLAIM_EDIT_CAP,
    REFETCH_PRICE_TOLERANCE,
    TALLINN_TZ,
)
from app.ingestion.http_client import http_get, normalized_hostname
from app.ingestion.jsonld import offers_from_jsonld_items, parse_jsonld_event_items
from app.ingestion.price_fallback import PRICE_FALLBACK_EXTRACTORS
from app.models.models import Claim, Event, EventSource
from app.routers.utils import (
    publisher_claim_event_ids,
    select_events_with_classification,
)
from app.events.queries import (
    event_not_ended_filter,
)

from .lifecycle import representative_event_source


async def claim_event_for_id(
    db: AsyncSession, claim: Claim, event_id: int | None
) -> Event | None:
    """Resolve the specific Event a claim edit (#437) targets. A Publisher
    claim given an explicit event_id re-derives claim coverage server-side
    via the same EventSource.publisher_id match list_claim_events (#436)
    uses — never trusts the client-supplied claim/event pairing; an event
    outside that set resolves to None (caller 404s). With no event_id, or
    for a Series claim (no bulk coverage query to run — Claim carries only
    a normalized title/venue key), falls back to the existing
    single-representative-event resolution."""
    if event_id is not None and claim.kind == CLAIM_KIND_PUBLISHER:
        matching_event_ids = publisher_claim_event_ids(claim.publisher_id)
        return await db.scalar(
            select_events_with_classification().where(
                Event.id == event_id, Event.id.in_(matching_event_ids)
            )
        )
    return await representative_event_for_claim(db, claim)


async def representative_event_for_claim(db: AsyncSession, claim: Claim) -> Event | None:
    """The single Event row this claim's edits land on. A Publisher claim
    reuses the same "freshest traced-back listing" lookup recheck_claim
    already relies on. A Series claim has no FK to walk (Claim carries only
    the normalized title/venue key), so it looks up not-yet-ended events by
    the indexed ``Event.series_key`` column."""
    if claim.kind == CLAIM_KIND_PUBLISHER:
        es = await representative_event_source(db, publisher_id=claim.publisher_id)
        if es is None:
            return None
        return await db.scalar(
            select_events_with_classification().where(Event.id == es.event_id)
        )

    if claim.event_series_key is None:
        return None
    resolved = await bulk_resolve_series_events(db, {claim.event_series_key})
    return resolved.get(claim.event_series_key)


async def bulk_resolve_series_events(
    db: AsyncSession, series_keys: set[str]
) -> dict[str, Event]:
    """Series-claim counterpart of ``bulk_resolve_publisher_events``: one
    indexed query (``events.series_key``, trigger-maintained — migration
    0052) over the not-yet-ended events carrying any requested key, instead
    of one scan per claim. The earliest-starting match wins per key, same as
    the single-claim lookup. Keys with no match are absent from the result."""
    if not series_keys:
        return {}
    now = datetime.now(TALLINN_TZ)
    candidates = (
        (
            await db.execute(
                select_events_with_classification()
                .where(Event.series_key.in_(series_keys), event_not_ended_filter(now))
                .order_by(Event.starts_at)
            )
        )
        .scalars()
        .all()
    )
    matched: dict[str, Event] = {}
    for event in candidates:
        if event.series_key is not None:
            matched.setdefault(event.series_key, event)
    return matched


async def clear_claim_pins(db: AsyncSession, claim: Claim) -> list[int]:
    """Bulk-clear pinned_fields on every event `claim` covers (#442) — not
    just the one representative_event_for_claim() picks. Publisher coverage
    reuses publisher_claim_event_ids(); a Series claim has no FK to
    bulk-filter on (Claim carries only a normalized title/venue key), so its
    candidates are the pinned events whose indexed ``Event.series_key``
    equals claim.event_series_key — same key representative_event_for_claim()
    resolves against, so a
    Publisher event whose EventSource has since been re-linked to a
    different publisher_id is likewise outside what either function can
    still see (pre-existing limitation, not new here). Either kind ends in
    one bulk UPDATE, never a per-row write. Returns the cleared event ids
    for the caller's result/log."""
    if claim.kind == CLAIM_KIND_PUBLISHER:
        covered_ids = publisher_claim_event_ids(claim.publisher_id)
        event_ids = list(
            (
                await db.scalars(
                    select(Event.id).where(
                        Event.id.in_(covered_ids),
                        func.jsonb_array_length(Event.pinned_fields) > 0,
                    )
                )
            ).all()
        )
    else:
        event_ids = list(
            (
                await db.scalars(
                    select(Event.id).where(
                        Event.series_key == claim.event_series_key,
                        func.jsonb_array_length(Event.pinned_fields) > 0,
                    )
                )
            ).all()
        )
    if event_ids:
        await db.execute(update(Event).where(Event.id.in_(event_ids)).values(pinned_fields=[]))
    return event_ids


def pin_key(field: str, locale: str | None = None) -> str:
    """"<field>" or "<field>:<locale>" — the entry format Event.pinned_fields
    stores (models.py docstring)."""
    return f"{field}:{locale}" if locale else field


def apply_pins(current: list[str], *, pin: set[str], unpin: set[str]) -> list[str]:
    """Merge `pin`/`unpin` deltas into the stored pinned_fields list. `unpin`
    is applied first so a field named in both this same request's edits and
    its unpin list (nonsensical, but not worth 422ing over) ends up pinned —
    an explicit edit always wins."""
    pins = set(current) - unpin
    pins |= pin
    return sorted(pins)


async def organizer_covered_event_count(db: AsyncSession, organizer_id: int) -> int:
    """How many events the organizer's approved, non-dormant claim(s)
    currently cover — feeds scaled_claim_edit_cap() (#438). A Publisher
    claim's coverage is the same EventSource.publisher_id match
    list_claim_events (#436) uses, bulk-counted (distinct event id) across
    every approved Publisher claim the organizer holds in one query — fixed
    query count regardless of how many claims or events (CLAUDE.md's Batch
    jobs rule). A Series claim has no FK to bulk-count against (Claim carries
    only a normalized title/venue key, per the Claim model docstring), so it
    counts as the one representative event the claim-editing surface
    actually exposes for it. A dormant claim's pins don't apply (#422), so it
    contributes nothing here either."""
    rows = (
        await db.execute(
            select(Claim.kind, Claim.publisher_id).where(
                Claim.organizer_id == organizer_id,
                Claim.status == CLAIM_STATUS_APPROVED,
                Claim.dormant == false(),
            )
        )
    ).all()
    publisher_ids = [r.publisher_id for r in rows if r.kind == CLAIM_KIND_PUBLISHER]
    series_count = sum(1 for r in rows if r.kind == CLAIM_KIND_SERIES)
    publisher_event_count = 0
    if publisher_ids:
        publisher_event_count = (
            await db.execute(
                select(func.count(func.distinct(EventSource.event_id))).where(
                    EventSource.publisher_id.in_(publisher_ids)
                )
            )
        ).scalar() or 0
    return publisher_event_count + series_count


def scaled_claim_edit_cap(covered_event_count: int) -> int:
    """The daily claim-edit cap (#438), scaled from
    ORGANIZER_DAILY_CLAIM_EDIT_CAP by how many events the organizer's
    claim(s) cover. A single covered event (the common case) yields exactly
    the flat baseline unchanged; every additional covered event adds
    ORGANIZER_CLAIM_EDIT_CAP_PER_EVENT, bounded by
    ORGANIZER_CLAIM_EDIT_CAP_CEILING so a large institutional claim (e.g.
    Estonia Concert Hall's 61 events) still hits a genuine limit rather than
    an effectively unbounded one."""
    extra_events = max(0, covered_event_count - 1)
    return min(
        ORGANIZER_CLAIM_EDIT_CAP_CEILING,
        ORGANIZER_DAILY_CLAIM_EDIT_CAP + extra_events * ORGANIZER_CLAIM_EDIT_CAP_PER_EVENT,
    )


@dataclass(frozen=True)
class FreshPrice:
    price_min: float | None
    price_max: float | None
    currency: str | None
    has_free_tier: bool


async def fetch_fresh_price(client: httpx.AsyncClient, event: Event) -> FreshPrice | None:
    """Re-fetch `event.url`'s detail page and read its schema.org offers —
    the same JSON-LD parse refetch_event_details() uses, but read-only (no
    row mutation): the claim-editing surface only ever writes price fields
    through an explicit organizer action (direct edit or "Accept new
    price"). Falls back to the same per-host selector-based price extraction
    (PRICE_FALLBACK_EXTRACTORS, #424) refetch_event_details() uses when the
    page carries no Event/offers JSON-LD at all. Returns None when there's
    no url to check or neither path finds a price, in which case the surface
    shows no mismatch badge."""
    if not event.url:
        return None
    try:
        response = await http_get(client, event.url)
    except (httpx.HTTPStatusError, httpx.RequestError, ValueError):
        return None
    soup = BeautifulSoup(response.text, HTML_PARSER)
    jsonld_items = parse_jsonld_event_items(soup)
    price_min, price_max, currency, has_free_tier = offers_from_jsonld_items(jsonld_items)
    if price_min is None and price_max is None and currency is None and not has_free_tier:
        fallback = PRICE_FALLBACK_EXTRACTORS.get(normalized_hostname(event.url))
        if fallback is not None:
            price_min, price_max, currency, has_free_tier = fallback(soup)
    if price_min is None and price_max is None and currency is None and not has_free_tier:
        return None
    return FreshPrice(price_min, price_max, currency, has_free_tier)


def _differs(stored: float | None, fresh: float | None) -> bool:
    if fresh is None:
        return False
    if stored is None:
        return True
    return abs(float(stored) - fresh) > REFETCH_PRICE_TOLERANCE


def price_mismatch(event: Event, fresh: FreshPrice | None) -> dict | None:
    """The diff the price-mismatch badge renders, or None when there is
    nothing to show (no fresh read, or the fresh read matches what's
    stored)."""
    if fresh is None:
        return None
    changed = (
        _differs(event.price_min, fresh.price_min)
        or _differs(event.price_max, fresh.price_max)
        or (fresh.currency is not None and fresh.currency != event.currency)
        or (fresh.has_free_tier and not event.has_free_tier)
    )
    if not changed:
        return None
    return {
        "price_min": fresh.price_min,
        "price_max": fresh.price_max,
        "currency": fresh.currency,
        "has_free_tier": fresh.has_free_tier,
    }
