"""One-off maintenance: flag sexually-explicit/kink listings and demote them from published.

Retroactively applies the is_explicit filter (porn, striptease, escort, and
kink/BDSM/fetish content) to rows ingested before EXPLICIT_KEYWORDS covered
that genre: sets events.is_explicit via the Layer-1 keyword rules
(is_explicit_text) plus a hardcoded audit list, then demotes any published
row carrying the flag back to 'classified' (the publish gate blocks it from
re-promoting).

Run from backend/ with the venv active:
    python scripts/demote_explicit_events.py            # dry run: shows matches
    python scripts/demote_explicit_events.py --yes      # apply flag + demote
"""
import argparse
import asyncio
import sys
from pathlib import Path

# backend/ must be on sys.path so `from app.*` resolves regardless of CWD.
sys.path.insert(0, str(Path(__file__).parent.parent))

import sqlalchemy as sa

from app.constants import EVENT_STATUS_CLASSIFIED, EVENT_STATUS_PUBLISHED
from app.ingestion.base import is_explicit_text
from app.models.models import Event
from app.routers.utils import mask_db_url

# Explicit/kink events the keyword rules cannot catch, from the 2026-07-03 DB
# audit of the Kultus Club series: nuanced "educational"/"panel"/"party"
# framings the LLM classifier (mistral) passed over despite explicit sexual
# content. Keyed by slug, not numeric id — slugs are deterministic (title +
# date + external_id hash, see _make_slug) and survive a reset_events.py
# TRUNCATE ... RESTART IDENTITY, while raw ids would silently re-attach to
# unrelated freshly-ingested events.
#
# Deliberately excludes "cuddle-party-by-thalia-hel-20260705-7bd4470f" (558)
# — self-described as nonsexual touch, not flagged.
KNOWN_EXPLICIT_SLUGS: frozenset[str] = frozenset(
    {
        "kultus-femdom-party-crossdress-sissyfication-20260725-ce84a683",
        "butt-stuff-workshop-by-thalia-hel-20260726-1fd766da",
        "pride-and-pain-kinky-girl-summer-18-20260711-4a591fce",
        "sacred-bodies-panel-discussion-20260717-46832b89",
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
                        Event.description_orig,
                        Event.venue_name,
                        Event.is_explicit,
                    ).order_by(Event.id)
                )
            ).all()

            matched: list[tuple] = []
            for row in rows:
                by_rule = is_explicit_text(
                    row.title_orig, row.description_orig, row.venue_name
                )
                by_slug = row.slug in KNOWN_EXPLICIT_SLUGS
                if by_rule or by_slug:
                    matched.append((row, "rule" if by_rule else "slug-list"))

            print(f"Events scanned: {len(rows)}")
            print(f"Explicit matches: {len(matched)}\n")
            for row, how in matched:
                flag = "" if row.is_explicit else " (new flag)"
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
                    .values(is_explicit=True)
                )
                demoted = await db.execute(
                    sa.update(Event)
                    .where(
                        Event.status == EVENT_STATUS_PUBLISHED,
                        Event.is_explicit.is_(True),
                    )
                    .values(status=EVENT_STATUS_CLASSIFIED)
                )
                await db.commit()
                print(f"\nFlagged is_explicit: {flagged.rowcount}")
                print(f"Demoted published -> classified: {demoted.rowcount}")

            remaining = await db.scalar(
                sa.select(sa.func.count())
                .select_from(Event)
                .where(
                    Event.status == EVENT_STATUS_PUBLISHED,
                    Event.is_explicit.is_(True),
                )
            )
            status = "OK" if remaining == 0 else "NONZERO — check manually"
            print(f"Published explicit events AFTER: {remaining}  {status}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Flag sexually-explicit/kink listings and demote them from published."
    )
    parser.add_argument("--yes", action="store_true", help="Apply flag + demote.")
    args = parser.parse_args()
    asyncio.run(main(confirm=args.yes))
