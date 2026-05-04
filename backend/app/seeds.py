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
        "organizer_ids": [3349, 1946, 15, 2111, 17595, 1088, 2704, 8403, 8412, 12106],
        "organizer_names": {
            "3349": "Kanuti Gildi SAAL",
            "1946": "Fotografiska Tallinn",
            "15": "Von Krahli Teater",
            "2111": "Kai kunstikeskus",
            "17595": "Paavli Kultuurivabrik",
            "1088": "Tallinn Fringe Festival",
            "2704": "Kellerteater",
            "8403": "MTÜ Uus Teater",
            "8412": "EKSPEDITSIOON",
            "12106": "Must Kast",
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
