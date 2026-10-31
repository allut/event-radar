"""The digest Sponsored slot (#611): which stored Daily 5 slots the digest carries.

The digest never picks a Promotion. It reads the one stored for the user
today in ``daily_sponsored_slots`` (#607) and runs the gate again, so a
Promotion that stopped qualifying since the nightly build is dropped rather
than swapped. The caller passes only users who consented and have a full set
of picks.

Reads are bulk with a fixed query count, however many users are passed.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.events import Event
from app.models.promotions import DailySponsoredSlot, Promotion
from app.promotions.daily5 import daily5_reason
from app.promotions.fill import evaluate_gate, gate_closed_reason


@dataclass(frozen=True)
class DigestSlot:
    """What the digest renders for one user: the Promotion, the advertiser it
    names and the gated event."""

    promotion_id: int
    advertiser: str
    event: Event


async def load_digest_slots(
    db: AsyncSession, user_ids: Sequence[int], now: datetime
) -> dict[int, DigestSlot]:
    """Per user, today's stored slot when its Promotion still passes the gate."""
    if not user_ids or gate_closed_reason(None) is not None:
        return {}
    stored = (
        await db.execute(
            select(DailySponsoredSlot.user_id, DailySponsoredSlot.promotion_id).where(
                DailySponsoredSlot.user_id.in_(list(user_ids)),
                DailySponsoredSlot.slot_date == now.date(),
                DailySponsoredSlot.promotion_id.is_not(None),
            )
        )
    ).all()
    if not stored:
        return {}
    promotions = (
        await db.scalars(
            select(Promotion)
            .where(Promotion.id.in_({promotion_id for _, promotion_id in stored}))
            .order_by(Promotion.id)
        )
    ).all()
    passing = {
        r.promotion.id: DigestSlot(r.promotion.id, r.promotion.advertiser_legal_name, r.event)
        for r in await evaluate_gate(db, promotions, now)
        if daily5_reason(r, now) is None
    }
    return {
        user_id: passing[promotion_id]
        for user_id, promotion_id in stored
        if promotion_id in passing
    }
