"""One-off cleanup for #641: a claim edit used to pin any https `image_url`.
Clear the ones a claimant pinned that are not our own Cloudinary uploads, and
drop the pin, so those events fall back to the scraped image or none."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.claims.pinning import apply_pins, pin_key
from app.ingestion.http_client import own_cloudinary_url
from app.models.models import Event


async def clear_foreign_pinned_images(db: AsyncSession) -> int:
    """Returns how many events were cleared. Scraped values are never touched:
    only an event whose ``image_url`` is pinned is considered."""
    key = pin_key("image_url")
    rows = (
        (await db.execute(select(Event).where(Event.pinned_fields.contains([key]))))
        .scalars()
        .all()
    )
    cleared = 0
    for event in rows:
        # No value: the claimant deliberately cleared the image, so keep the pin.
        if not event.image_url or own_cloudinary_url(event.image_url) is not None:
            continue
        event.image_url = None
        event.pinned_fields = apply_pins(event.pinned_fields, pin=set(), unpin={key})
        cleared += 1
    return cleared
