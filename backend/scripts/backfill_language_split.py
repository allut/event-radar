"""One-off maintenance: backfill *_localized locale keys for events whose single
source page concatenates two languages in one blob (see app.ingestion.language_split).

Iterates all events, runs split_by_language against title_orig/description_orig/
important_info, and merges any newly-detected locale keys into the existing
title_localized/description_localized/important_info_localized JSONB — only
adding keys that are still missing, never overwriting a locale obtained from a
real per-locale page fetch.

Run from backend/ with the venv active:
    python scripts/backfill_language_split.py             # dry run
    python scripts/backfill_language_split.py --yes       # write to DB
    python scripts/backfill_language_split.py --yes --limit 50  # cap rows
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

# backend/ must be on sys.path so `from app.*` resolves regardless of CWD.
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from app.constants import BACKFILL_DEFAULT_LIMIT
from app.ingestion.language_split import split_by_language
from app.logging_config import configure_logging
from app.models.models import Event
from app.routers.utils import mask_db_url

configure_logging()
log = logging.getLogger(__name__)


def _split_updates(event: Event) -> dict[str, dict[str, str]]:
    """Return {field_name: newly-detected {locale: text}} for fields with a
    missing locale that split_by_language can fill. Empty dict if none apply."""
    updates: dict[str, dict[str, str]] = {}
    for field, orig in (
        ("title_localized", event.title_orig),
        ("description_localized", event.description_orig),
        ("important_info_localized", event.important_info),
    ):
        existing = getattr(event, field) or {}
        split = split_by_language(orig)
        new_keys = {loc: text for loc, text in split.items() if loc not in existing}
        if new_keys:
            updates[field] = new_keys
    return updates


async def main(confirm: bool, limit: int) -> None:
    from app.config import settings
    from app.db import AsyncSessionLocal

    print(f"DB: {mask_db_url(settings.DATABASE_URL)}")

    async with AsyncSessionLocal() as db:
        stmt = select(Event).order_by(Event.id).limit(limit)
        result = await db.execute(stmt)
        events = result.scalars().all()

    print(f"Scanning {len(events)} events for a bilingual-in-one-field split.")
    if not events:
        return

    candidates: list[tuple[int, dict[str, dict[str, str]]]] = []
    for ev in events:
        updates = _split_updates(ev)
        if updates:
            candidates.append((ev.id, updates))

    print(f"Found {len(candidates)} events with at least one new locale to fill.")
    if not candidates:
        return

    print("Sample (before write):")
    for event_id, updates in candidates[:5]:
        summary = {field: sorted(new.keys()) for field, new in updates.items()}
        print(f"  [{event_id}] +{summary}")

    if not confirm:
        print("\nDry run — pass --yes to write to DB.")
        return

    updated = 0
    async with AsyncSessionLocal() as db:
        for i, (event_id, _) in enumerate(candidates, 1):
            ev = await db.get(Event, event_id)
            if ev is None:
                continue
            updates = _split_updates(ev)
            if not updates:
                continue
            for field, new_keys in updates.items():
                merged = dict(getattr(ev, field) or {})
                merged.update(new_keys)
                setattr(ev, field, merged)
            updated += 1
            log.info("[%d/%d] event_id=%d -> %s", i, len(candidates), event_id, updates)

            if updated % 50 == 0:
                await db.commit()
                log.info("Committed %d updates so far.", updated)

        await db.commit()

    print(f"\nDone. updated={updated}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill *_localized locale keys split out of a single bilingual field."
    )
    parser.add_argument("--yes", action="store_true", help="Write results to DB.")
    parser.add_argument(
        "--limit",
        type=int,
        default=BACKFILL_DEFAULT_LIMIT,
        help=f"Max events to scan (default {BACKFILL_DEFAULT_LIMIT}).",
    )
    args = parser.parse_args()
    asyncio.run(main(confirm=args.yes, limit=args.limit))
