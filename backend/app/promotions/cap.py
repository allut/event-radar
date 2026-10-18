"""Cap accounting: how many Promotions hold each Tallinn day, and the lock
that makes a check-and-insert atomic."""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.promotions import (
    PROMOTION_CAP_LOCK_KEY,
    PROMOTION_CAP_STRIP_DAYS,
    PROMOTION_HOLDING_STATUSES,
    PROMOTION_LIVE_CAP,
    PROMOTION_STATUS_PAID,
)
from app.models.models import Promotion
from app.promotions.windows import window_dates


@dataclass(frozen=True)
class CapDay:
    day: date
    reserved: int  # unpaid + paid Promotions whose window holds this day
    paid: int
    live: int  # paid Promotions running on this day (today only; later days are 0)

    @property
    def unpaid(self) -> int:
        return self.reserved - self.paid

    def as_dict(self) -> dict:
        return {
            "date": self.day.isoformat(),
            "reserved": self.reserved,
            "paid": self.paid,
            "unpaid": self.unpaid,
            "live": self.live,
            "cap": PROMOTION_LIVE_CAP,
            "free": max(PROMOTION_LIVE_CAP - self.reserved, 0),
        }


async def lock_cap(db: AsyncSession) -> None:
    """Take the transaction-scoped cap lock. Concurrent grants queue here, so
    the second one counts the first one's committed row. Released on commit
    or rollback; call it before the cap check and keep the insert in the same
    transaction."""
    await db.execute(select(func.pg_advisory_xact_lock(PROMOTION_CAP_LOCK_KEY)))


async def cap_days(
    db: AsyncSession,
    start: date,
    end: date,
    today: date,
    exclude_promotion_id: int | None = None,
) -> list[CapDay]:
    """Reserved, paid and live counts for each day in [start, end].
    `exclude_promotion_id` leaves one Promotion out, so an edit is checked
    against the others rather than against its own current window."""
    query = select(Promotion.status, Promotion.start_date, Promotion.end_date).where(
        Promotion.status.in_(PROMOTION_HOLDING_STATUSES),
        Promotion.start_date <= end,
        Promotion.end_date >= start,
    )
    if exclude_promotion_id is not None:
        query = query.where(Promotion.id != exclude_promotion_id)
    rows = (await db.execute(query)).all()
    days = window_dates(start, end)
    reserved = dict.fromkeys(days, 0)
    paid = dict.fromkeys(days, 0)
    for status, p_start, p_end in rows:
        for day in days:
            if p_start <= day <= p_end:
                reserved[day] += 1
                if status == PROMOTION_STATUS_PAID:
                    paid[day] += 1
    return [
        CapDay(day, reserved[day], paid[day], paid[day] if day == today else 0)
        for day in days
    ]


async def full_days(
    db: AsyncSession,
    start: date,
    end: date,
    today: date,
    exclude_promotion_id: int | None = None,
) -> list[date]:
    """Days in [start, end] already at the cap (one more would exceed it)."""
    days = await cap_days(db, start, end, today, exclude_promotion_id)
    return [c.day for c in days if c.reserved >= PROMOTION_LIVE_CAP]


async def cap_strip(db: AsyncSession, today: date) -> list[CapDay]:
    return await cap_days(db, today, today + timedelta(days=PROMOTION_CAP_STRIP_DAYS - 1), today)
