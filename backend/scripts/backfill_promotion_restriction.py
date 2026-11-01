"""One-off launch backfill (#612): assess `events.promotion_restriction` for
every owned, not-ended event. Idempotent: events already assessed are skipped,
and one the LLM could not answer is retried on the next run.

Run from backend/ with the venv active:
    python scripts/backfill_promotion_restriction.py          # dry run: counts only
    python scripts/backfill_promotion_restriction.py --yes    # assess
"""
import argparse
import asyncio
import sys
from pathlib import Path

# backend/ must be on sys.path so `from app.*` resolves regardless of CWD.
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import mask_db_url


async def main(confirm: bool) -> None:
    from sqlalchemy import func, select

    from app.config import settings
    from app.db import AsyncSessionLocal, engine
    from app.events.queries import event_not_ended_filter
    from app.models.events import Event
    from app.promotions.restriction import backfill_restrictions
    from app.promotions.windows import now_tallinn

    print(f"DB: {mask_db_url(settings.DATABASE_URL)}")
    now = now_tallinn()
    async with AsyncSessionLocal() as db:
        if not confirm:
            unassessed = await db.scalar(
                select(func.count())
                .select_from(Event)
                .where(Event.promotion_restriction.is_(None), event_not_ended_filter(now))
            )
            print(f"Dry run: {unassessed} not-ended unassessed events (owned subset assessed). Pass --yes.")
        else:
            summary = await backfill_restrictions(db, now)
            await db.commit()
            print(f"Assessed {summary['assessed']} of {summary['owned']} owned events "
                  f"({summary['candidates']} candidates).")
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Assess promotion_restriction for owned events.")
    parser.add_argument("--yes", action="store_true", help="Confirm and assess.")
    args = parser.parse_args()
    asyncio.run(main(confirm=args.yes))
