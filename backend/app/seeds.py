from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.models import Source


def _fienta_source() -> dict:
    return {
        "slug": "fienta",
        "kind": "api",
        "enabled": True,
        "config": {
            "base_url": settings.FIENTA_BASE_URL,
            "organizer_ids": settings.FIENTA_ORGANIZER_IDS,
            "organizer_names": settings.FIENTA_ORGANIZER_NAMES,
        },
    }


async def seed_sources(db: AsyncSession) -> None:
    source = _fienta_source()
    existing = await db.scalar(
        select(Source).where(Source.slug == source["slug"])
    )
    if existing:
        desired = source["config"]
        db_cfg = existing.config or {}
        # Union organizer IDs so auto-discovered IDs from organizer_sync are preserved.
        # DB names take precedence — organizer_sync may have refreshed them.
        merged_ids = sorted(set(desired["organizer_ids"]) | set(db_cfg.get("organizer_ids", [])))
        merged_names = {**desired["organizer_names"], **db_cfg.get("organizer_names", {})}
        merged = {
            **db_cfg,
            "base_url": desired["base_url"],
            "organizer_ids": merged_ids,
            "organizer_names": merged_names,
        }
        if merged != db_cfg:
            existing.config = merged
            await db.flush()
        return
    db.add(Source(**source))
    await db.flush()
