import http
import logging
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import (
    FIENTA_CITY_FILTER,
    FIENTA_MIN_REQUEST_INTERVAL_SECONDS,
    FIENTA_ORGANIZER_CHECK_LIMIT,
    FIENTA_ORGANIZER_SCAN_LIMIT,
    HTTP_TIMEOUT_SECONDS,
    ORGANIZER_MIN_EVENTS_FOR_AUTO_ADD,
    ORGANIZER_NAME_MAX_LEN,
    PUBLISHER_STATUS_ACTIVE,
    PUBLISHER_STATUS_RETIRED,
    SOURCE_SLUG_FIENTA,
    STALE_ORGANIZER_RETIRE_DAYS,
    TALLINN_TZ,
)
from app.ingestion.http_client import AsyncRateLimiter, http_get
from app.models.models import Publisher, Source

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
    await limiter.acquire()
    try:
        resp = await http_get(
            client,
            settings.FIENTA_BASE_URL,
            params={
                "city": FIENTA_CITY_FILTER,
                "limit": FIENTA_ORGANIZER_SCAN_LIMIT,
            },
        )
        events = resp.json().get("events", [])
        if len(events) == FIENTA_ORGANIZER_SCAN_LIMIT:
            log.warning(
                "organizer_sync: city=%s scan hit limit=%d — results may be truncated",
                FIENTA_CITY_FILTER,
                FIENTA_ORGANIZER_SCAN_LIMIT,
            )
        org_counts: dict[int, tuple[int, str]] = {}
        for event in events:
            raw_oid = event.get("organizer_id")
            if raw_oid is None:
                continue
            try:
                oid = int(raw_oid)
            except (ValueError, TypeError):
                continue
            name = str(event.get("organizer_name", ""))[:ORGANIZER_NAME_MAX_LEN]
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
    many organizers changed this run (Code Quality Rules' "Batch jobs").
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
        name = current_names.get(external_id, external_id)[:ORGANIZER_NAME_MAX_LEN]
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

    Caller is responsible for committing the session after this returns.
    """
    source = await db.scalar(select(Source).where(Source.slug == SOURCE_SLUG_FIENTA))
    if not source:
        log.warning("organizer_sync: fienta source not found")
        return {}

    config = source.config or {}
    current_ids: list[int] = [int(x) for x in config.get("organizer_ids", [])]
    current_names: dict[str, str] = dict(config.get("organizer_names", {}))
    current_id_set: set[int] = set(current_ids)
    retired_ids: set[int] = set(int(x) for x in config.get("retired_organizer_ids", []))
    # stale_since: oid (str key, JSONB) -> ISO timestamp of first consecutive stale probe.
    stale_since: dict[str, str] = dict(config.get("stale_since", {}))

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
    source.config = {
        **config,
        "organizer_ids": current_ids,
        "organizer_names": current_names,
        "last_sync": now.isoformat(),
        "stale_organizer_ids": stale_organizer_ids,
        "stale_since": stale_since,
        "retired_organizer_ids": sorted(retired_ids),
    }
    flag_modified(source, "config")

    await _sync_publishers(db, source, current_ids, current_names, retired_ids)

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
