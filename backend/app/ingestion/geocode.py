"""Nominatim geocoding for events that have a venue_address but no lat/lng."""

import asyncio
import logging
import re

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    ESTONIAN_STREET_TYPE_ABBREV,
    GEOCODE_COUNTRY_SUFFIX,
    GEOCODE_COUNTY_RE,
    GEOCODE_FLOOR_RE,
    GEOCODE_MAX_PER_RUN,
    GEOCODE_REQUEST_DELAY_SECONDS,
    GEOCODE_UNIT_SUFFIX_RE,
    HTTP_TIMEOUT_SECONDS,
    NOMINATIM_BASE_URL,
    NOMINATIM_USER_AGENT,
)
from app.ingestion.base import http_get
from app.models.models import Event

log = logging.getLogger(__name__)

# Pre-compiled patterns built from constants — avoids re-compiling per call.
_STREET_TYPE_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in ESTONIAN_STREET_TYPE_ABBREV) + r")\b",
    re.IGNORECASE,
)
_UNIT_SUFFIX_RE = re.compile(GEOCODE_UNIT_SUFFIX_RE, re.IGNORECASE)
_FLOOR_RE = re.compile(GEOCODE_FLOOR_RE, re.IGNORECASE)
_COUNTY_RE = re.compile(GEOCODE_COUNTY_RE, re.IGNORECASE)


def normalize_address_for_geocoding(address: str) -> str:
    """Return a Nominatim-friendly version of a Fienta venue_address.

    Abbreviates Estonian street-type words, strips unit suffixes, floor notes,
    and county markers, then appends ", Estonia" to anchor country matching.
    The stored venue_address is never mutated — this is query-only.
    """
    result = address
    result = _FLOOR_RE.sub("", result)
    result = _COUNTY_RE.sub("", result)
    result = _UNIT_SUFFIX_RE.sub("", result)
    result = _STREET_TYPE_PATTERN.sub(
        lambda m: ESTONIAN_STREET_TYPE_ABBREV.get(m.group(0).lower(), m.group(0)),
        result,
    )
    result = re.sub(r"\s+", " ", result).strip().rstrip(",").strip()
    if not result.endswith(GEOCODE_COUNTRY_SUFFIX):
        result += GEOCODE_COUNTRY_SUFFIX
    return result


async def geocode_address(
    client: httpx.AsyncClient, address: str, original: str | None = None
) -> tuple[float, float] | None:
    """Look up an address via Nominatim, returning ``(lat, lng)`` or None if no match.

    ``address`` is the normalized query sent to Nominatim.
    ``original`` is the raw venue_address (used only in the no-match log line).
    """
    response = await http_get(
        client,
        NOMINATIM_BASE_URL,
        params={"q": address, "format": "json", "limit": 1},
        headers={"User-Agent": NOMINATIM_USER_AGENT},
    )
    try:
        results = response.json()
        if not results:
            log.warning(
                "geocode no match: query=%r original=%r",
                address,
                original or address,
            )
            return None
        return float(results[0]["lat"]), float(results[0]["lon"])
    except (KeyError, TypeError, ValueError):
        return None


async def geocode_pending(db: AsyncSession) -> dict:
    """Backfill lat/lng for events with a venue_address but no coordinates.

    Two queries total regardless of row count: one for pending events (capped at
    GEOCODE_MAX_PER_RUN), one to seed a normalized-query→coords cache from events
    already geocoded — avoids re-hitting Nominatim for venues we already know.
    The cache is keyed by the *normalized* query so format variants of one venue
    (e.g. "60a/9" vs "60a / 9") share a single Nominatim call.
    Remaining distinct addresses are geocoded serially with a delay between calls
    per Nominatim's usage policy (max 1 req/s).
    """
    pending = (
        await db.scalars(
            select(Event)
            .where(Event.venue_address.is_not(None), Event.lat.is_(None))
            .limit(GEOCODE_MAX_PER_RUN)
        )
    ).all()
    if not pending:
        return {"pending": 0, "geocoded": 0, "failed": 0}

    addresses = {event.venue_address for event in pending}
    cached_rows = (
        await db.execute(
            select(Event.venue_address, Event.lat, Event.lng).where(
                Event.venue_address.in_(addresses), Event.lat.is_not(None)
            )
        )
    ).all()
    # Seed cache by normalized query so format variants of the same venue hit once.
    cache: dict[str, tuple[float, float] | None] = {
        normalize_address_for_geocoding(address): (lat, lng)
        for address, lat, lng in cached_rows
    }

    geocoded = 0
    failed = 0
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        for event in pending:
            raw_address = event.venue_address
            assert raw_address is not None  # guaranteed by the WHERE clause above
            query = normalize_address_for_geocoding(raw_address)

            if query not in cache:
                try:
                    cache[query] = await geocode_address(client, query, original=raw_address)
                except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                    log.warning("geocode failed address=%s: %s", raw_address, exc)
                    cache[query] = None
                await asyncio.sleep(GEOCODE_REQUEST_DELAY_SECONDS)

            coords = cache[query]
            if coords is None:
                failed += 1
                continue
            event.lat, event.lng = coords
            geocoded += 1

    return {"pending": len(pending), "geocoded": geocoded, "failed": failed}
