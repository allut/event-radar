"""Nominatim geocoding for events that have a venue_address but no lat/lng."""

import asyncio
import logging

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    GEOCODE_MAX_PER_RUN,
    GEOCODE_REQUEST_DELAY_SECONDS,
    HTTP_TIMEOUT_SECONDS,
    NOMINATIM_BASE_URL,
    NOMINATIM_USER_AGENT,
)
from app.ingestion.base import http_get
from app.models.models import Event

log = logging.getLogger(__name__)


async def geocode_address(
    client: httpx.AsyncClient, address: str
) -> tuple[float, float] | None:
    """Look up an address via Nominatim, returning ``(lat, lng)`` or None if no match."""
    response = await http_get(
        client,
        NOMINATIM_BASE_URL,
        params={"q": address, "format": "json", "limit": 1},
        headers={"User-Agent": NOMINATIM_USER_AGENT},
    )
    try:
        results = response.json()
        if not results:
            return None
        return float(results[0]["lat"]), float(results[0]["lon"])
    except (KeyError, TypeError, ValueError):
        return None


async def geocode_pending(db: AsyncSession) -> dict:
    """Backfill lat/lng for events with a venue_address but no coordinates.

    Two queries total regardless of row count: one for pending events (capped at
    GEOCODE_MAX_PER_RUN), one to seed an address→coords cache from events already
    geocoded with the same address — avoids re-hitting Nominatim for venues we
    already know. Remaining distinct addresses are geocoded serially with a delay
    between calls per Nominatim's usage policy (max 1 req/s).
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
    cache: dict[str, tuple[float, float] | None] = {
        address: (lat, lng) for address, lat, lng in cached_rows
    }

    geocoded = 0
    failed = 0
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        for event in pending:
            address = event.venue_address
            assert address is not None  # guaranteed by the WHERE clause above

            if address not in cache:
                try:
                    cache[address] = await geocode_address(client, address)
                except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                    log.warning("geocode failed address=%s: %s", address, exc)
                    cache[address] = None
                await asyncio.sleep(GEOCODE_REQUEST_DELAY_SECONDS)

            coords = cache[address]
            if coords is None:
                failed += 1
                continue
            event.lat, event.lng = coords
            geocoded += 1

    return {"pending": len(pending), "geocoded": geocoded, "failed": failed}
