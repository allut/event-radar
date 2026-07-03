"""One-off maintenance: fix event price extraction bugs (2026-07-03 price audit).

Two independent passes:

1. Fienta events — recompute price_min/price_max/currency/has_free_tier from the
   stored raw_events.payload["price_from_string"] using the fixed
   parse_price_from_string() (listing-only baseline). The previously-stored
   raw_events.payload["_detail"] price fields were produced by the old, buggy
   extract_jsonld_event_offers() (it collapsed a sold-out event's placeholder
   offer to a fake €0 price, and took min() across offers including €0
   member/companion tiers) and must NOT be reused here. The next scheduled
   detail-refetch pass (app/ingestion/refetch.py, now using the fixed
   extractor) reconciles future events' detail-page paid bounds on its own
   cadence, so this script only needs to repair the listing-only floor.

2. Piletilevi events — the adapter sets no price at ingest and no price_hint,
   so every price on these rows is an LLM guess, frequently a verbatim echo of
   the old prompt's JSON example ("price_min": 10, "price_max": 20). Nulls
   price_min/price_max/currency/has_free_tier, then re-runs classify_event()
   per event against the fixed prompt (which now includes a full-text price
   digest and rejects prices not backed by a literal amount in the source
   text).

Run from backend/ with the venv active:
    python scripts/fix_prices.py            # dry run: shows planned changes
    python scripts/fix_prices.py --yes      # apply
"""
import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import sqlalchemy as sa

from app.ingestion.base import parse_price_from_string
from app.llm.classifier import classify_event
from app.models.models import Event, EventClassification, EventSource, RawEvent, Source
from app.routers.utils import mask_db_url

FIENTA_SLUG = "fienta"
PILETILEVI_SLUG = "piletilevi"
COMMIT_INTERVAL_SECONDS = 10.0


async def fix_fienta(db, confirm: bool) -> None:
    rows = (
        await db.execute(
            sa.select(
                Event.id,
                Event.price_min,
                Event.price_max,
                Event.currency,
                Event.has_free_tier,
                RawEvent.payload["price_from_string"].astext.label("pfs"),
            )
            .select_from(Event)
            .join(EventSource, EventSource.event_id == Event.id)
            .join(Source, Source.id == EventSource.source_id)
            .join(
                RawEvent,
                sa.and_(
                    RawEvent.source_id == EventSource.source_id,
                    RawEvent.external_id == EventSource.external_id,
                ),
            )
            .where(Source.slug == FIENTA_SLUG)
            .order_by(Event.id)
        )
    ).all()

    print(f"Fienta events scanned: {len(rows)}")
    changed: list[tuple] = []
    for row in rows:
        new_min, new_max, new_currency, new_free_tier = parse_price_from_string(row.pfs)
        old_min = float(row.price_min) if row.price_min is not None else None
        old_max = float(row.price_max) if row.price_max is not None else None
        if (
            old_min != new_min
            or old_max != new_max
            or row.currency != new_currency
            or bool(row.has_free_tier) != new_free_tier
        ):
            changed.append((row, old_min, old_max, new_min, new_max, new_currency, new_free_tier))

    print(f"Fienta events needing a price fix: {len(changed)}\n")
    for row, old_min, old_max, new_min, new_max, new_currency, new_free_tier in changed[:50]:
        print(
            f"  {row.id} | {old_min}/{old_max} -> {new_min}/{new_max} {new_currency} "
            f"free_tier={new_free_tier} | pfs={row.pfs!r}"
        )
    if len(changed) > 50:
        print(f"  ... and {len(changed) - 50} more")

    if not confirm:
        print("\nDry run — pass --yes to apply Fienta fixes.")
        return

    last_commit = time.monotonic()
    for row, _old_min, _old_max, new_min, new_max, new_currency, new_free_tier in changed:
        await db.execute(
            sa.update(Event)
            .where(Event.id == row.id)
            .values(
                price_min=new_min,
                price_max=new_max,
                currency=new_currency,
                has_free_tier=new_free_tier,
            )
        )
        if time.monotonic() - last_commit >= COMMIT_INTERVAL_SECONDS:
            await db.commit()
            last_commit = time.monotonic()
    await db.commit()
    print(f"Applied Fienta price fixes: {len(changed)}")


async def fix_piletilevi(db, confirm: bool) -> None:
    event_ids = (
        await db.scalars(
            sa.select(Event.id)
            .select_from(Event)
            .join(EventSource, EventSource.event_id == Event.id)
            .join(Source, Source.id == EventSource.source_id)
            .where(Source.slug == PILETILEVI_SLUG, Event.price_min.is_not(None))
            .order_by(Event.id)
        )
    ).all()

    print(f"\nPiletilevi events with an LLM-guessed price: {len(event_ids)}")
    if not confirm:
        print("Dry run — pass --yes to null prices and reclassify via the fixed prompt.")
        return

    await db.execute(
        sa.update(Event)
        .where(Event.id.in_(event_ids))
        .values(price_min=None, price_max=None, currency=None, has_free_tier=False)
    )
    await db.commit()

    succeeded = 0
    failed = 0
    last_commit = time.monotonic()
    for i, event_id in enumerate(event_ids, start=1):
        event = await db.get(Event, event_id)
        if event is None:
            continue
        existing = await db.scalar(
            sa.select(EventClassification).where(
                EventClassification.event_id == event_id
            )
        )
        ok = await classify_event(event, db, existing_classification=existing, prefetched=True)
        if ok:
            succeeded += 1
        else:
            failed += 1
        if time.monotonic() - last_commit >= COMMIT_INTERVAL_SECONDS:
            await db.commit()
            last_commit = time.monotonic()
        if i % 50 == 0:
            print(f"  reclassified {i}/{len(event_ids)} (ok={succeeded} failed={failed})")
    await db.commit()
    print(f"Piletilevi reclassify done: succeeded={succeeded} failed={failed}")


async def main(confirm: bool) -> None:
    from app.config import settings
    from app.db import AsyncSessionLocal, engine

    print(f"DB: {mask_db_url(settings.DATABASE_URL)}\n")
    try:
        async with AsyncSessionLocal() as db:
            await fix_fienta(db, confirm)
            await fix_piletilevi(db, confirm)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Fix Fienta listing prices and reclassify Piletilevi LLM-guessed prices."
    )
    parser.add_argument("--yes", action="store_true", help="Apply the fixes.")
    args = parser.parse_args()
    asyncio.run(main(confirm=args.yes))
