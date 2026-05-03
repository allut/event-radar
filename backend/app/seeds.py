from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Source

# Placeholder organizer IDs — replace with real Fienta organizer IDs before going live.
# Find each venue's ID from their Fienta organizer profile URL.
_FIENTA_SOURCE = {
    "slug": "fienta",
    "kind": "api",
    "enabled": True,
    "config": {
        "base_url": "https://fienta.com/api/v1/public/events",
        "organizer_ids": [1001, 1002, 1003, 1004, 1005, 1006, 1007, 1008],
        "organizer_names": {
            "1001": "Sveta Baar",
            "1002": "HALL",
            "1003": "Tallinn Music Week",
            "1004": "Telliskivi Loomelinnak",
            "1005": "Kino Sõprus",
            "1006": "Rost",
            "1007": "Noblessner",
            "1008": "Kanuti Gildi SAAL",
        },
    },
}


async def seed_sources(db: AsyncSession) -> None:
    existing = await db.scalar(
        select(Source).where(Source.slug == _FIENTA_SOURCE["slug"])
    )
    if existing:
        return
    db.add(Source(**_FIENTA_SOURCE))
    await db.flush()
