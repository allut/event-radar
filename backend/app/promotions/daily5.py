"""The Daily 5 Sponsored slot (#607): the nightly pick, the stored slot, the
mid-day swap, the gate-outcome rows and Daily 5 reach.

The slot is a separate card after a full five and never changes the five. It
lives in ``daily_sponsored_slots``, apart from ``daily_feeds``.

Eligibility is the shared fill gate (``fill.evaluate_gate``) plus the Daily 5
context: the event starts within the builder's lookahead window and is never
matched to the five's categories. On top of that, per user: the five's events,
dedup groups and series are never repeated, the viewer's own signals only
exclude (``fill.viewer_excluded_promotions``), and a Promotion stored for the
user within the last ``PROMOTION_DAILY5_COOLDOWN_DAYS`` days is skipped. The
cooldown never relaxes: when nothing survives, the slot collapses. The pick is
``fill.rotation_pick`` seeded with user id + Tallinn date.

Every read here is bulk with a fixed query count, however many users and
Promotions there are.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.promotions import (
    PROMOTION_DAILY5_COOLDOWN_DAYS,
    PROMOTION_GATE_OUTCOME_PAUSED,
    PROMOTION_GATE_OUTCOME_SHOWN,
    PROMOTION_NOT_SHOWING_OUTSIDE_DAILY5_WINDOW,
    PROMOTION_STAT_DAILY5_PLACED,
    PROMOTION_STATUS_PAID,
)
from app.constants.ranking import DAILY_5_COUNT, DAILY_5_LOOKAHEAD_DAYS
from app.models.events import Event
from app.models.promotions import DailySponsoredSlot, Promotion, PromotionDailyStat
from app.promotions import counters
from app.promotions.fill import (
    GateResult,
    VisibleSet,
    evaluate_gate,
    explore_seed,
    gate_closed_reason,
    rotation_pick,
    surviving,
    viewer_excluded_promotions,
)


def daily5_reason(result: GateResult, now: datetime) -> str | None:
    """The gate reason, or the Daily 5 context's own when the event starts
    after the builder's lookahead window."""
    if result.reason is not None:
        return result.reason
    if result.event.starts_at > now + timedelta(days=DAILY_5_LOOKAHEAD_DAYS):
        return PROMOTION_NOT_SHOWING_OUTSIDE_DAILY5_WINDOW
    return None


async def load_live_promotions(db: AsyncSession, today: date) -> list[Promotion]:
    """Paid Promotions whose window covers today, ordered by id (the cap keeps
    this to a handful)."""
    return list(
        (
            await db.scalars(
                select(Promotion)
                .where(
                    Promotion.status == PROMOTION_STATUS_PAID,
                    Promotion.start_date <= today,
                    Promotion.end_date >= today,
                )
                .order_by(Promotion.id)
            )
        ).all()
    )


async def _cooldown(db: AsyncSession, user_ids: Sequence[int], today: date) -> dict[int, set[int]]:
    """Per user, the Promotions stored for them within the cooldown window."""
    out: dict[int, set[int]] = {uid: set() for uid in user_ids}
    if not user_ids:
        return out
    rows = (
        await db.execute(
            select(DailySponsoredSlot.user_id, DailySponsoredSlot.promotion_id).where(
                DailySponsoredSlot.user_id.in_(list(user_ids)),
                DailySponsoredSlot.slot_date
                >= today - timedelta(days=PROMOTION_DAILY5_COOLDOWN_DAYS),
                DailySponsoredSlot.slot_date < today,
                DailySponsoredSlot.promotion_id.is_not(None),
            )
        )
    ).all()
    for uid, pid in rows:
        out[uid].add(pid)
    return out


async def _visible_by_user(
    db: AsyncSession, five_by_user: dict[int, list[int]]
) -> dict[int, VisibleSet]:
    """Each user's five as a VisibleSet, from one events query."""
    all_ids = sorted({eid for ids in five_by_user.values() for eid in ids})
    rows: dict[int, tuple] = {}
    if all_ids:
        for r in (
            await db.execute(
                select(Event.id, Event.dedup_group_id, Event.series_key).where(
                    Event.id.in_(all_ids)
                )
            )
        ).all():
            rows[r[0]] = tuple(r)
    out: dict[int, VisibleSet] = {}
    for uid, ids in five_by_user.items():
        picked = [rows[i] for i in ids if i in rows]
        out[uid] = VisibleSet(
            frozenset(r[0] for r in picked),
            frozenset(r[1] if r[1] is not None else r[0] for r in picked),
            frozenset(r[2] for r in picked if r[2] is not None),
        )
    return out


@dataclass
class Daily5Run:
    """One nightly build's Daily 5 slot state: the live Promotions' gate
    results, loaded once and reused for every page of users."""

    today: date
    now: datetime
    eligible: list[GateResult]

    async def assign(self, db: AsyncSession, five_by_user: dict[int, list[int]]) -> int:
        """Store one slot per user who has a full five. Returns the number stored."""
        full = {uid: ids for uid, ids in five_by_user.items() if len(ids) >= DAILY_5_COUNT}
        if not self.eligible or not full:
            return 0
        user_ids = list(full)
        cooldown = await _cooldown(db, user_ids, self.today)
        excluded = await viewer_excluded_promotions(db, user_ids, self.eligible)
        visible = await _visible_by_user(db, full)
        rows: list[dict] = []
        for uid in user_ids:
            candidates = surviving(
                [
                    r
                    for r in self.eligible
                    if r.promotion.id not in excluded[uid] and r.promotion.id not in cooldown[uid]
                ],
                visible[uid],
            )
            if candidates:
                picked = rotation_pick(candidates, explore_seed(uid, self.today))
                rows.append(
                    {"user_id": uid, "slot_date": self.today, "promotion_id": picked.promotion.id}
                )
        if not rows:
            return 0
        # A user who already has today's row (a rebuild) keeps it: the slot is
        # stable for the day.
        stored = (
            await db.execute(
                pg_insert(DailySponsoredSlot)
                .values(rows)
                .on_conflict_do_nothing(constraint="uq_daily_sponsored_slots_user_date")
                .returning(DailySponsoredSlot.promotion_id)
            )
        ).all()
        for (promotion_id,) in stored:
            counters.bump(promotion_id, self.today, PROMOTION_STAT_DAILY5_PLACED)
        return len(stored)

    async def finish(self, db: AsyncSession) -> None:
        """Recompute reach, then write the pending counts (the nightly picks)."""
        await refresh_reach(db, self.today)
        await counters.flush(db)


async def prepare_daily5(db: AsyncSession, now: datetime) -> Daily5Run:
    """Load the live Promotions, run the gate once and write each one's outcome
    and reason row for today. With the slots flag off nothing is picked, and
    the rows say ``slots_disabled``."""
    today = now.date()
    promotions = await load_live_promotions(db, today)
    closed = gate_closed_reason(None)
    if closed is not None:
        await record_gate_outcomes(db, [(p.id, closed) for p in promotions], today)
        return Daily5Run(today, now, [])
    results = await evaluate_gate(db, promotions, now)
    reasons = [(r, daily5_reason(r, now)) for r in results]
    await record_gate_outcomes(db, [(r.promotion.id, reason) for r, reason in reasons], today)
    return Daily5Run(today, now, [r for r, reason in reasons if reason is None])


async def record_gate_outcomes(
    db: AsyncSession, outcomes: Sequence[tuple[int, str | None]], today: date
) -> None:
    """One row per Promotion for today: shown, or paused with the reason. Only
    the outcome and reason are written, so counts already on the row stay."""
    if not outcomes:
        return
    insert = pg_insert(PromotionDailyStat).values(
        [
            {
                "promotion_id": pid,
                "day": today,
                "gate_outcome": (
                    PROMOTION_GATE_OUTCOME_SHOWN
                    if reason is None
                    else PROMOTION_GATE_OUTCOME_PAUSED
                ),
                "gate_reason": reason,
            }
            for pid, reason in outcomes
        ]
    )
    await db.execute(
        insert.on_conflict_do_update(
            constraint="uq_promotion_daily_stats_promotion_day",
            set_={
                "gate_outcome": insert.excluded.gate_outcome,
                "gate_reason": insert.excluded.gate_reason,
            },
        )
    )


async def refresh_reach(db: AsyncSession, today: date) -> None:
    """Distinct users the slot was stored for over each window, in one UPDATE.
    Windows are recomputed from their start until the day after they end, then
    frozen."""
    await db.execute(
        text(
            """
            UPDATE promotions p SET daily5_reach = (
                SELECT count(DISTINCT s.user_id) FROM daily_sponsored_slots s
                WHERE s.promotion_id = p.id
                  AND s.slot_date BETWEEN p.start_date AND p.end_date
            )
            WHERE p.start_date <= :today AND p.end_date >= :yesterday
            """
        ),
        {"today": today, "yesterday": today - timedelta(days=1)},
    )


@dataclass(frozen=True)
class FeedSlot:
    """The slot the feed returns, and whether this read changed the store (the
    caller commits a swap)."""

    result: GateResult | None
    swapped: bool = False


async def resolve_feed_slot(
    db: AsyncSession,
    user_id: int,
    now: datetime,
    five_event_ids: Sequence[int],
    user_agent: str | None,
) -> FeedSlot:
    """The stored slot after the five, re-gated. A failing stored pick is
    swapped once for the next eligible Promotion in the user-day order; the
    replacement is stored and sticks, and when nothing is left the slot
    collapses for the day. Nothing is stored for a user the build gave no slot."""
    if gate_closed_reason(user_agent) is not None:
        return FeedSlot(None)
    today = now.date()
    for _ in range(2):  # a lost compare-and-set re-reads once
        row = await db.scalar(
            select(DailySponsoredSlot).where(
                DailySponsoredSlot.user_id == user_id, DailySponsoredSlot.slot_date == today
            )
        )
        if row is None or row.promotion_id is None:
            return FeedSlot(None)
        stored = await db.get(Promotion, row.promotion_id)
        if stored is None:
            return FeedSlot(None)
        (current,) = await evaluate_gate(db, [stored], now)
        if daily5_reason(current, now) is None:
            return FeedSlot(current)
        # Swapped once already today: collapse, and let that stick too.
        replacement = (
            None
            if row.is_swap
            else await _next_eligible(db, user_id, now, five_event_ids, stored.id)
        )
        won = await db.execute(
            update(DailySponsoredSlot)
            .where(
                DailySponsoredSlot.id == row.id,
                DailySponsoredSlot.promotion_id == stored.id,
            )
            .values(
                promotion_id=replacement.promotion.id if replacement else None,
                is_swap=True,
                replaced_promotion_id=row.replaced_promotion_id or stored.id,
            )
            .returning(DailySponsoredSlot.id)
        )
        if won.first() is None:
            continue
        if replacement is not None:
            counters.bump(replacement.promotion.id, today, PROMOTION_STAT_DAILY5_PLACED)
        return FeedSlot(replacement, swapped=True)
    return FeedSlot(None)


async def _next_eligible(
    db: AsyncSession,
    user_id: int,
    now: datetime,
    five_event_ids: Sequence[int],
    failed_id: int,
) -> GateResult | None:
    today = now.date()
    promotions = [p for p in await load_live_promotions(db, today) if p.id != failed_id]
    results = [
        r for r in await evaluate_gate(db, promotions, now) if daily5_reason(r, now) is None
    ]
    if not results:
        return None
    cooldown = (await _cooldown(db, [user_id], today))[user_id]
    excluded = (await viewer_excluded_promotions(db, [user_id], results))[user_id]
    visible = (await _visible_by_user(db, {user_id: list(five_event_ids)}))[user_id]
    candidates = surviving(
        [r for r in results if r.promotion.id not in excluded and r.promotion.id not in cooldown],
        visible,
    )
    if not candidates:
        return None
    return rotation_pick(candidates, explore_seed(user_id, today))
