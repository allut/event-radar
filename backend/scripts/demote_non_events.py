"""One-off maintenance: flag non-event listings and demote them from published.

Retroactively applies the is_non_event filter (gift cards, vouchers, merch,
donations, online webinars/recordings) to rows ingested before the flag
existed: sets events.is_non_event via the Layer-1 keyword rules
(is_non_event_text) plus a hardcoded audit list, then demotes any published
row carrying the flag back to 'classified' (the publish gate blocks it from
re-promoting).

Run from backend/ with the venv active:
    python scripts/demote_non_events.py            # dry run: shows matches
    python scripts/demote_non_events.py --yes      # apply flag + demote
"""
import argparse
import asyncio
import sys
from pathlib import Path

# backend/ must be on sys.path so `from app.*` resolves regardless of CWD.
sys.path.insert(0, str(Path(__file__).parent.parent))

import sqlalchemy as sa

from app.constants import EVENT_STATUS_CLASSIFIED, EVENT_STATUS_PUBLISHED
from app.ingestion.content_filters import is_non_event_text
from app.models.models import Event
from app.routers.utils import mask_db_url

# Non-events the keyword/venue rules cannot catch, from the 2026-07-03 DB audit:
# a book, MamaClub recordings with no keyword/venue signal, an ongoing enrollment,
# online courses/guides (venue NULL), a VIP card, a donation, and an open-ended
# coaching booking. Keyed by slug, not numeric id — slugs are deterministic
# (title + date + external_id hash, see _make_slug) and survive a
# reset_events.py TRUNCATE ... RESTART IDENTITY, while raw ids would silently
# re-attach to unrelated freshly-ingested events.
KNOWN_NON_EVENT_SLUGS: frozenset[str] = frozenset(
    {
        "s-ltumatu-tantsu-raamat-20251208-726c09d8",
        "-20210117-29ec8066",
        "-20210117-319b2600",
        "-20210117-5c72c994",
        "3-5-12-20250301-b1743e3e",
        "-20240523-9c089da8",
        "5-20250717-309ac58b",
        "-20251113-1742f092",
        "gant-club-vip-cub-card-20260401-10f61b46",
        "gant-club-donate-20260408-154fef03",
        "book-your-somatic-coaching-and-bodywork-sessions-20260318-bf51e766",
    }
)


async def main(confirm: bool) -> None:
    from app.config import settings
    from app.db import AsyncSessionLocal, engine

    print(f"DB: {mask_db_url(settings.DATABASE_URL)}\n")

    try:
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    sa.select(
                        Event.id,
                        Event.slug,
                        Event.status,
                        Event.title_orig,
                        Event.venue_name,
                        Event.is_non_event,
                    ).order_by(Event.id)
                )
            ).all()

            matched: list[tuple] = []
            for row in rows:
                by_rule = is_non_event_text(row.title_orig, row.venue_name)
                by_slug = row.slug in KNOWN_NON_EVENT_SLUGS
                if by_rule or by_slug:
                    matched.append((row, "rule" if by_rule else "slug-list"))

            print(f"Events scanned: {len(rows)}")
            print(f"Non-event matches: {len(matched)}\n")
            for row, how in matched:
                flag = "" if row.is_non_event else " (new flag)"
                print(
                    f"  {row.id} | {row.status} | {how}{flag} | "
                    f"{(row.title_orig or '')[:70]} | venue={row.venue_name}"
                )

            matched_ids = [row.id for row, _ in matched]
            published_ids = [
                row.id for row, _ in matched if row.status == EVENT_STATUS_PUBLISHED
            ]
            print(f"\nCurrently published among matches: {len(published_ids)}")

            if not confirm:
                print("\nDry run — pass --yes to flag + demote.")
                return

            if matched_ids:
                flagged = await db.execute(
                    sa.update(Event)
                    .where(Event.id.in_(matched_ids))
                    .values(is_non_event=True)
                )
                demoted = await db.execute(
                    sa.update(Event)
                    .where(
                        Event.status == EVENT_STATUS_PUBLISHED,
                        Event.is_non_event.is_(True),
                    )
                    .values(status=EVENT_STATUS_CLASSIFIED)
                )
                await db.commit()
                print(f"\nFlagged is_non_event: {flagged.rowcount}")
                print(f"Demoted published -> classified: {demoted.rowcount}")

            remaining = await db.scalar(
                sa.select(sa.func.count())
                .select_from(Event)
                .where(
                    Event.status == EVENT_STATUS_PUBLISHED,
                    Event.is_non_event.is_(True),
                )
            )
            status = "OK" if remaining == 0 else "NONZERO — check manually"
            print(f"Published non-events AFTER: {remaining}  {status}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Flag non-event listings and demote them from published."
    )
    parser.add_argument("--yes", action="store_true", help="Apply flag + demote.")
    args = parser.parse_args()
    asyncio.run(main(confirm=args.yes))
