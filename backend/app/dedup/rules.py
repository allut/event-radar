"""Rule-based deduplication pre-filter for Event Radar.

Stage 1 of the two-stage dedup pipeline:
  rule-based → (Day 9) LLM tiebreaker on candidate pairs only

Merge criteria (ALL three must pass):
  1. Title fuzzy match: rapidfuzz token_set_ratio > TITLE_RATIO_THRESHOLD
  2. Time proximity: |Δstart| < TIME_WINDOW_HOURS hours
  3. Venue compatibility: same venue name (fuzzy) OR either venue is unknown

On match: assign dedup_group_id = min(event_id) across the connected component
(union-find over all candidate pairs).
"""

import logging
from datetime import datetime, timedelta
from typing import Iterable, Optional

from rapidfuzz.fuzz import token_set_ratio
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.constants import (
    SECONDS_PER_HOUR,
    TIME_WINDOW_HOURS,
    TITLE_RATIO_THRESHOLD,
    VENUE_RATIO_THRESHOLD,
)
from app.models.models import Event

log = logging.getLogger(__name__)


def _venue_compatible(a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return True
    return token_set_ratio(a.lower(), b.lower()) >= VENUE_RATIO_THRESHOLD


def is_candidate_pair(a: Event, b: Event) -> bool:
    """Return True when a and b pass all three rule-based criteria."""
    if (
        abs((a.starts_at - b.starts_at).total_seconds())
        > TIME_WINDOW_HOURS * SECONDS_PER_HOUR
    ):
        return False
    if (
        token_set_ratio(a.title_orig.lower(), b.title_orig.lower())
        < TITLE_RATIO_THRESHOLD
    ):
        return False
    return _venue_compatible(a.venue_name, b.venue_name)


# ---------------------------------------------------------------------------
# Union-Find for clustering candidate pairs into groups
# ---------------------------------------------------------------------------


def _find(parent: dict[int, int], x: int) -> int:
    while parent[x] != x:
        parent[x] = parent[parent[x]]  # path compression
        x = parent[x]
    return x


def _union(parent: dict[int, int], a: int, b: int) -> None:
    ra, rb = _find(parent, a), _find(parent, b)
    if ra != rb:
        # smaller ID becomes the root so dedup_group_id == min(event_id)
        if ra < rb:
            parent[rb] = ra
        else:
            parent[ra] = rb


def build_cluster_assignments(parent: dict[int, int], ids: list[int]) -> dict[int, int]:
    """Resolve union-find roots → {event_id: group_id} for groups with ≥2 members."""
    roots: dict[int, list[int]] = {}
    for eid in ids:
        root = _find(parent, eid)
        roots.setdefault(root, []).append(eid)
    assignments: dict[int, int] = {}
    for root, members in roots.items():
        if len(members) > 1:
            for eid in members:
                assignments[eid] = root
    return assignments


def cluster_events(
    events: list[Event],
    candidate_pair_ids: Optional[Iterable[tuple[int, int]]] = None,
) -> dict[int, int]:
    """Return {event_id: dedup_group_id} for events that share a group.

    Events with no duplicates are NOT included in the result.

    If ``candidate_pair_ids`` is provided, only those (a_id, b_id) tuples are
    fuzzy-checked (typically pre-filtered by SQL on the time window). Without
    it, falls back to the original O(N²) Python enumeration.
    """
    n = len(events)
    if n < 2:
        return {}

    ids = [e.id for e in events]
    parent: dict[int, int] = {eid: eid for eid in ids}

    pair_count = 0
    if candidate_pair_ids is None:
        for i in range(n):
            for j in range(i + 1, n):
                if is_candidate_pair(events[i], events[j]):
                    _union(parent, events[i].id, events[j].id)
                    pair_count += 1
    else:
        events_by_id: dict[int, Event] = {e.id: e for e in events}
        for a_id, b_id in candidate_pair_ids:
            a = events_by_id.get(a_id)
            b = events_by_id.get(b_id)
            if a is None or b is None:
                continue
            if is_candidate_pair(a, b):
                _union(parent, a.id, b.id)
                pair_count += 1

    if pair_count:
        log.debug("dedup: found %d candidate pair(s) among %d events", pair_count, n)

    return build_cluster_assignments(parent, ids)


# ---------------------------------------------------------------------------
# DB-level pass
# ---------------------------------------------------------------------------


async def run_dedup_pass(db: AsyncSession) -> dict:
    """Find duplicate events and assign dedup_group_id.

    Loads all non-cancelled events, clusters them, and writes group IDs for
    any newly discovered or changed groups. Returns a summary dict.
    """
    from app.constants import (
        EVENT_STATUS_CANCELLED,
        DEDUP_LOOKBACK_DAYS,
        TALLINN_TZ,
    )  # avoid circular

    # Extend lower bound by TIME_WINDOW_HOURS: boundary pairs (events within 12h of
    # the cutoff) are loaded together so neither is evaluated without its partner.
    cutoff = (
        datetime.now(tz=TALLINN_TZ)
        - timedelta(days=DEDUP_LOOKBACK_DAYS)
        - timedelta(hours=TIME_WINDOW_HOURS)
    )
    rows = (
        await db.scalars(
            select(Event)
            .where(Event.status != EVENT_STATUS_CANCELLED)
            .where(Event.starts_at >= cutoff)
            .order_by(Event.id)
        )
    ).all()
    events = list(rows)

    if not events:
        return {"total": 0, "grouped": 0, "pairs": 0}

    # SQL pre-filter: self-join restricted to pairs within TIME_WINDOW_HOURS.
    # Result set is small (~O(N·k) where k is avg events in the window), but
    # the join itself is bounded by the existing (starts_at, status) B-tree:
    # the planner can range-scan b on a sargable BETWEEN around a.starts_at.
    a = aliased(Event)
    b = aliased(Event)
    window = timedelta(seconds=TIME_WINDOW_HOURS * SECONDS_PER_HOUR)
    pair_rows = (
        await db.execute(
            select(a.id, b.id)
            .join(
                b,
                (a.id < b.id)
                & (b.starts_at >= a.starts_at - window)
                & (b.starts_at <= a.starts_at + window),
            )
            .where(
                a.status != EVENT_STATUS_CANCELLED,
                b.status != EVENT_STATUS_CANCELLED,
                a.starts_at >= cutoff,
                b.starts_at >= cutoff,
            )
        )
    ).all()
    candidate_pair_ids = [(row[0], row[1]) for row in pair_rows]

    assignments = cluster_events(events, candidate_pair_ids=candidate_pair_ids)

    updated = 0
    for event in events:
        new_gid = assignments.get(event.id)
        if event.dedup_group_id != new_gid:
            event.dedup_group_id = new_gid
            updated += 1

    # Null out dedup_group_id for events that have aged out of the window.
    # Without this, an event excluded from the query would retain a stale group_id
    # even after its partner was cleared by the loop above.
    # synchronize_session=False: safe here because aged-out rows (starts_at < cutoff)
    # were never loaded by the SELECT above (starts_at >= cutoff), so no identity-map
    # objects are affected. The status filter mirrors the SELECT to keep scope consistent.
    await db.execute(
        update(Event)
        .where(Event.starts_at < cutoff)
        .where(Event.status != EVENT_STATUS_CANCELLED)
        .where(Event.dedup_group_id.is_not(None))
        .values(dedup_group_id=None),
        execution_options={"synchronize_session": False},
    )

    group_count = len({gid for gid in assignments.values()})
    log.info(
        "dedup pass: %d events, %d grouped into %d group(s), %d updated",
        len(events),
        len(assignments),
        group_count,
        updated,
    )
    return {
        "total": len(events),
        "grouped": len(assignments),
        "groups": group_count,
        "updated": updated,
    }
