"""One-time backfill: publishers/event_sources.publisher_id for currently-
claimable events (#411). See app/ingestion/publisher_backfill.py for the
scoping rules (live re-query, published + not-yet-ended only).

Run from backend/ with the venv active:
    python scripts/backfill_publisher_ids.py            # dry run: shows target counts
    python scripts/backfill_publisher_ids.py --yes       # actually backfill
"""
import argparse
import asyncio
import sys
from pathlib import Path

# backend/ must be on sys.path so `from app.*` resolves regardless of CWD.
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import mask_db_url


async def main(confirm: bool) -> None:
    from app.config import settings
    from app.db import AsyncSessionLocal, engine
    from app.ingestion.publisher_backfill import backfill_publisher_ids

    print(f"DB: {mask_db_url(settings.DATABASE_URL)}")

    if not confirm:
        print("Dry run — pass --yes to backfill.")
        await engine.dispose()
        return

    async with AsyncSessionLocal() as db:
        results = await backfill_publisher_ids(db)
        await db.commit()

    print("Backfilled event_sources.publisher_id:")
    for slug, count in results.items():
        print(f"  {slug}: {count}")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill publisher_id for currently-claimable events."
    )
    parser.add_argument("--yes", action="store_true", help="Confirm backfill.")
    args = parser.parse_args()
    asyncio.run(main(confirm=args.yes))
