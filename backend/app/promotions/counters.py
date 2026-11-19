"""Anonymous per-day delivery counters for Promotions (#606).

Counts live in a module-level dict keyed (promotion id, Tallinn day, column)
and reach ``promotion_daily_stats`` as one bulk upsert every
``PROMOTION_COUNTER_FLUSH_SECONDS`` and on shutdown. This relies on the
single-process topology: a crash loses at most a minute of counts.

No viewer identifier is ever written to the database, and nothing here feeds
ranking, the persona or ``user_event_feedback``. The ``?ref=`` opens count once
per client a day, so the set that dedups them holds ``client_key()`` in memory
for the current Tallinn day only.
"""

import logging
from collections import Counter
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.log_events import LOG_EVENT_PROMOTION_REF_SEEN_FULL
from app.constants.promotions import (
    PROMOTION_COUNTER_COLUMNS,
    PROMOTION_REF_SEEN_MAX_ENTRIES,
    PROMOTION_STATUS_PAID,
)
from app.models.promotions import Promotion, PromotionDailyStat
from app.promotions.windows import now_tallinn, tallinn_today

log = logging.getLogger(__name__)

_pending: Counter[tuple[int, date, str]] = Counter()
# day -> (client_key, promotion id, column) already counted that day. Only
# today's entry is kept; a new day drops the old one.
_ref_seen: dict[date, set[tuple[str, int, str]]] = {}
# Days whose set filled up and already logged it, so the warning fires once.
_ref_seen_full_logged: set[date] = set()


def bump(promotion_id: int, day: date, column: str) -> None:
    """Count one event. Synchronous, so a request never waits on the database."""
    if column not in PROMOTION_COUNTER_COLUMNS:
        raise ValueError(column)
    _pending[(promotion_id, day, column)] += 1


def first_ref_hit(client: str, promotion_id: int, day: date, column: str) -> bool:
    """True the first time ``client`` opens this Promotion's ``column`` on
    ``day``. A full set refuses new clients rather than evicting: eviction
    would let enough rotating addresses re-count forever."""
    seen = _ref_seen.get(day)
    if seen is None:
        _ref_seen.clear()
        _ref_seen_full_logged.clear()
        seen = _ref_seen[day] = set()
    key = (client, promotion_id, column)
    if key in seen:
        return False
    if len(seen) >= PROMOTION_REF_SEEN_MAX_ENTRIES:
        if day not in _ref_seen_full_logged:
            _ref_seen_full_logged.add(day)
            log.warning(
                "promotion ref dedup set full; opens stop counting until midnight",
                extra={"event": LOG_EVENT_PROMOTION_REF_SEEN_FULL},
            )
        return False
    seen.add(key)
    return True


def reset() -> None:
    _pending.clear()
    _ref_seen.clear()
    _ref_seen_full_logged.clear()


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


async def record_ref_hit(
    db: AsyncSession, event_id: int, column: str, client: str | None = None
) -> None:
    """Count ``column`` for the event's Promotion when one is live today. With
    ``client``, only that client's first hit of the day counts."""
    today = tallinn_today(now_tallinn())
    promotion_id = await live_promotion_id(db, event_id, today)
    if promotion_id is None:
        return
    if client is not None and not first_ref_hit(client, promotion_id, today, column):
        return
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
