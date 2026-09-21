"""Claim-editing surface (#416): resolving "the event" a granted claim edits,
per-field pin/unpin bookkeeping, and the price-mismatch diff. See CONTEXT.md's
Event Claiming glossary and app/claims/lifecycle.py for claim create/cancel/
recheck.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    CLAIM_EDIT_SERIES_EVENT_SCAN_LIMIT,
    CLAIM_KIND_PUBLISHER,
    HTML_PARSER,
    REFETCH_PRICE_TOLERANCE,
)
from app.ingestion.http_client import http_get
from app.ingestion.jsonld import offers_from_jsonld_items, parse_jsonld_event_items
from app.models.models import Claim, Event
from app.routers.utils import (
    event_not_ended_filter,
    event_series_key,
    resolve_venue_name,
    select_events_with_classification,
    serialize_event_series_key,
)

from .lifecycle import representative_event_source


async def representative_event_for_claim(db: AsyncSession, claim: Claim) -> Event | None:
    """The single Event row this claim's edits land on. A Publisher claim
    reuses the same "freshest traced-back listing" lookup recheck_claim
    already relies on. A Series claim has no FK to walk (Claim carries only
    the normalized title/venue key), so it scans not-yet-ended events
    newest-starting-first for a computed-key match, bounded by
    CLAIM_EDIT_SERIES_EVENT_SCAN_LIMIT."""
    if claim.kind == CLAIM_KIND_PUBLISHER:
        es = await representative_event_source(db, publisher_id=claim.publisher_id)
        if es is None:
            return None
        return await db.scalar(
            select_events_with_classification().where(Event.id == es.event_id)
        )

    now = datetime.now(timezone.utc)
    candidates = (
        (
            await db.execute(
                select_events_with_classification()
                .where(event_not_ended_filter(now))
                .order_by(Event.starts_at)
                .limit(CLAIM_EDIT_SERIES_EVENT_SCAN_LIMIT)
            )
        )
        .scalars()
        .all()
    )
    for event in candidates:
        key = serialize_event_series_key(
            event_series_key(event.title_orig, resolve_venue_name(event))
        )
        if key == claim.event_series_key:
            return event
    return None


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
    price"). Returns None when there's no url to check or the page carries
    no offers at all, in which case the surface shows no mismatch badge."""
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
