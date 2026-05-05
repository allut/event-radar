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

from rapidfuzz.fuzz import token_set_ratio
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import TITLE_RATIO_THRESHOLD, VENUE_RATIO_THRESHOLD, TIME_WINDOW_HOURS
from app.models.models import Event

log = logging.getLogger(__name__)


def _venue_compatible(a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return True
    return token_set_ratio(a.lower(), b.lower()) >= VENUE_RATIO_THRESHOLD


def is_candidate_pair(a: Event, b: Event) -> bool:
    """Return True when a and b pass all three rule-based criteria."""
    if abs((a.starts_at - b.starts_at).total_seconds()) > TIME_WINDOW_HOURS * 3600:
        return False
    if token_set_ratio(a.title_orig.lower(), b.title_orig.lower()) < TITLE_RATIO_THRESHOLD:
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


def cluster_events(events: list[Event]) -> dict[int, int]:
    """Return {event_id: dedup_group_id} for events that share a group.

    Events with no duplicates are NOT included in the result.
    """
    n = len(events)
    if n < 2:
        return {}

    ids = [e.id for e in events]
    parent: dict[int, int] = {eid: eid for eid in ids}

    pair_count = 0
    for i in range(n):
        for j in range(i + 1, n):
            if is_candidate_pair(events[i], events[j]):
                _union(parent, events[i].id, events[j].id)
                pair_count += 1

    if pair_count:
        log.debug("dedup: found %d candidate pair(s) among %d events", pair_count, n)

    # Collect only events that belong to a group (root has ≥2 members)
    roots: dict[int, list[int]] = {}
    for eid in ids:
        root = _find(parent, eid)
        roots.setdefault(root, []).append(eid)

    result: dict[int, int] = {}
    for root, members in roots.items():
        if len(members) > 1:
            for eid in members:
                result[eid] = root

    return result


# ---------------------------------------------------------------------------
# DB-level pass
# ---------------------------------------------------------------------------


async def run_dedup_pass(db: AsyncSession) -> dict:
    """Find duplicate events and assign dedup_group_id.

    Loads all non-cancelled events, clusters them, and writes group IDs for
    any newly discovered or changed groups. Returns a summary dict.
    """
    from app.constants import EVENT_STATUS_CANCELLED, DEDUP_LOOKBACK_DAYS, TALLINN_TZ  # avoid circular

    # Extend lower bound by TIME_WINDOW_HOURS: boundary pairs (events within 12h of
    # the cutoff) are loaded together so neither is evaluated without its partner.
    cutoff = datetime.now(tz=TALLINN_TZ) - timedelta(days=DEDUP_LOOKBACK_DAYS) - timedelta(hours=TIME_WINDOW_HOURS)
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

    assignments = cluster_events(events)

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
        len(events), len(assignments), group_count, updated,
    )
    return {
        "total": len(events),
        "grouped": len(assignments),
        "groups": group_count,
        "updated": updated,
    }
