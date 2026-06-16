"""One-off maintenance: wipe all event data and reset IDs to 1.

Run from backend/ with the venv active:
    python scripts/reset_events.py            # dry run: shows target + counts
    python scripts/reset_events.py --yes      # actually truncate
"""
import argparse
import asyncio
import re
import sys
from pathlib import Path

# backend/ must be on sys.path so `from app.*` resolves regardless of CWD.
sys.path.insert(0, str(Path(__file__).parent.parent))

import sqlalchemy as sa
from sqlalchemy import text

WIPE_TABLES = (
    "events",
    "raw_events",
    "event_sources",
    "event_classifications",
    "user_event_feedback",
    "user_event_scores",
    "daily_feeds",
    "ingestion_runs",
    "llm_calls",
    "raw_inbound_emails",
)

_TRUNCATE_SQL = text(
    "TRUNCATE TABLE "
    + ", ".join(WIPE_TABLES)
    + " RESTART IDENTITY CASCADE"
)

_RESET_SOURCES_SQL = text(
    "UPDATE sources SET last_run_at = NULL, last_status = NULL"
)


async def _counts(conn) -> dict[str, int]:  # type: ignore[no-untyped-def]
    result: dict[str, int] = {}
    for table in WIPE_TABLES:
        stmt = sa.select(sa.func.count()).select_from(sa.table(table))
        row = await conn.execute(stmt)
        result[table] = row.scalar_one()
    return result


def _masked_url(url: str) -> str:
    return re.sub(r":[^@/]+@", ":***@", url)


async def main(confirm: bool) -> None:
    from app.config import settings
    from app.db import engine

    print(f"DB: {_masked_url(settings.DATABASE_URL)}")
    print(f"Tables: {', '.join(WIPE_TABLES)}\n")

    try:
        async with engine.connect() as conn:
            before = await _counts(conn)

        print("Row counts BEFORE:")
        for table, count in before.items():
            print(f"  {table}: {count}")

        if not confirm:
            print("\nDry run — pass --yes to truncate.")
            return

        print("\n** TRUNCATING — cannot be undone **")

        async with engine.begin() as conn:
            await conn.execute(_TRUNCATE_SQL)
            await conn.execute(_RESET_SOURCES_SQL)

        async with engine.connect() as conn:
            after = await _counts(conn)

        print("\nRow counts AFTER:")
        for table, count in after.items():
            status = "OK" if count == 0 else "NONZERO — check manually"
            print(f"  {table}: {count}  {status}")

        all_zero = all(v == 0 for v in after.values())
        print("\nReset complete." if all_zero else "\nWARNING: some tables non-zero.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Wipe event data and reset IDs.")
    parser.add_argument("--yes", action="store_true", help="Confirm destructive wipe.")
    args = parser.parse_args()
    asyncio.run(main(confirm=args.yes))
