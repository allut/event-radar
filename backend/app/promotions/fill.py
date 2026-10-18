"""The Sponsored-slot fill gate and rotation: the only home for "may this
Promotion show here, and which one".

A Promotion may fill a slot only when every clause holds. Each failing clause
has a named not-showing reason (``PROMOTION_NOT_SHOWING_*``), evaluated in this
order:

1. the slots flag is on (``gate_closed_reason``, checked before any query)
2. the request isn't from a self-declared bot (``gate_closed_reason``)
3. status ``paid`` and the window covers today's Tallinn date
4. the event is public, canonical and not ended
5. the Organizer still owns it (``owners.resolve_owner_ids``)
6. ``promotion_restriction`` is ``none`` or the restriction the Promotion's
   Restriction clearance covers (``restriction_cleared``)

An Explore context adds one more reason: the event must pass every active
facet and ``q`` through ``facet_conditions`` (``filters_mismatch``).

A viewer's own signals only exclude (``without_viewer_excluded``): a dislike
of the event or its dedup group, a report, a bookmark or a like skips that
Promotion and the next in rotation order fills the slot.

Everything here reads in bulk with a fixed query count, however many
Promotions are live. Viewer taste (persona, feedback scores) never selects or
orders a Promotion; rotation is a seeded hash of the Promotion id.
"""

import hashlib
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants.ranking import SIGNAL_BOOKMARK, SIGNAL_DISLIKE, SIGNAL_LIKE
from app.constants.promotions import (
    PROMOTION_BOT_USER_AGENT_RE,
    PROMOTION_NOT_SHOWING_BOT,
    PROMOTION_NOT_SHOWING_EVENT_ENDED,
    PROMOTION_NOT_SHOWING_EVENT_NOT_CANONICAL,
    PROMOTION_NOT_SHOWING_EVENT_NOT_PUBLIC,
    PROMOTION_NOT_SHOWING_FILTERS_MISMATCH,
    PROMOTION_NOT_SHOWING_NOT_OWNED,
    PROMOTION_NOT_SHOWING_NOT_PAID,
    PROMOTION_NOT_SHOWING_OUTSIDE_WINDOW,
    PROMOTION_NOT_SHOWING_RESTRICTION_FLAGGED,
    PROMOTION_NOT_SHOWING_RESTRICTION_UNASSESSED,
    PROMOTION_NOT_SHOWING_SLOTS_DISABLED,
    PROMOTION_RESTRICTION_NONE,
    PROMOTION_STATUS_PAID,
)
from app.events.queries import (
    canonical_event_filter,
    event_not_ended_filter,
    public_event_filter,
    select_events_with_classification,
)
from app.models.models import Event, EventReport, Promotion, UserEventFeedback
from app.promotions.owners import resolve_owner_ids
from app.promotions.windows import tallinn_today


@dataclass(frozen=True)
class GateResult:
    """One Promotion's gate outcome: ``reason`` is None when it may show."""

    promotion: Promotion
    event: Event
    reason: str | None


def is_bot_user_agent(user_agent: str | None) -> bool:
    return bool(user_agent) and PROMOTION_BOT_USER_AGENT_RE.search(user_agent or "") is not None


def gate_closed_reason(user_agent: str | None) -> str | None:
    """Clauses 1 and 2, which need no query. None means the gate is open."""
    if not settings.PROMOTIONS_SLOTS_ENABLED:
        return PROMOTION_NOT_SHOWING_SLOTS_DISABLED
    if is_bot_user_agent(user_agent):
        return PROMOTION_NOT_SHOWING_BOT
    return None


def _status_reason(promotion: Promotion, today: date) -> str | None:
    if promotion.status != PROMOTION_STATUS_PAID:
        return PROMOTION_NOT_SHOWING_NOT_PAID
    if not promotion.start_date <= today <= promotion.end_date:
        return PROMOTION_NOT_SHOWING_OUTSIDE_WINDOW
    return None


def _restriction_reason(event: Event, promotion: Promotion) -> str | None:
    if event.promotion_restriction is None:
        return PROMOTION_NOT_SHOWING_RESTRICTION_UNASSESSED
    if event.promotion_restriction not in (
        PROMOTION_RESTRICTION_NONE,
        promotion.restriction_cleared,
    ):
        return PROMOTION_NOT_SHOWING_RESTRICTION_FLAGGED
    return None


async def evaluate_gate(
    db: AsyncSession,
    promotions: Sequence[Promotion],
    now: datetime,
    facet_conds: list[ColumnElement[bool]] | None = None,
) -> list[GateResult]:
    """Run clauses 3 to 6 (plus the Explore facet context when ``facet_conds``
    is given) for each Promotion. Five queries whatever the row count."""
    if not promotions:
        return []
    today = tallinn_today(now)
    event_ids = sorted({p.event_id for p in promotions})
    events = {
        e.id: e
        for e in (
            await db.scalars(select_events_with_classification().where(Event.id.in_(event_ids)))
        ).all()
    }
    flag_rows = (
        await db.execute(
            select(
                Event.id,
                public_event_filter(),
                canonical_event_filter(),
                event_not_ended_filter(now),
            ).where(Event.id.in_(event_ids))
        )
    ).all()
    flags = {row[0]: (bool(row[1]), bool(row[2]), bool(row[3])) for row in flag_rows}
    owners = await resolve_owner_ids(db, list(events.values()))
    facet_ids: set[int] | None = None
    if facet_conds is not None:
        # Same join as the organic query: an event with no classification is
        # never an organic result, so it can't be an eligible slot either.
        facet_ids = set(
            (
                await db.scalars(
                    select(Event.id)
                    .join(Event.classification)
                    .where(Event.id.in_(event_ids), *facet_conds)
                )
            ).all()
        )

    results: list[GateResult] = []
    for promotion in promotions:
        event = events[promotion.event_id]
        public, canonical, live = flags[event.id]
        reason = _status_reason(promotion, today)
        if reason is None and not public:
            reason = PROMOTION_NOT_SHOWING_EVENT_NOT_PUBLIC
        if reason is None and not canonical:
            reason = PROMOTION_NOT_SHOWING_EVENT_NOT_CANONICAL
        if reason is None and not live:
            reason = PROMOTION_NOT_SHOWING_EVENT_ENDED
        if reason is None and owners.get(event.id) != promotion.organizer_id:
            reason = PROMOTION_NOT_SHOWING_NOT_OWNED
        if reason is None:
            reason = _restriction_reason(event, promotion)
        if reason is None and facet_ids is not None and event.id not in facet_ids:
            reason = PROMOTION_NOT_SHOWING_FILTERS_MISMATCH
        results.append(GateResult(promotion, event, reason))
    return results


async def explore_eligible(
    db: AsyncSession, now: datetime, facet_conds: list[ColumnElement[bool]]
) -> list[GateResult]:
    """Every live Promotion whose event passes the gate and the Explore facets,
    ordered by id (rotation orders them per viewer)."""
    today = tallinn_today(now)
    promotions = (
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
    results = await evaluate_gate(db, promotions, now, facet_conds)
    return [r for r in results if r.reason is None]


def explore_seed(user_id: int | None, today: date) -> str:
    """User id + Tallinn date when signed in (stable for a user-day); random per
    request when signed out."""
    if user_id is None:
        return secrets.token_hex(8)
    return f"{user_id}:{today.isoformat()}"


def rotation_order(results: Sequence[GateResult], seed: str) -> list[GateResult]:
    """Equal share, no weighting: order by hash(seed, promotion id)."""
    return sorted(
        results,
        key=lambda r: hashlib.sha256(f"{seed}:{r.promotion.id}".encode()).digest(),
    )


@dataclass(frozen=True)
class VisibleSet:
    """What page 1's organic results already show: event ids, dedup groups and
    series keys. A slot never repeats any of them."""

    event_ids: frozenset[int]
    group_ids: frozenset[int]
    series_keys: frozenset[str]

    def covers(self, event: Event) -> bool:
        group = event.dedup_group_id if event.dedup_group_id is not None else event.id
        return (
            event.id in self.event_ids
            or group in self.group_ids
            or (event.series_key is not None and event.series_key in self.series_keys)
        )


async def load_visible(db: AsyncSession, event_ids: Sequence[int]) -> VisibleSet:
    if not event_ids:
        return VisibleSet(frozenset(), frozenset(), frozenset())
    rows = (
        await db.execute(
            select(Event.id, Event.dedup_group_id, Event.series_key).where(
                Event.id.in_(list(event_ids))
            )
        )
    ).all()
    return VisibleSet(
        frozenset(r[0] for r in rows),
        frozenset(r[1] if r[1] is not None else r[0] for r in rows),
        frozenset(r[2] for r in rows if r[2] is not None),
    )


def surviving(results: Sequence[GateResult], visible: VisibleSet) -> list[GateResult]:
    return [r for r in results if not visible.covers(r.event)]


def _group(event_id: int, dedup_group_id: int | None) -> int:
    return dedup_group_id if dedup_group_id is not None else event_id


async def without_viewer_excluded(
    db: AsyncSession, user_id: int | None, results: Sequence[GateResult]
) -> list[GateResult]:
    """Drop Promotions the signed-in viewer disliked (event or dedup group),
    reported, bookmarked or liked. Two queries whatever the row count; a
    signed-out viewer has no signals and is untouched. Signals only exclude:
    the disliked-category soft filter is deliberately not applied."""
    if user_id is None or not results:
        return list(results)
    event_ids = sorted({r.event.id for r in results})
    groups = sorted({_group(r.event.id, r.event.dedup_group_id) for r in results})
    group_col = func.coalesce(Event.dedup_group_id, Event.id)
    feedback = (
        await db.execute(
            select(UserEventFeedback.signal, UserEventFeedback.event_id, group_col)
            .join(Event, Event.id == UserEventFeedback.event_id)
            .where(
                UserEventFeedback.user_id == user_id,
                UserEventFeedback.signal.in_((SIGNAL_LIKE, SIGNAL_DISLIKE, SIGNAL_BOOKMARK)),
                or_(
                    UserEventFeedback.event_id.in_(event_ids),
                    and_(UserEventFeedback.signal == SIGNAL_DISLIKE, group_col.in_(groups)),
                ),
            )
        )
    ).all()
    reported = set(
        (
            await db.scalars(
                select(EventReport.event_id).where(
                    EventReport.user_id == user_id, EventReport.event_id.in_(event_ids)
                )
            )
        ).all()
    )
    excluded_events = {row[1] for row in feedback} | reported
    disliked_groups = {row[2] for row in feedback if row[0] == SIGNAL_DISLIKE}
    return [
        r
        for r in results
        if r.event.id not in excluded_events
        and _group(r.event.id, r.event.dedup_group_id) not in disliked_groups
    ]

