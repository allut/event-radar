import logging
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import (
    FIENTA_CITY_FILTER,
    FIENTA_ORGANIZER_CHECK_LIMIT,
    FIENTA_ORGANIZER_SCAN_LIMIT,
    HTTP_TIMEOUT_SECONDS,
    ORGANIZER_MIN_EVENTS_FOR_AUTO_ADD,
    ORGANIZER_NAME_MAX_LEN,
    SOURCE_SLUG_FIENTA,
    TALLINN_TZ,
)
from app.ingestion.base import _http_get
from app.models.models import Source

log = logging.getLogger(__name__)


async def sync_fienta_organizers(db: AsyncSession) -> dict:
    """Check active organizers, discover new ones, update Source.config.

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
    # Carry forward stale IDs from previous runs so transient errors don't silently clear them.
    prev_stale: set[int] = set(int(x) for x in config.get("stale_organizer_ids", []))

    stale_ids: set[int] = set()
    added: list[tuple[int, str]] = []

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        # Step 1 — check each current organizer is still returning events
        for org_id in current_ids:
            try:
                resp = await _http_get(
                    client,
                    settings.FIENTA_BASE_URL,
                    params={"organizer": org_id, "limit": FIENTA_ORGANIZER_CHECK_LIMIT},
                )
                events = resp.json().get("events", [])
                if not events:
                    stale_ids.add(org_id)
                    log.info(
                        "organizer_sync: organizer %s (%s) returned 0 events — flagged stale",
                        org_id,
                        current_names.get(str(org_id)),
                    )
            except httpx.HTTPError as exc:
                log.warning(
                    "organizer_sync: check failed for organizer=%s: %s", org_id, exc
                )

        # Step 2 — discover new organizers via city filter scan
        try:
            resp = await _http_get(
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
                if (
                    oid not in current_id_set
                    and count >= ORGANIZER_MIN_EVENTS_FOR_AUTO_ADD
                ):
                    current_ids.append(oid)
                    current_id_set.add(oid)
                    current_names[str(oid)] = name
                    added.append((oid, name))
                    log.info(
                        "organizer_sync: auto-added organizer %s (%s) — %d events",
                        oid,
                        name,
                        count,
                    )
        except httpx.HTTPError as exc:
            log.warning("organizer_sync: discovery scan failed: %s", exc)

    # Merge with previous stale set so HTTP-error runs don't silently clear prior stale flags.
    merged_stale: list[int] = sorted(stale_ids | prev_stale)

    # Step 3 — always persist last_sync; update organizer lists only if changed
    source.config = {
        **config,
        "organizer_ids": current_ids,
        "organizer_names": current_names,
        "last_sync": datetime.now(tz=TALLINN_TZ).isoformat(),
        "stale_organizer_ids": merged_stale,  # retained for human review; not auto-removed
    }
    flag_modified(source, "config")

    log.info(
        "organizer_sync: done — total=%d added=%d stale=%d",
        len(current_ids),
        len(added),
        len(merged_stale),
    )
    return {"added": added, "stale": merged_stale}
