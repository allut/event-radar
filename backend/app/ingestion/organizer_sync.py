import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.models import Source

TALLINN_TZ = ZoneInfo("Europe/Tallinn")
MIN_EVENTS_TO_ADD = 3   # organizer must appear ≥3 times in city=Tallinn results to be auto-added
_NAME_MAX_LEN = 200
log = logging.getLogger(__name__)


async def sync_fienta_organizers(db: AsyncSession) -> dict:
    """Check active organizers, discover new ones, update Source.config.

    Caller is responsible for committing the session after this returns.
    """
    source = await db.scalar(select(Source).where(Source.slug == "fienta"))
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

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Step 1 — check each current organizer is still returning events
        for org_id in current_ids:
            try:
                resp = await client.get(settings.FIENTA_BASE_URL, params={"organizer": org_id, "limit": 5})
                resp.raise_for_status()
                events = resp.json().get("events", [])
                if not events:
                    stale_ids.add(org_id)
                    log.info(
                        "organizer_sync: organizer %s (%s) returned 0 events — flagged stale",
                        org_id, current_names.get(str(org_id)),
                    )
            except httpx.HTTPError as exc:
                log.warning("organizer_sync: check failed for organizer=%s: %s", org_id, exc)

        # Step 2 — discover new Tallinn organizers from city=Tallinn scan
        try:
            resp = await client.get(settings.FIENTA_BASE_URL, params={"city": "Tallinn", "limit": 1000})
            resp.raise_for_status()
            events = resp.json().get("events", [])
            if len(events) == 1000:
                log.warning("organizer_sync: city=Tallinn scan hit limit=1000 — results may be truncated")
            org_counts: dict[int, tuple[int, str]] = {}
            for event in events:
                raw_oid = event.get("organizer_id")
                if raw_oid is None:
                    continue
                try:
                    oid = int(raw_oid)
                except (ValueError, TypeError):
                    continue
                name = str(event.get("organizer_name", ""))[:_NAME_MAX_LEN]
                count, _ = org_counts.get(oid, (0, name))
                org_counts[oid] = (count + 1, name)

            for oid, (count, name) in sorted(org_counts.items()):
                if oid not in current_id_set and count >= MIN_EVENTS_TO_ADD:
                    current_ids.append(oid)
                    current_id_set.add(oid)
                    current_names[str(oid)] = name
                    added.append((oid, name))
                    log.info("organizer_sync: auto-added organizer %s (%s) — %d events", oid, name, count)
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
        len(current_ids), len(added), len(merged_stale),
    )
    return {"added": added, "stale": merged_stale}
