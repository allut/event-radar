"""Anonymous per-day delivery counters for Promotions (#606).

Counts live in a module-level dict keyed (promotion id, Tallinn day, column)
and reach ``promotion_daily_stats`` as one bulk upsert every
``PROMOTION_COUNTER_FLUSH_SECONDS`` and on shutdown. This relies on the
single-process topology (CLAUDE.md): a crash loses at most a minute of counts.

No viewer identifier is ever recorded, and nothing here feeds ranking, the
persona or ``user_event_feedback``.
"""

from collections import Counter
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.promotions import (
    PROMOTION_COUNTER_COLUMNS,
    PROMOTION_STATUS_PAID,
)
from app.models.models import Promotion, PromotionDailyStat
from app.promotions.windows import now_tallinn, tallinn_today

_pending: Counter[tuple[int, date, str]] = Counter()


def bump(promotion_id: int, day: date, column: str) -> None:
    """Count one event. Synchronous, so a request never waits on the database."""
    if column not in PROMOTION_COUNTER_COLUMNS:
        raise ValueError(column)
    _pending[(promotion_id, day, column)] += 1


def reset() -> None:
    _pending.clear()


async def live_promotion_id(db: AsyncSession, event_id: int, today: date) -> int | None:
    """The paid Promotion whose window covers ``today`` for this event, if any."""
    return await db.scalar(
        select(Promotion.id)
        .where(
            Promotion.event_id == event_id,
            Promotion.status == PROMOTION_STATUS_PAID,
            Promotion.start_date <= today,
            Promotion.end_date >= today,
        )
        .order_by(Promotion.id)
        .limit(1)
    )


async def record_ref_hit(db: AsyncSession, event_id: int, column: str) -> None:
    """Count ``column`` for the event's Promotion when one is live today."""
    today = tallinn_today(now_tallinn())
    promotion_id = await live_promotion_id(db, event_id, today)
    if promotion_id is not None:
        bump(promotion_id, today, column)


async def flush(db: AsyncSession) -> dict:
    """Write the pending counts as one bulk upsert that adds to the stored
    totals. The caller commits. A failed write puts the counts back."""
    taken = Counter(_pending)
    _pending.clear()
    if not taken:
        return {"rows": 0}
    grouped: dict[tuple[int, date], dict[str, int]] = {}
    for (promotion_id, day, column), n in taken.items():
        grouped.setdefault((promotion_id, day), dict.fromkeys(PROMOTION_COUNTER_COLUMNS, 0))[
            column
        ] += n
    rows = [
        {"promotion_id": promotion_id, "day": day, **cols}
        for (promotion_id, day), cols in grouped.items()
    ]
    insert = pg_insert(PromotionDailyStat).values(rows)
    stmt = insert.on_conflict_do_update(
        constraint="uq_promotion_daily_stats_promotion_day",
        set_={
            col: getattr(PromotionDailyStat, col) + getattr(insert.excluded, col)
            for col in PROMOTION_COUNTER_COLUMNS
        },
    )
    try:
        await db.execute(stmt)
    except Exception:
        _pending.update(taken)
        raise
    return {"rows": len(rows)}
