"""One-off maintenance: re-classify Piletilevi events whose price_min was set to a
booking/service fee instead of the real ticket price.

Selects events from piletilevi.ee whose important_info matches a fee keyword, resets
price_min/price_max/currency to NULL so classify_event re-derives them from the
fixed prompt (which strips fee clauses), then re-classifies each event in batches.

Run from backend/ with the venv active:
    python scripts/fix_fee_prices.py            # dry run: shows affected row count + sample
    python scripts/fix_fee_prices.py --yes      # actually reclassify
"""
import argparse
import asyncio
import sys
from pathlib import Path

# backend/ must be on sys.path so `from app.*` resolves regardless of CWD.
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, text, update

from app.ingestion.base import strip_fee_amounts
from app.routers.utils import mask_db_url

_SAMPLE_LIMIT = 10
_BATCH_SIZE = 10


def _has_fee_keyword(important_info: str | None) -> bool:
    """True when strip_fee_amounts would change the text (i.e. a fee clause is present)."""
    if not important_info:
        return False
    return strip_fee_amounts(important_info) != important_info


async def main(confirm: bool) -> None:
    from app.config import settings
    from app.db import engine
    from app.llm.classifier import classify_event
    from app.models.models import Event, EventClassification

    print(f"DB: {mask_db_url(settings.DATABASE_URL)}")
    print("Target: piletilevi.ee events with a fee keyword in important_info\n")

    async with engine.connect() as conn:
        piletilevi_id_row = await conn.execute(
            text("SELECT id FROM sources WHERE slug = 'piletilevi'")
        )
        row = piletilevi_id_row.fetchone()

    if row is None:
        print("Source slug 'piletilevi' not found in sources table — nothing to do.")
        await engine.dispose()
        return

    piletilevi_source_id: int = row[0]

    # Load all piletilevi events that still carry a non-NULL important_info.
    # The fee filter runs in Python so we can reuse strip_fee_amounts.
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT e.id, e.price_min, e.price_max, e.important_info "
                "FROM events e "
                "JOIN event_sources es ON es.event_id = e.id "
                "WHERE es.source_id = :sid "
                "AND e.important_info IS NOT NULL"
            ),
            {"sid": piletilevi_source_id},
        )
        all_rows = result.fetchall()

    affected = [r for r in all_rows if _has_fee_keyword(r[3])]

    print(f"Piletilevi events with important_info: {len(all_rows)}")
    print(f"Events with fee keyword in important_info: {len(affected)}\n")

    if not affected:
        print("Nothing to fix.")
        await engine.dispose()
        return

    print(f"Sample (up to {_SAMPLE_LIMIT}):")
    for event_id, price_min, price_max, info in affected[:_SAMPLE_LIMIT]:
        snippet = (info or "")[:120].replace("\n", " ")
        print(f"  [{event_id}] price_min={price_min} price_max={price_max} | {snippet}")
    if len(affected) > _SAMPLE_LIMIT:
        print(f"  ... and {len(affected) - _SAMPLE_LIMIT} more")

    if not confirm:
        print("\nDry run — pass --yes to reclassify.")
        await engine.dispose()
        return

    print("\n** RECLASSIFYING **")

    from app.db import AsyncSessionLocal

    succeeded = failed = 0
    event_ids = [r[0] for r in affected]

    for batch_start in range(0, len(event_ids), _BATCH_SIZE):
        batch_ids = event_ids[batch_start : batch_start + _BATCH_SIZE]

        async with AsyncSessionLocal() as db:
            # Reset price fields so classify_event's guard (price_min is None) triggers.
            await db.execute(
                update(Event)  # type: ignore[arg-type]
                .where(Event.id.in_(batch_ids))
                .values(price_min=None, price_max=None, currency=None)
            )
            await db.commit()

            events_result = await db.scalars(
                select(Event).where(Event.id.in_(batch_ids))
            )
            events = list(events_result.all())

            # Prefetch existing classifications to avoid N+1.
            cls_result = await db.scalars(
                select(EventClassification).where(
                    EventClassification.event_id.in_(batch_ids)
                )
            )
            cls_by_event: dict[int, EventClassification] = {
                c.event_id: c for c in cls_result.all()
            }

            for event in events:
                ok = await classify_event(
                    event,
                    db,
                    existing_classification=cls_by_event.get(event.id),
                    prefetched=True,
                )
                if ok:
                    succeeded += 1
                else:
                    failed += 1

            await db.commit()

        print(
            f"  Batch {batch_start // _BATCH_SIZE + 1}: "
            f"{len(batch_ids)} events — {succeeded} ok, {failed} failed so far"
        )

    print(f"\nDone. Reclassified {succeeded} event(s), {failed} failed.")
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Re-classify Piletilevi events with mis-extracted fee prices."
    )
    parser.add_argument("--yes", action="store_true", help="Confirm the reclassification.")
    args = parser.parse_args()
    asyncio.run(main(confirm=args.yes))
