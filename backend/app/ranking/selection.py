"""
Daily 5 selection: capped MMR pick with tiered backfill.

Pure: takes pre-scored events and returns the picks. Depends on neither
scoring nor the DB build.
"""

from __future__ import annotations

from heapq import nlargest

from app.constants.ranking import DAILY_5_BACKFILL_TRUNCATION_MULTIPLIER
from app.models.events import Event


def _mmr_pick(
    scored_sorted: list[tuple[float, Event]], n: int, max_per_category: int
) -> list[Event]:
    """
    MMR-lite diversity pick: greedy top-n with at most max_per_category events per category.
    Events with no categories bypass the category cap.

    ``scored_sorted`` must already be sorted by score descending (the caller,
    ``select_with_backfill``, sorts each pool once up front and reuses it across every
    tier — sorting here too would repeat the same O(E log E) work per tier for no
    benefit, since the order is identical every time).
    """
    category_counts: dict[str, int] = {}
    picked: list[Event] = []

    for _, event in scored_sorted:
        if len(picked) >= n:
            break
        cl = event.classification
        cats: list[str] = cl.categories if cl else []

        # Events with categories must respect the per-category cap
        if cats and any(category_counts.get(c, 0) >= max_per_category for c in cats):
            continue

        picked.append(event)
        for c in cats:
            category_counts[c] = category_counts.get(c, 0) + 1

    return picked


def _greedy_fill(
    picked: list[Event],
    picked_ids: set[int],
    category_counts: dict[str, int],
    pool_sorted: list[tuple[float, Event]],
    n: int,
    max_per_category: int | None,
) -> None:
    """Append highest-scored events from pool (not already picked) until len(picked) == n.
    When max_per_category is not None, skip an event whose category already hit the cap
    (events with no categories bypass it, matching _mmr_pick).

    ``pool_sorted`` must already be sorted by score descending — see the note on
    ``_mmr_pick``; the same pre-sorted pool is passed to more than one tier here."""
    for _, event in pool_sorted:
        if len(picked) >= n:
            break
        if event.id in picked_ids:
            continue
        cl = event.classification
        cats: list[str] = cl.categories if cl else []
        if (
            max_per_category is not None
            and cats
            and any(category_counts.get(c, 0) >= max_per_category for c in cats)
        ):
            continue
        picked.append(event)
        picked_ids.add(event.id)
        for c in cats:
            category_counts[c] = category_counts.get(c, 0) + 1


def select_with_backfill(
    scored: list[tuple[float, Event]],
    cooled_scored: list[tuple[float, Event]],
    n: int,
    max_per_category: int,
    backfill_max_per_category: int,
) -> list[Event]:
    """
    Capped MMR (tier 1), then backfill to n: relaxed-cap fresh, relaxed-cap
    cooled, then uncapped fresh/cooled as a last resort. Diversity is preferred
    over freshness in the relaxed tiers; the uncapped sweep guarantees reaching n
    when scarce. Dislikes are excluded upstream and never re-enter.

    Each pool is truncated to its top ``n * DAILY_5_BACKFILL_TRUNCATION_MULTIPLIER``
    scores via ``heapq.nlargest`` exactly once here (O(E log k) instead of a full
    O(E log E) sort), and the same truncated, sorted list is reused across every
    tier that consumes it (``scored`` feeds tiers 1, 2, and 4; ``cooled_scored``
    feeds tiers 3 and 5) — previously each tier re-sorted the *whole* pool
    independently. Only if every tier still leaves the pick short of ``n`` (the
    truncated top-k didn't contain enough eligible events — pathologically rare
    at realistic pool sizes) does this fall back to a full sort of the
    untruncated pool for one last uncapped pass.
    """
    truncate_to = n * DAILY_5_BACKFILL_TRUNCATION_MULTIPLIER
    scored_sorted = nlargest(truncate_to, scored, key=lambda x: x[0])
    cooled_sorted = nlargest(truncate_to, cooled_scored, key=lambda x: x[0])

    picked = _mmr_pick(scored_sorted, n, max_per_category)
    if len(picked) >= n:
        return picked
    picked_ids = {e.id for e in picked}
    category_counts: dict[str, int] = {}
    for e in picked:
        for c in e.classification.categories if e.classification else []:
            category_counts[c] = category_counts.get(c, 0) + 1
    # relaxed-cap tiers (diversity preserved)
    _greedy_fill(
        picked, picked_ids, category_counts, scored_sorted, n, backfill_max_per_category
    )
    if len(picked) < n:
        _greedy_fill(
            picked,
            picked_ids,
            category_counts,
            cooled_sorted,
            n,
            backfill_max_per_category,
        )
    # uncapped last resort (guarantee n when relaxed cap left it short)
    if len(picked) < n:
        _greedy_fill(picked, picked_ids, category_counts, scored_sorted, n, None)
    if len(picked) < n:
        _greedy_fill(picked, picked_ids, category_counts, cooled_sorted, n, None)
    # Truncated top-k pools were exhausted without reaching n — pay for the
    # full sort only now, as a last resort.
    if len(picked) < n:
        full_scored_sorted = sorted(scored, key=lambda x: x[0], reverse=True)
        _greedy_fill(picked, picked_ids, category_counts, full_scored_sorted, n, None)
    if len(picked) < n:
        full_cooled_sorted = sorted(cooled_scored, key=lambda x: x[0], reverse=True)
        _greedy_fill(picked, picked_ids, category_counts, full_cooled_sorted, n, None)
    return picked
