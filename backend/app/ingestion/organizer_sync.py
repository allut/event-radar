import http
import logging
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, InterfaceError
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants.core import TALLINN_TZ
from app.constants.http import HTTP_TIMEOUT_SECONDS
from app.constants.ingestion import (
    FIENTA_CITY_FILTER,
    FIENTA_MIN_REQUEST_INTERVAL_SECONDS,
    FIENTA_ORGANIZER_CHECK_LIMIT,
    FIENTA_ORGANIZER_SCAN_MAX_PAGES,
    ORGANIZER_SYNC_DB_WRITE_ATTEMPTS,
    ORGANIZER_MIN_EVENTS_FOR_AUTO_ADD,
    PUBLISHER_NAME_MAX_LEN,
    PUBLISHER_STATUS_ACTIVE,
    PUBLISHER_STATUS_RETIRED,
    SOURCE_SLUG_FIENTA,
    STALE_ORGANIZER_RETIRE_DAYS,
)
from app.ingestion.http_client import AsyncRateLimiter, http_get
from app.models.ingestion import Source
from app.models.claims import Publisher

log = logging.getLogger(__name__)


async def _check_existing_organizers(
    client: httpx.AsyncClient,
    limiter: AsyncRateLimiter,
    current_ids: list[int],
    current_names: dict[str, str],
) -> tuple[set[int], set[int]]:
    """Probe each current organizer; return (stale_this_run, revived).

    A transient HTTP error leaves the organizer in neither set — its existing
    stale_since state carries forward, avoiding false stale/revival flips on a
    network blip.
    """
    stale_this_run: set[int] = set()
    revived: set[int] = set()
    for org_id in current_ids:
        await limiter.acquire()
        try:
            resp = await http_get(
                client,
                settings.FIENTA_BASE_URL,
                params={"organizer": org_id, "limit": FIENTA_ORGANIZER_CHECK_LIMIT},
            )
            events = resp.json().get("events", [])
            if not events:
                stale_this_run.add(org_id)
                log.info(
                    "organizer_sync: organizer %s (%s) returned 0 events — flagged stale",
                    org_id,
                    current_names.get(str(org_id)),
                )
            else:
                revived.add(org_id)
        except httpx.HTTPError as exc:
            log.warning(
                "organizer_sync: check failed for organizer=%s: %s", org_id, exc
            )
            if (
                isinstance(exc, httpx.HTTPStatusError)
                and exc.response.status_code == http.HTTPStatus.TOO_MANY_REQUESTS
            ):
                limiter.backoff(FIENTA_MIN_REQUEST_INTERVAL_SECONDS)
    return stale_this_run, revived


async def _fetch_city_scan(
    client: httpx.AsyncClient, limiter: AsyncRateLimiter
) -> list[dict[str, Any]]:
    """Fetch every page of the city-filtered listing (#634).

    Follows ``pagination.next_page_url``, rejecting a host other than
    ``FIENTA_BASE_URL``'s (SSRF guard, as in ``FientaAdapter.fetch_organizer``).
    Each page goes through ``limiter``; at most FIENTA_ORGANIZER_SCAN_MAX_PAGES
    requests are made, with a WARNING if pages remain.
    """
    base_host = urlparse(settings.FIENTA_BASE_URL).hostname
    events: list[dict[str, Any]] = []
    url = settings.FIENTA_BASE_URL
    params: dict[str, Any] | None = {"city": FIENTA_CITY_FILTER}
    for _ in range(FIENTA_ORGANIZER_SCAN_MAX_PAGES):
        await limiter.acquire()
        resp = await http_get(client, url, params=params)
        data = resp.json()
        events.extend(data.get("events", []))
        next_url = (data.get("pagination") or {}).get("next_page_url")
        if not next_url:
            return events
        url = next_url
        if urlparse(url).hostname != base_host:
            log.error(
                "organizer_sync: pagination.next_page_url host mismatch "
                "(SSRF guard), stopping scan"
            )
            return events
        params = None  # next_page_url already encodes every param
    log.warning(
        "organizer_sync: city=%s scan hit page budget=%d — results truncated",
        FIENTA_CITY_FILTER,
        FIENTA_ORGANIZER_SCAN_MAX_PAGES,
    )
    return events


async def _discover_new_organizers(
    client: httpx.AsyncClient,
    limiter: AsyncRateLimiter,
    current_ids: list[int],
    current_id_set: set[int],
    current_names: dict[str, str],
    retired_ids: set[int],
) -> list[tuple[int, str]]:
    """City-filtered scan; auto-add organizers with enough Tallinn events.

    Mutates current_ids/current_id_set/current_names/retired_ids in place
    (a retired organizer that resurfaces rejoins like any new one).
    Returns the (oid, name) pairs added.
    """
    added: list[tuple[int, str]] = []
    try:
        events = await _fetch_city_scan(client, limiter)
        org_counts: dict[int, tuple[int, str]] = {}
        for event in events:
            raw_oid = event.get("organizer_id")
            if raw_oid is None:
                continue
            try:
                oid = int(raw_oid)
            except (ValueError, TypeError):
                continue
            name = str(event.get("organizer_name", ""))[:PUBLISHER_NAME_MAX_LEN]
            count, _ = org_counts.get(oid, (0, name))
            org_counts[oid] = (count + 1, name)

        for oid, (count, name) in sorted(org_counts.items()):
            if oid in current_id_set or count < ORGANIZER_MIN_EVENTS_FOR_AUTO_ADD:
                continue
            current_ids.append(oid)
            current_id_set.add(oid)
            current_names[str(oid)] = name
            added.append((oid, name))
            if oid in retired_ids:
                retired_ids.discard(oid)
                log.info(
                    "organizer_sync: retired organizer %s (%s) revived — rejoined",
                    oid,
                    name,
                )
            log.info(
                "organizer_sync: auto-added organizer %s (%s) — %d events",
                oid,
                name,
                count,
            )
    except httpx.HTTPError as exc:
        log.warning("organizer_sync: discovery scan failed: %s", exc)
    return added


def _retire_stale(
    stale_since: dict[str, str],
    current_ids: list[int],
    current_id_set: set[int],
    current_names: dict[str, str],
    retired_ids: set[int],
    now: datetime,
) -> list[int]:
    """Retire any oid stale continuously for >= STALE_ORGANIZER_RETIRE_DAYS.

    Mutates stale_since/current_ids/current_id_set/retired_ids in place;
    returns the oids retired this run.
    """
    retired_now: list[int] = []
    retire_cutoff = now - timedelta(days=STALE_ORGANIZER_RETIRE_DAYS)
    for oid_str, since_iso in list(stale_since.items()):
        since = datetime.fromisoformat(since_iso)
        if since <= retire_cutoff:
            oid = int(oid_str)
            retired_ids.add(oid)
            retired_now.append(oid)
            stale_since.pop(oid_str, None)
            log.info(
                "organizer_sync: retired organizer %s (%s) — stale since %s",
                oid,
                current_names.get(oid_str),
                since_iso,
            )
    if retired_now:
        retired_now_set = set(retired_now)
        current_ids[:] = [oid for oid in current_ids if oid not in retired_now_set]
        current_id_set.difference_update(retired_now_set)
    return retired_now


async def _sync_publishers(
    db: AsyncSession,
    source: Source,
    current_ids: list[int],
    current_names: dict[str, str],
    retired_ids: set[int],
) -> None:
    """Mirror publishers from organizer_ids/organizer_names/retired_organizer_ids
    (#409/#411) — a read mirror only, never the other way around; the JSONB
    lists on Source.config stay the live ingestion filter (see module
    docstring). One bulk SELECT plus in-memory upserts, independent of how
    many organizers changed this run (batch-job rule).
    """
    all_oids = set(current_ids) | retired_ids
    if not all_oids:
        return
    external_ids = [str(oid) for oid in all_oids]
    existing_by_external_id = {
        p.external_id: p
        for p in (
            await db.execute(
                select(Publisher).where(
                    Publisher.source_id == source.id,
                    Publisher.external_id.in_(external_ids),
                )
            )
        )
        .scalars()
        .all()
    }
    for oid in all_oids:
        external_id = str(oid)
        name = current_names.get(external_id, external_id)[:PUBLISHER_NAME_MAX_LEN]
        status = (
            PUBLISHER_STATUS_RETIRED if oid in retired_ids else PUBLISHER_STATUS_ACTIVE
        )
        publisher = existing_by_external_id.get(external_id)
        if publisher is None:
            db.add(
                Publisher(
                    source_id=source.id,
                    external_id=external_id,
                    name=name,
                    status=status,
                )
            )
        else:
            publisher.name = name
            publisher.status = status
    await db.flush()


def _is_connection_failure(exc: DBAPIError) -> bool:
    return exc.connection_invalidated or isinstance(exc, InterfaceError)


async def _persist_sync(
    db: AsyncSession,
    config_updates: dict,
    current_ids: list[int],
    current_names: dict[str, str],
    retired_ids: set[int],
) -> bool:
    """Write the run's result on a fresh transaction; False when the source vanished.

    Re-reads the source so keys this job doesn't own (a concurrent admin edit
    during the HTTP phase) survive; only ``config_updates`` overwrite.
    """
    source = await db.scalar(
        select(Source)
        .where(Source.slug == SOURCE_SLUG_FIENTA)
        .execution_options(populate_existing=True)
    )
    if not source:
        log.warning("organizer_sync: fienta source vanished before write")
        return False
    source.config = {**(source.config or {}), **config_updates}
    flag_modified(source, "config")
    await _sync_publishers(db, source, current_ids, current_names, retired_ids)
    return True


async def sync_fienta_organizers(db: AsyncSession) -> dict:
    """Check active organizers, discover new ones, retire long-dead ones, update Source.config.

    Lifecycle: an organizer that returns 0 events is flagged stale (skipped by
    the next hourly ingest, still re-probed weekly here so a revival is
    detected). Once an organizer has been continuously stale for
    STALE_ORGANIZER_RETIRE_DAYS, it is retired — dropped out of organizer_ids
    entirely into retired_organizer_ids, so seeding (app/seeds.py) never
    resurrects it from the hardcoded settings floor. A retired organizer that
    resurfaces in the discovery scan (>= ORGANIZER_MIN_EVENTS_FOR_AUTO_ADD
    Tallinn events) rejoins organizer_ids like any newly-discovered one.

    Three phases: read the config, then roll back so no connection sits idle
    in a transaction across the ~2 min HTTP phase (#530), then write on a
    fresh pre-pinged connection, retried once if the server dropped it.

    Caller is responsible for committing the session after this returns.
    """
    source = await db.scalar(select(Source).where(Source.slug == SOURCE_SLUG_FIENTA))
    if not source:
        log.warning("organizer_sync: fienta source not found")
        return {}

    config = dict(source.config or {})
    current_ids: list[int] = [int(x) for x in config.get("organizer_ids", [])]
    current_names: dict[str, str] = dict(config.get("organizer_names", {}))
    current_id_set: set[int] = set(current_ids)
    retired_ids: set[int] = set(int(x) for x in config.get("retired_organizer_ids", []))
    # stale_since: oid (str key, JSONB) -> ISO timestamp of first consecutive stale probe.
    stale_since: dict[str, str] = dict(config.get("stale_since", {}))

    # Release the connection before the HTTP phase; config is already copied out.
    await db.rollback()

    now = datetime.now(tz=TALLINN_TZ)

    # Shared with fienta.py's ingest pacing: proactively spaces every request to
    # this same upstream instead of firing one per organizer back-to-back, which
    # was tripping Fienta's rate limit on accounts with many organizers.
    limiter = AsyncRateLimiter(FIENTA_MIN_REQUEST_INTERVAL_SECONDS)
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        stale_this_run, revived = await _check_existing_organizers(
            client, limiter, current_ids, current_names
        )
        added = await _discover_new_organizers(
            client, limiter, current_ids, current_id_set, current_names, retired_ids
        )

    # New stale oids get a first-seen timestamp; revived oids are cleared.
    # Errored oids keep whatever prior state they had.
    for oid in stale_this_run:
        stale_since.setdefault(str(oid), now.isoformat())
    for oid in revived:
        stale_since.pop(str(oid), None)

    retired_now = _retire_stale(
        stale_since, current_ids, current_id_set, current_names, retired_ids, now
    )

    # stale_organizer_ids = currently stale, not yet retired (still polled next
    # week so a revival is detectable; skipped by hourly ingest, see fienta.py).
    stale_organizer_ids = sorted(int(x) for x in stale_since)

    # Always persist last_sync; organizer lists ride along.
    config_updates = {
        "organizer_ids": current_ids,
        "organizer_names": current_names,
        "last_sync": now.isoformat(),
        "stale_organizer_ids": stale_organizer_ids,
        "stale_since": stale_since,
        "retired_organizer_ids": sorted(retired_ids),
    }

    for attempt in range(1, ORGANIZER_SYNC_DB_WRITE_ATTEMPTS + 1):
        try:
            if not await _persist_sync(
                db, config_updates, current_ids, current_names, retired_ids
            ):
                return {}
            break
        except DBAPIError as exc:
            if (
                not _is_connection_failure(exc)
                or attempt == ORGANIZER_SYNC_DB_WRITE_ATTEMPTS
            ):
                raise
            log.warning(
                "organizer_sync: DB connection lost on write (attempt %d) — retrying: %s",
                attempt,
                exc,
            )
            await db.rollback()

    log.info(
        "organizer_sync: done — total=%d added=%d stale=%d retired=%d",
        len(current_ids),
        len(added),
        len(stale_organizer_ids),
        len(retired_now),
    )
    return {
        "added": added,
        "stale": stale_organizer_ids,
        "retired": retired_now,
    }
