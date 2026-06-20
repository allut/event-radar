"""Daily detail-page refetch sync for future events.

Re-fetches every future event's detail page (``event.url``), parses the
schema.org JSON-LD ``Event`` block, and reconciles the stored row against the
source: updating ``venue_name``/``venue_address``/``lat``/``lng``/price fields
when the detail page reports a *different* value, and filling them when they were
empty — never clobbering a good stored value with nothing.

Generic JSON-LD, not Fienta-specific: it no-ops on any page without an ``Event``
block, so it is safe across sources (Fienta is the only beneficiary today; HTML
sources already fetch detail at ingest).

Coexists with the geocode passes (``extract_address_from_venue_name`` /
``copy_venue_from_siblings``): ``venue_address`` and ``lat``/``lng`` are
reconciled as one coupled unit so they never drift apart, and a clean stored
``venue_name`` is never overwritten by a suspect detail name. See the module
docstring of ``geocode.py`` and the project plan for the full rationale.
"""

import asyncio
import logging
from datetime import datetime, timedelta

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    EVENT_STATUS_CLASSIFIED,
    EVENT_STATUS_PUBLISHED,
    GEOCODE_COORD_QUANT_DECIMALS,
    HTTP_TIMEOUT_SECONDS,
    REFETCH_MAX_PER_RUN,
    REFETCH_MIN_INTERVAL_DAYS,
    REFETCH_PLACEHOLDER_VENUE_NAMES,
    REFETCH_PRICE_TOLERANCE,
    REFETCH_REQUEST_DELAY_SECONDS,
    TALLINN_TZ,
    VENUE_NAME_MAX_LEN,
)
from app.ingestion.base import (
    extract_jsonld_event_location,
    extract_jsonld_event_offers,
    http_get,
    is_explicit_text,
)
from app.ingestion.geocode import is_suspect_venue_name
from app.models.models import Event

log = logging.getLogger(__name__)


def _is_empty_venue_name(name: str | None) -> bool:
    """True when a stored venue_name is missing or a placeholder (replaceable)."""
    if name is None:
        return True
    stripped = name.strip()
    if not stripped:
        return True
    return stripped.lower() in REFETCH_PLACEHOLDER_VENUE_NAMES


def _price_differs(stored: float | None, fresh: float) -> bool:
    """True when a detail-page price differs from the stored value beyond tolerance.

    A NULL stored price with any fresh price counts as a change (fill case).
    ``stored`` is a ``Decimal`` (Numeric column) or None at runtime; ``fresh`` is a float.
    """
    if stored is None:
        return True
    return abs(float(stored) - fresh) > REFETCH_PRICE_TOLERANCE


def _coords_differ(
    stored_lat: float | None,
    stored_lng: float | None,
    fresh_lat: float,
    fresh_lng: float,
) -> bool:
    """True when fresh coords differ from stored beyond the quantization grid.

    NULL stored coords with present fresh coords count as a change (fill case).
    Comparison is rounded to GEOCODE_COORD_QUANT_DECIMALS — the same grid
    copy_venue_from_siblings uses — so a sub-meter re-store reads as unchanged.
    """
    if stored_lat is None or stored_lng is None:
        return True
    q = GEOCODE_COORD_QUANT_DECIMALS
    return (
        round(stored_lat, q) != round(fresh_lat, q)
        or round(stored_lng, q) != round(fresh_lng, q)
    )


async def refetch_event_details(db: AsyncSession) -> dict:
    """Re-fetch detail pages for all future events and reconcile stored fields.

    Single pass, mirrors geocode_pending. Candidates are every event with a
    ``url`` whose ``starts_at`` is in the future and that has not been synced
    within REFETCH_MIN_INTERVAL_DAYS — no missing-field filter (all future
    events are candidates) and no attempt cap. Ordered oldest-synced-first so a
    capped run prioritizes the least-recently-synced events. Returns a summary
    dict; the caller commits.
    """
    now = datetime.now(TALLINN_TZ)
    due_before = now - timedelta(days=REFETCH_MIN_INTERVAL_DAYS)

    candidates = (
        await db.scalars(
            select(Event)
            .where(
                Event.url.is_not(None),
                Event.starts_at > now,
                or_(
                    Event.detail_refetched_at.is_(None),
                    Event.detail_refetched_at < due_before,
                ),
            )
            .order_by(Event.detail_refetched_at.asc().nulls_first())
            .limit(REFETCH_MAX_PER_RUN)
        )
    ).all()

    summary = {
        "candidates": len(candidates),
        "fetched": 0,
        "address_changed": 0,
        "coords_changed": 0,
        "venue_changed": 0,
        "price_changed": 0,
        "unchanged": 0,
        "no_data": 0,
        "failed": 0,
        "flagged_explicit": 0,
    }
    if not candidates:
        return summary

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        for event in candidates:
            url = event.url
            assert url is not None  # guaranteed by the WHERE clause above
            try:
                response = await http_get(client, url)
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                # Don't bump detail_refetched_at on a fetch failure — a transient
                # error should be retried on the next run, not throttled out.
                summary["failed"] += 1
                log.warning("refetch failed url=%s: %s", url, exc)
                continue

            summary["fetched"] += 1
            soup = BeautifulSoup(response.text, "html.parser")
            location = extract_jsonld_event_location(soup)
            price_min, price_max, currency = extract_jsonld_event_offers(soup)

            detail_name = location.get("venue_name") if location else None
            detail_address = location.get("venue_address") if location else None
            detail_lat = location.get("lat") if location else None
            detail_lng = location.get("lng") if location else None

            parsed_anything = location is not None or any(
                v is not None for v in (price_min, price_max, currency)
            )
            if not parsed_anything:
                summary["no_data"] += 1
                _mark_synced(event, now)
                await asyncio.sleep(REFETCH_REQUEST_DELAY_SECONDS)
                continue

            changed = _reconcile(
                event,
                summary,
                detail_name=detail_name,
                detail_address=detail_address,
                detail_lat=detail_lat,
                detail_lng=detail_lng,
                price_min=price_min,
                price_max=price_max,
                currency=currency,
            )
            if not changed:
                summary["unchanged"] += 1

            _mark_synced(event, now)
            await asyncio.sleep(REFETCH_REQUEST_DELAY_SECONDS)

    return summary


def _mark_synced(event: Event, now: datetime) -> None:
    """Bump the throttle fields, run regardless of whether any value changed."""
    event.detail_refetch_count = (event.detail_refetch_count or 0) + 1
    event.detail_refetched_at = now


def _reconcile(
    event: Event,
    summary: dict,
    *,
    detail_name: object,
    detail_address: str | None,
    detail_lat: float | None,
    detail_lng: float | None,
    price_min: float | None,
    price_max: float | None,
    currency: str | None,
) -> bool:
    """Apply the reconciliation rules to one event in place. Returns True if any
    field was changed. Increments the matching ``summary`` counters."""
    changed = False

    # --- price: update each field on drift, fill on empty, never clobber with
    # nothing. Overrides the "ingest-set prices are authoritative" rule — a price
    # change at the source should win — but a no-offers refetch leaves stored prices.
    price_changed = False
    if price_min is not None and _price_differs(event.price_min, price_min):
        event.price_min = price_min  # type: ignore[assignment]
        price_changed = True
    if price_max is not None and _price_differs(event.price_max, price_max):
        event.price_max = price_max  # type: ignore[assignment]
        price_changed = True
    if currency is not None and event.currency != currency:
        event.currency = currency
        price_changed = True
    if price_changed:
        summary["price_changed"] += 1
        changed = True

    # --- venue_address + lat/lng: reconciled as a coupled unit, never field-
    # independently, so the two can't drift apart (see geocode.py coexistence).
    address_differs = (
        detail_address is not None and detail_address != event.venue_address
    )
    if address_differs:
        event.venue_address = detail_address
        summary["address_changed"] += 1
        changed = True
        if detail_lat is not None and detail_lng is not None:
            # Consistent triple straight from the source — beats Nominatim/sibling guess.
            if _coords_differ(event.lat, event.lng, detail_lat, detail_lng):
                summary["coords_changed"] += 1
            event.lat, event.lng = detail_lat, detail_lng
        elif event.lat is not None or event.lng is not None:
            # New address, no source coords — NULL the stale coords (derived from a
            # *different* address) so geocode_pending re-resolves them. Already-NULL
            # coords are left as-is (nothing changed, so don't count it).
            event.lat, event.lng = None, None
            summary["coords_changed"] += 1
    elif (
        detail_lat is not None
        and detail_lng is not None
        and _coords_differ(event.lat, event.lng, detail_lat, detail_lng)
    ):
        # Address absent/identical but source coords moved — direct geo, update only.
        event.lat, event.lng = detail_lat, detail_lng
        summary["coords_changed"] += 1
        changed = True

    # --- venue_name: take the JSON-LD location.name (already split from address).
    name = detail_name.strip() if isinstance(detail_name, str) else None
    name_changed = False
    if name:
        if _is_empty_venue_name(event.venue_name):
            # Fill / replace placeholder — accept any real name.
            if name != event.venue_name:
                event.venue_name = name[:VENUE_NAME_MAX_LEN]
                name_changed = True
        elif name != event.venue_name and not is_suspect_venue_name(name):
            # Clean stored name → only overwrite with a clean (non-suspect) detail
            # name; a glued/suspect name would undo extract_address_from_venue_name.
            event.venue_name = name[:VENUE_NAME_MAX_LEN]
            name_changed = True
    if name_changed:
        summary["venue_changed"] += 1
        changed = True
        # Content-safety layer 1 re-check: a venue_name change is a new write path
        # that can land on an already-published event, so re-run the explicit-keyword
        # prefilter over the same fields ingest checks (title/description/venue_name).
        # A newly-explicit published event is demoted to classified so the publish
        # gate (which excludes is_explicit) keeps it out of the public feed.
        if not event.is_explicit and is_explicit_text(
            event.title_orig, event.description_orig, event.venue_name
        ):
            event.is_explicit = True
            summary["flagged_explicit"] += 1
            if event.status == EVENT_STATUS_PUBLISHED:
                event.status = EVENT_STATUS_CLASSIFIED

    return changed
