"""One-off cleanup (#641): clear `image_url` (and its pin) on events where a
claim edit pinned a non-Cloudinary host. Idempotent.

Run from backend/ with the venv active:
    python scripts/clear_foreign_claim_images.py          # dry run: rolls back
    python scripts/clear_foreign_claim_images.py --yes    # clear
"""
import argparse
import asyncio
import sys
from pathlib import Path

# backend/ must be on sys.path so `from app.*` resolves regardless of CWD.
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db import mask_db_url


async def main(confirm: bool) -> None:
    from app.claims.image_cleanup import clear_foreign_pinned_images
    from app.config import settings
    from app.db import AsyncSessionLocal, engine

    print(f"DB: {mask_db_url(settings.DATABASE_URL)}")
    async with AsyncSessionLocal() as db:
        cleared = await clear_foreign_pinned_images(db)
        if confirm:
            await db.commit()
            print(f"Cleared {cleared} events.")
        else:
            await db.rollback()
            print(f"Dry run: {cleared} events would be cleared. Pass --yes.")
    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Clear claimant-pinned non-Cloudinary images.")
    parser.add_argument("--yes", action="store_true", help="Confirm and clear.")
    args = parser.parse_args()
    asyncio.run(main(confirm=args.yes))
