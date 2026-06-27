"""One-off maintenance: upgrade stored ECH (concert.ee) image URLs to full-res.

Rewrites events.image_url for concert.ee rows by stripping the WordPress
-WxH thumbnail suffix (e.g. ...-82x118.jpg -> ...jpg), so existing rows match
the full-resolution poster the ingest adapter now stores for new events. Reuses
full_res_concert_image() from the ingest adapter so the transform stays in one
place.

Run from backend/ with the venv active:
    python scripts/upgrade_ech_images.py            # dry run: shows affected rows
    python scripts/upgrade_ech_images.py --yes      # actually rewrite
"""
import argparse
import asyncio
import sys
from pathlib import Path

# backend/ must be on sys.path so `from app.*` resolves regardless of CWD.
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text

from app.ingestion.sources.html_listing import full_res_concert_image
from app.routers.utils import mask_db_url

_SELECT_SQL = text(
    "SELECT id, image_url FROM events "
    "WHERE image_url IS NOT NULL AND image_url ILIKE '%concert.ee%'"
)
_UPDATE_SQL = text("UPDATE events SET image_url = :new_url WHERE id = :id")

# Cap how many before/after pairs we print so a large table stays readable.
_PREVIEW_LIMIT = 20


async def main(confirm: bool) -> None:
    from app.config import settings
    from app.db import engine

    print(f"DB: {mask_db_url(settings.DATABASE_URL)}")
    print("Target: events.image_url for concert.ee rows\n")

    try:
        async with engine.connect() as conn:
            rows = (await conn.execute(_SELECT_SQL)).all()

        changes: list[tuple[int, str, str]] = []
        for row_id, old_url in rows:
            new_url = full_res_concert_image(old_url)
            # new_url is only None when old_url is None, which the WHERE clause
            # already excludes — the guard keeps the type honest and rules out
            # ever writing NULL into image_url.
            if new_url is not None and new_url != old_url:
                changes.append((row_id, old_url, new_url))

        print(f"concert.ee rows: {len(rows)}")
        print(f"Rows needing rewrite: {len(changes)}\n")

        for row_id, old_url, new_url in changes[:_PREVIEW_LIMIT]:
            print(f"  [{row_id}] {old_url}\n      -> {new_url}")
        if len(changes) > _PREVIEW_LIMIT:
            print(f"  ... and {len(changes) - _PREVIEW_LIMIT} more")

        if not changes:
            print("Nothing to upgrade.")
            return

        if not confirm:
            print("\nDry run — pass --yes to rewrite.")
            return

        print("\n** REWRITING image URLs **")
        async with engine.begin() as conn:
            for row_id, _old_url, new_url in changes:
                await conn.execute(_UPDATE_SQL, {"new_url": new_url, "id": row_id})

        print(f"\nDone. Rewrote {len(changes)} row(s).")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upgrade ECH image URLs to full-res.")
    parser.add_argument("--yes", action="store_true", help="Confirm the rewrite.")
    args = parser.parse_args()
    asyncio.run(main(confirm=args.yes))
