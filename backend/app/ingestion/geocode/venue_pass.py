"""Geocode pending organizer-saved Venues (#173, #179).

Venues are organizer-created (not ingested), so the volume is far below
Event's — no donor cache or sibling-copy machinery here, just a serial
Nominatim resolve mirroring Event's retry-cooldown pattern, but keyed on
Venue's own ``geocode_attempted_at`` column (a separate cooldown clock from
Event's). No inline/synchronous geocoding happens on venue create/edit
(app/routers/organizer_venues.py) — this periodic pass is the only
resolution path.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    GEOCODE_COMMIT_INTERVAL_SECONDS,
    GEOCODE_MAX_PER_RUN,
    GEOCODE_REQUEST_DELAY_SECONDS,
    GEOCODE_RETRY_INTERVAL_DAYS,
    HTTP_TIMEOUT_SECONDS,
)
from app.ingestion.geocode.nominatim import (
    geocode_address,
    normalize_address_for_geocoding,
)
from app.models.models import Venue

log = logging.getLogger(__name__)


async def geocode_pending_venues(db: AsyncSession, now: datetime) -> tuple[int, int]:
    """Resolve lat/lng for saved venues with an address but no coordinates.

    Excludes soft-deleted venues and, like the Event pass, excludes addresses
    that failed within the last GEOCODE_RETRY_INTERVAL_DAYS. A transient HTTP
    failure does NOT start the retry cooldown — only a definitive
    no-match/bbox-reject does, mirroring the Event Nominatim pass. Returns
    (geocoded, failed); caller commits.
    """
    due_before = now - timedelta(days=GEOCODE_RETRY_INTERVAL_DAYS)
    pending = (
        await db.scalars(
            select(Venue)
            .where(
                Venue.address.is_not(None),
                Venue.lat.is_(None),
                Venue.deleted_at.is_(None),
                or_(
                    Venue.geocode_attempted_at.is_(None),
                    Venue.geocode_attempted_at < due_before,
                ),
            )
            .order_by(Venue.geocode_attempted_at.asc().nulls_first())
            .limit(GEOCODE_MAX_PER_RUN)
        )
    ).all()
    if not pending:
        return 0, 0

    geocoded = 0
    failed = 0
    cache: dict[str, tuple[float, float] | None] = {}
    transient_failure_queries: set[str] = set()
    last_commit = time.monotonic()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        for venue in pending:
            raw_address = venue.address
            assert raw_address is not None  # guaranteed by the pending query
            query = normalize_address_for_geocoding(raw_address)

            if query not in cache:
                try:
                    cache[query] = await geocode_address(
                        client, query, original=raw_address
                    )
                except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                    log.warning("venue geocode failed address=%s: %s", raw_address, exc)
                    cache[query] = None
                    transient_failure_queries.add(query)
                await asyncio.sleep(GEOCODE_REQUEST_DELAY_SECONDS)

            coords = cache[query]
            if coords is None:
                failed += 1
                if query not in transient_failure_queries:
                    venue.geocode_attempted_at = now
            else:
                venue.lat, venue.lng = coords
                venue.geocode_attempted_at = now
                geocoded += 1
            if time.monotonic() - last_commit >= GEOCODE_COMMIT_INTERVAL_SECONDS:
                await db.commit()
                last_commit = time.monotonic()

    if geocoded:
        log.info("geocoded %d venue(s)", geocoded)
    return geocoded, failed
