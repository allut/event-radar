"""
Personalized event scoring and Daily 5 feed builder.

Formula (all components normalized to [0, 1]):
  score = 0.45 * persona_affinity
        + 0.20 * recency_boost
        + 0.20 * feedback_signal (mapped from [-1,1] to [0,1])
        + 0.10 * quality_score
        + 0.05 * locality_bonus
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from functools import cached_property
from heapq import nlargest

from sqlalchemy import or_, select, true
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

from app.constants import (
    FEEDBACK_HISTORY_LOOKBACK_DAYS,
    DAILY5_SERIES_COOLDOWN_DAYS,
    DAILY_5_BACKFILL_MAX_PER_CATEGORY,
    DAILY_5_BACKFILL_TRUNCATION_MULTIPLIER,
    DAILY_5_COUNT,
    DAILY_5_LOOKAHEAD_DAYS,
    DAILY_5_MAX_PER_CATEGORY,
    FEED_BUILD_USER_BATCH_SIZE,
    FEEDBACK_DECAY_BASE,
    FEEDBACK_INDIRECT_WEIGHT,
    NEUTRAL_SCORE,
    RECENCY_DECAY_DAYS,
    SCORE_HARD_EXCLUDE,
    SCORE_INSERT_CHUNK_SIZE,
    SCORE_WEIGHT_AFFINITY,
    SCORE_WEIGHT_ANON_LOCALITY,
    SCORE_WEIGHT_ANON_QUALITY,
    SCORE_WEIGHT_ANON_RECENCY,
    SCORE_WEIGHT_FEEDBACK,
    SCORE_WEIGHT_LOCALITY,
    SCORE_WEIGHT_QUALITY,
    SCORE_WEIGHT_RECENCY,
    SECONDS_PER_DAY,
    SIGNAL_DISLIKE,
    SIGNAL_LIKE,
    TALLINN_CENTER_LAT,
    TALLINN_CENTER_LNG,
    TALLINN_LAT_DELTA,
    TALLINN_LNG_DELTA,
    TALLINN_TZ,
    TIME_DAYTIME_START,
    TIME_EVENING_START,
    TIME_LATE_NIGHT_START,
    TIME_MORNING_START,
    TIME_SLOT_DAYTIME,
    TIME_SLOT_EVENING,
    TIME_SLOT_LATE_NIGHT,
    TIME_SLOT_MORNING,
    TIME_SLOT_WEEKDAY,
    TIME_SLOT_WEEKEND,
    WEEKEND_START_WEEKDAY,
)
from app.models.models import (
    DailyFeed,
    Event,
    EventClassification,
    User,
    UserEventFeedback,
    UserEventScore,
    UserPersona,
)
from app.routers.utils import (
    collapse_series_duplicates,
    persona_weight_tuple,
    select_events_with_classification,
)
from app.events.venue import resolve_venue_coords, resolve_venue_name
from app.events.queries import (
    canonical_event_filter,
    public_event_filter,
    event_not_ended_filter,
    event_series_key,
)

# ---------------------------------------------------------------------------
# Feedback context (precomputed for one user, reused across event scoring)
# ---------------------------------------------------------------------------


@dataclass
class _FeedbackRow:
    signal: str
    event_id: int
    categories: list[str]
    dedup_group_id: int | None
    created_at: datetime
    # Precomputed frozenset of `categories` — hoisted out of the inner scoring
    # loop so we don't rebuild it once per (event × feedback-row) iteration.
    category_set: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.category_set and self.categories:
            self.category_set = frozenset(self.categories)


@dataclass
class FeedbackContext:
    rows: list[_FeedbackRow] = field(default_factory=list)
    disliked_groups: frozenset[int] = field(default_factory=frozenset)
    disliked_event_ids: frozenset[int] = field(default_factory=frozenset)
    # O(1) direct-match lookup: event_id → all rows for that event
    direct_map: dict[int, list[_FeedbackRow]] = field(default_factory=dict)
    # Only liked rows — indirect category matching iterates this subset, not all rows
    liked_rows: list[_FeedbackRow] = field(default_factory=list)
    # Indirect-signal aggregates, lazily populated by feedback_signal() via
    # build_liked_aggregates(now) on first use (decay depends on `now`, fixed once per
    # build_daily_feeds call). Keyed by distinct category_set rather than per-row:
    # collapses the O(E * L) indirect scan in feedback_signal to O(E * S), S = distinct
    # liked category-sets (S << L for a real user, since likes cluster into a handful
    # of category combinations).
    liked_decay_by_catset: dict[frozenset[str], float] = field(default_factory=dict)
    # Each liked row's own decay contribution, for self-exclusion when the scored event
    # is itself one of the user's liked rows (row.event_id != event_id in the old loop).
    liked_decay_by_event: dict[int, float] = field(default_factory=dict)
    # `now` the aggregates above were built for; None means not built yet. Lets
    # feedback_signal() lazily (re)build on first use / if `now` changes, so a caller
    # that forgets to call build_liked_aggregates() explicitly still gets correct
    # results instead of a silent all-zero indirect signal.
    _liked_aggregates_built_for: datetime | None = field(default=None, repr=False)
    # Memoizes the catset-overlap sum in _indirect_feedback_signal, keyed on
    # the *candidate event's* category set — with 14 valid categories the
    # number of distinct category sets across a scoring pool is tiny relative
    # to the number of candidates, so every event sharing a set reuses one
    # computed sum instead of redoing the frozenset intersections (score.py
    # Big-O audit M11). Reset whenever build_liked_aggregates() rebuilds,
    # since it depends on liked_decay_by_catset.
    _indirect_overlap_by_catset: dict[frozenset[str], float] = field(
        default_factory=dict, repr=False
    )

    @cached_property
    def disliked_categories(self) -> frozenset[str]:
        """Union of categories across every disliked feedback row.

        Reuses the `_FeedbackRow.categories` data already loaded for indirect
        feedback scoring — no extra query. Consumed by the /explore For-you
        soft-filter (browse.py) to hide events in a category the user has
        actively disliked, independent of the per-event/per-group hard
        excludes (`disliked_event_ids` / `disliked_groups`).

        `@cached_property` (not `@property`): `self.rows` is fixed at
        construction (from_orm_rows), so this is safe to compute once and
        reuse — an in-loop call inside scoring is a one-character regression
        away from O(E*L) otherwise.
        """
        cats: set[str] = set()
        for row in self.rows:
            if row.signal == SIGNAL_DISLIKE:
                cats.update(row.categories)
        return frozenset(cats)

    def build_liked_aggregates(self, now: datetime) -> None:
        """Populate liked_decay_by_catset / liked_decay_by_event for this `now`.

        Idempotent per `now`: a repeat call with the same `now` is a no-op (checked by
        feedback_signal before calling this, so normal per-user-per-build usage costs
        exactly one O(L) pass). Exactly reproduces the old per-row loop's semantics:
        each liked row contributes FEEDBACK_INDIRECT_WEIGHT * decay(row) once, decay =
        FEEDBACK_DECAY_BASE**days.
        """
        if self._liked_aggregates_built_for == now:
            return
        self.liked_decay_by_catset = {}
        self.liked_decay_by_event = {}
        self._indirect_overlap_by_catset = {}
        for row in self.liked_rows:
            days = max(0.0, (now - row.created_at).total_seconds() / SECONDS_PER_DAY)
            decay = FEEDBACK_INDIRECT_WEIGHT * (FEEDBACK_DECAY_BASE**days)
            self.liked_decay_by_catset[row.category_set] = (
                self.liked_decay_by_catset.get(row.category_set, 0.0) + decay
            )
            # Sum, not overwrite: a partial unique index (migration 0019) now
            # guarantees at most one like/dislike/bookmark row per (user, event),
            # but this loop still iterates all rows generically — the sum is a
            # no-op for the single-row case and correctly reproduces the old
            # per-row loop's behavior otherwise (matches the old loop, which
            # skipped every row with row.event_id == event_id).
            self.liked_decay_by_event[row.event_id] = (
                self.liked_decay_by_event.get(row.event_id, 0.0) + decay
            )
        self._liked_aggregates_built_for = now

    @classmethod
    def from_orm_rows(cls, orm_rows: list[UserEventFeedback]) -> "FeedbackContext":
        rows: list[_FeedbackRow] = []
        for r in orm_rows:
            cats: list[str] = []
            dedup_group: int | None = None
            if r.event:
                dedup_group = r.event.dedup_group_id
                if r.event.classification:
                    cats = r.event.classification.categories or []
            rows.append(
                _FeedbackRow(
                    signal=r.signal,
                    event_id=r.event_id,
                    categories=cats,
                    dedup_group_id=dedup_group,
                    created_at=r.created_at,
                )
            )
        disliked_groups = frozenset(
            row.dedup_group_id
            for row in rows
            if row.signal == SIGNAL_DISLIKE and row.dedup_group_id is not None
        )
        disliked_event_ids = frozenset(
            row.event_id for row in rows if row.signal == SIGNAL_DISLIKE
        )
        direct_map: dict[int, list[_FeedbackRow]] = {}
        for row in rows:
            direct_map.setdefault(row.event_id, []).append(row)
        liked_rows = [row for row in rows if row.signal == SIGNAL_LIKE]
        return cls(
            rows=rows,
            disliked_groups=disliked_groups,
            disliked_event_ids=disliked_event_ids,
            direct_map=direct_map,
            liked_rows=liked_rows,
        )


# ---------------------------------------------------------------------------
# Pure scoring functions (no DB access)
# ---------------------------------------------------------------------------


def _time_slots_for_event(starts_at: datetime) -> list[str]:
    """
    Derive time-of-day and day-of-week slots from a timezone-aware starts_at.
    An event can match multiple slots (e.g. Saturday evening → ['weekend', 'evening']).

    build_daily_feeds calls this once per (user, candidate-event) pair via
    score_event, but the result depends only on the event's starts_at. Rather
    than an LRU cache keyed on starts_at (which thrashed to a near-0% hit rate
    once the number of distinct start times exceeded the cache's maxsize —
    Big-O audit #5, item 2.2), build_daily_feeds precomputes this once per
    event into _precompute_event_factors' result and threads it through as
    part of ``precomputed``; ad hoc single-user callers (browse.py) still call
    this directly and pay the cost once per event, which is fine at that scale.
    """
    local = starts_at.astimezone(TALLINN_TZ)
    hour = local.hour
    slots: list[str] = []
    if hour >= TIME_LATE_NIGHT_START or hour < TIME_MORNING_START:
        slots.append(TIME_SLOT_LATE_NIGHT)
    elif hour >= TIME_EVENING_START:
        slots.append(TIME_SLOT_EVENING)
    elif hour >= TIME_DAYTIME_START:
        slots.append(TIME_SLOT_DAYTIME)
    elif hour >= TIME_MORNING_START:
        slots.append(TIME_SLOT_MORNING)
    if local.weekday() >= WEEKEND_START_WEEKDAY:
        slots.append(TIME_SLOT_WEEKEND)
    else:
        slots.append(TIME_SLOT_WEEKDAY)
    return slots


def _affinity_for_vector(
    vector: dict,
    categories: list[str],
    vibes: list[str],
    time_slots: Sequence[str] = (),
) -> float:
    """
    Compute affinity of one persona vector against event tags + time slots.
    Normalizes raw dot-product by the max achievable score from this vector so that
    ranking discrimination is preserved for high-match events → returns [0, 1].
    """
    cat_map: dict[str, float] = vector.get("categories", {})
    vibe_map: dict[str, float] = vector.get("vibes", {})
    time_map: dict[str, float] = vector.get("times", {})
    max_possible = (
        sum(cat_map.values()) + sum(vibe_map.values()) + sum(time_map.values())
    )
    if max_possible <= 0:
        # Empty vector or all-negative weights — no meaningful signal, return neutral.
        return NEUTRAL_SCORE
    raw = (
        sum(cat_map.get(c, 0.0) for c in categories)
        + sum(vibe_map.get(v, 0.0) for v in vibes)
        + sum(time_map.get(t, 0.0) for t in time_slots)
    )
    normalized = max(-1.0, min(1.0, raw / max_possible))
    return (normalized + 1.0) / 2.0


# (id(persona vector), categories, vibes, time_slots) -> _affinity_for_vector().
# A vector's affinity depends only on the vector and the event's tags, and the
# daily-feed build scores every user against every event with only a handful of
# distinct persona vectors — so one build-scoped dict collapses the
# U x E x P x |vec| work to (distinct vectors x distinct tag-sets) (Big-O
# audit H4). Keyed on id(): the vectors are held alive by the build context.
AffinityCache = dict[tuple[int, tuple[str, ...], tuple[str, ...], tuple[str, ...]], float]


def persona_affinity(
    user_persona_weights: list[tuple[float, dict]],
    categories: list[str],
    vibes: list[str],
    time_slots: Sequence[str] = (),
    cache: AffinityCache | None = None,
) -> float:
    """Weighted blend of persona affinities → [0, 1]. Returns NEUTRAL_SCORE with no personas.

    ``cache`` is an optional build-scoped memo of per-vector affinities (see
    ``AffinityCache``); omit it for one-off calls."""
    if not user_persona_weights:
        return NEUTRAL_SCORE
    total_weight = sum(w for w, _ in user_persona_weights)
    if total_weight == 0:
        return NEUTRAL_SCORE
    if cache is None:
        weighted = sum(
            w * _affinity_for_vector(vec, categories, vibes, time_slots)
            for w, vec in user_persona_weights
        )
        return weighted / total_weight
    tags = (tuple(categories), tuple(vibes), tuple(time_slots))
    weighted = 0.0
    for w, vec in user_persona_weights:
        key = (id(vec), *tags)
        affinity = cache.get(key)
        if affinity is None:
            affinity = _affinity_for_vector(vec, categories, vibes, time_slots)
            cache[key] = affinity
        weighted += w * affinity
    return weighted / total_weight


def recency_boost(starts_at: datetime, now: datetime) -> float:
    """Linear decay 1.0 at starts_at == now to 0.0 at +21 days. 0.0 for past events."""
    delta_days = (starts_at - now).total_seconds() / SECONDS_PER_DAY
    if delta_days < 0:
        return 0.0
    return max(0.0, 1.0 - delta_days / RECENCY_DECAY_DAYS)


def _direct_feedback_signal(
    event_id: int, ctx: FeedbackContext, now: datetime
) -> list[float]:
    """Decayed contributions of this event's own like/dislike rows (O(1) lookup)."""
    signals: list[float] = []
    for row in ctx.direct_map.get(event_id, []):
        days = max(0.0, (now - row.created_at).total_seconds() / SECONDS_PER_DAY)
        decay = FEEDBACK_DECAY_BASE**days
        if row.signal == SIGNAL_LIKE:
            signals.append(decay)
        elif row.signal == SIGNAL_DISLIKE:
            signals.append(-1.0)
    return signals


def _indirect_feedback_signal(
    event_id: int, event_cat_set: frozenset[str], ctx: FeedbackContext
) -> float:
    """Pre-aggregated decay of liked category-sets overlapping this event's.

    O(distinct liked category-sets) instead of O(all liked rows). The event's
    own contribution is subtracted (the per-row loop this replaces excluded
    rows with row.event_id == event_id). That unconditional subtraction
    assumes a liked row's category_set is identical to the scored event's
    categories for the same event_id — true today because both reads resolve
    to the same identity-mapped Event within one build_daily_feeds() call.
    If reclassification ever runs concurrently with feed building, this could
    subtract decay that was never added; guarding would need the O(L) per-row
    scan this aggregation exists to avoid, so it stays a documented assumption.
    """
    overlap = ctx._indirect_overlap_by_catset.get(event_cat_set)
    if overlap is None:
        overlap = sum(
            decay
            for cats, decay in ctx.liked_decay_by_catset.items()
            if cats & event_cat_set
        )
        ctx._indirect_overlap_by_catset[event_cat_set] = overlap
    return overlap - ctx.liked_decay_by_event.get(event_id, 0.0)


def feedback_signal(
    event_id: int,
    event_categories: list[str],
    event_dedup_group: int | None,
    ctx: FeedbackContext,
    now: datetime,
) -> float:
    """
    Feedback score in [-1, 1] for normal events.
    Returns SCORE_HARD_EXCLUDE (-2.0, deliberately outside the [-1, 1] range so it
    cannot collide with a legitimately disliked event's -1.0) when the event belongs
    to a disliked dedup_group; the caller skips the event entirely.
    """
    if event_dedup_group is not None and event_dedup_group in ctx.disliked_groups:
        return SCORE_HARD_EXCLUDE

    signals = _direct_feedback_signal(event_id, ctx, now)

    # No-op if already built for this `now` (the normal per-user-per-build
    # case) — self-healing for any caller that forgot to build.
    ctx.build_liked_aggregates(now)
    event_cat_set = frozenset(event_categories)
    if event_cat_set:
        indirect = _indirect_feedback_signal(event_id, event_cat_set, ctx)
        if indirect:
            signals.append(indirect)

    if not signals:
        return 0.0
    return max(-1.0, min(1.0, sum(signals)))


def locality_bonus(lat: float | None, lng: float | None) -> float:
    """1.0 if within central Tallinn bounding box; NEUTRAL_SCORE when location unknown; 0.0 otherwise."""
    if lat is None or lng is None:
        return NEUTRAL_SCORE
    if (
        abs(lat - TALLINN_CENTER_LAT) < TALLINN_LAT_DELTA
        and abs(lng - TALLINN_CENTER_LNG) < TALLINN_LNG_DELTA
    ):
        return 1.0
    return 0.0


_EventFactors = tuple[float, float, float, list[str]]


def _precompute_event_factors(
    event_rows: list[Event], now: datetime
) -> dict[int, _EventFactors]:
    """Per-event (recency, quality, locality, time_slots) — invariant across
    every user.

    build_daily_feeds' inner loop calls score_event once per (user, candidate)
    pair; these four factors depend only on the event and the run's fixed
    ``now``, so without this they're recomputed identically U times per event
    at U x E scale. Hoisted once here and threaded through as ``precomputed``
    (time_slots joined this tuple in Big-O audit #5, item 2.2 — see
    _time_slots_for_event).
    """
    factors: dict[int, _EventFactors] = {}
    for event in event_rows:
        cl = event.classification
        quality = cl.quality_score if cl and cl.quality_score is not None else NEUTRAL_SCORE
        lat, lng = resolve_venue_coords(event)
        factors[event.id] = (
            recency_boost(event.starts_at, now),
            quality,
            locality_bonus(lat, lng),
            _time_slots_for_event(event.starts_at),
        )
    return factors


def score_event(
    user_persona_weights: list[tuple[float, dict]],
    ctx: FeedbackContext,
    event: Event,
    now: datetime,
    precomputed: _EventFactors | None = None,
    affinity_cache: AffinityCache | None = None,
) -> float | None:
    """
    Compute personalized score for one event. Returns None if hard-excluded.
    Score is in [0, 1].

    ``precomputed`` is the (recency, quality, locality, time_slots) tuple from
    ``_precompute_event_factors`` — pass it from a caller iterating many users
    over the same candidate pool to skip recomputing these per-event-only
    values on every call. Callers scoring a single user's events ad hoc (e.g.
    browse.py) omit it and get the values computed inline, as before.
    """
    cl: EventClassification | None = event.classification
    categories: list[str] = cl.categories if cl else []
    vibes: list[str] = cl.vibes if cl else []

    fb = feedback_signal(event.id, categories, event.dedup_group_id, ctx, now)
    if fb == SCORE_HARD_EXCLUDE:
        return None  # hard exclude

    if precomputed is not None:
        recency, quality, locality, time_slots = precomputed
    else:
        time_slots = _time_slots_for_event(event.starts_at)
        recency = recency_boost(event.starts_at, now)
        quality = (
            cl.quality_score if cl and cl.quality_score is not None else NEUTRAL_SCORE
        )
        lat, lng = resolve_venue_coords(event)
        locality = locality_bonus(lat, lng)
    affinity = persona_affinity(
        user_persona_weights, categories, vibes, time_slots, cache=affinity_cache
    )
    fb_normalized = (fb + 1.0) / 2.0  # map [-1, 1] → [0, 1]

    return (
        SCORE_WEIGHT_AFFINITY * affinity
        + SCORE_WEIGHT_RECENCY * recency
        + SCORE_WEIGHT_FEEDBACK * fb_normalized
        + SCORE_WEIGHT_QUALITY * quality
        + SCORE_WEIGHT_LOCALITY * locality
    )


def anonymous_score_event(event: Event, now: datetime) -> float:
    """Persona-free score for anonymous /explore callers (#234).

    score = SCORE_WEIGHT_AFFINITY * NEUTRAL_SCORE + SCORE_WEIGHT_ANON_RECENCY * recency
          + SCORE_WEIGHT_ANON_QUALITY * quality + SCORE_WEIGHT_ANON_LOCALITY * locality

    feedback_signal is dropped entirely (see the SCORE_WEIGHT_ANON_* constants'
    docstring) — never hard-excludes, unlike score_event(). persona_affinity is
    the constant NEUTRAL_SCORE, matching what persona_affinity([], ...) already
    returns for a request with no persona.
    """
    cl: EventClassification | None = event.classification
    quality = cl.quality_score if cl and cl.quality_score is not None else NEUTRAL_SCORE
    recency = recency_boost(event.starts_at, now)
    lat, lng = resolve_venue_coords(event)
    locality = locality_bonus(lat, lng)
    return (
        SCORE_WEIGHT_AFFINITY * NEUTRAL_SCORE
        + SCORE_WEIGHT_ANON_RECENCY * recency
        + SCORE_WEIGHT_ANON_QUALITY * quality
        + SCORE_WEIGHT_ANON_LOCALITY * locality
    )


def _mmr_pick(
    scored_sorted: list[tuple[float, Event]], n: int, max_per_category: int
) -> list[Event]:
    """
    MMR-lite diversity pick: greedy top-n with at most max_per_category events per category.
    Events with no categories bypass the category cap.

    ``scored_sorted`` must already be sorted by score descending (the caller,
    ``_select_with_backfill``, sorts each pool once up front and reuses it across every
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


def _select_with_backfill(
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


# ---------------------------------------------------------------------------
# Daily feed builder (async, touches DB)
# ---------------------------------------------------------------------------


@dataclass
class _SharedFeedContext:
    """Candidate events + derived series keys — identical for every page of
    users in one build_daily_feeds run. Loaded once, threaded through."""

    event_rows: list[Event]
    candidate_series_key: dict[int, tuple[str, str]]
    event_factors: dict[int, _EventFactors]


@dataclass
class _FeedBuildContext:
    """Everything the per-user scoring loop needs, bulk-loaded up front.

    A fixed number of queries independent of user count (the no-N+1 batch rule).
    """

    shared: _SharedFeedContext
    users: list[User]
    personas_by_user: dict[int, list[tuple[float, dict]]]
    fb_by_user: dict[int, list[UserEventFeedback]]
    recent_series_by_user: dict[int, set[tuple[str, str]]]
    score_cache: dict[tuple[int, int], float]
    # Shared across the users of this page (one context per page) — see
    # AffinityCache; must not outlive the context that holds the vectors.
    affinity_cache: AffinityCache = field(default_factory=dict)

    @property
    def event_rows(self) -> list[Event]:
        return self.shared.event_rows

    @property
    def candidate_series_key(self) -> dict[int, tuple[str, str]]:
        return self.shared.candidate_series_key

    @property
    def event_factors(self) -> dict[int, _EventFactors]:
        return self.shared.event_factors


async def _load_recent_series_by_user(
    db: AsyncSession, user_ids: list[int], today: date
) -> dict[int, set[tuple[str, str]]]:
    """Series keys each user was shown within the cooldown window.

    Suppresses repeat recommendations of the same recurring series across
    days — a multi-day series (one canonical event per day) would otherwise
    score well and be re-picked night after night. Feed-level filter,
    independent of dedup_group_id (series are intentionally not dedup-grouped).
    """
    recent_series_by_user: dict[int, set[tuple[str, str]]] = {}
    cooldown_start = today - timedelta(days=DAILY5_SERIES_COOLDOWN_DAYS)
    recent_feed_rows = (
        await db.scalars(
            select(DailyFeed).where(
                DailyFeed.user_id.in_(user_ids),
                DailyFeed.feed_date >= cooldown_start,
                DailyFeed.feed_date < today,
            )
        )
    ).all()
    # event_id -> set of user_ids who were shown it within the window
    shown_event_users: dict[int, set[int]] = {}
    for feed_row in recent_feed_rows:
        for eid in feed_row.event_ids or []:
            shown_event_users.setdefault(eid, set()).add(feed_row.user_id)
    if shown_event_users:
        # Bulk SELECT, chunked at SCORE_INSERT_CHUNK_SIZE — shown events may be
        # outside the current lookahead window, so resolve them directly rather
        # than from event_rows. Unchunked this hits Postgres's per-statement
        # bind-param limit past ~32k ids (Big-O audit #5, item 1.6).
        shown_event_ids = list(shown_event_users.keys())
        shown_event_rows: list[Event] = []
        for i in range(0, len(shown_event_ids), SCORE_INSERT_CHUNK_SIZE):
            chunk = shown_event_ids[i : i + SCORE_INSERT_CHUNK_SIZE]
            shown_event_rows.extend(
                (
                    await db.scalars(
                        select(Event)
                        .where(Event.id.in_(chunk))
                        .options(
                            load_only(
                                Event.id,
                                Event.title_orig,
                                Event.venue_name,
                                Event.venue_id,
                            ),
                            selectinload(Event.venue),
                        )
                    )
                ).all()
            )
        for shown_ev in shown_event_rows:
            key = event_series_key(shown_ev.title_orig, resolve_venue_name(shown_ev))
            for uid in shown_event_users[shown_ev.id]:
                recent_series_by_user.setdefault(uid, set()).add(key)
    return recent_series_by_user


async def _load_candidate_events(
    db: AsyncSession, now: datetime
) -> tuple[list[Event], dict[int, tuple[str, str]], dict[int, _EventFactors]]:
    """Bulk-load published, non-excluded, upcoming-within-lookahead candidate
    events. Identical query for every page of users within one
    build_daily_feeds run — see _SharedFeedContext. Collapses same-series
    duplicates (see collapse_series_duplicates) before returning, along with
    each survivor's series key and its precomputed per-event score factors
    (see _precompute_event_factors)."""
    cutoff = now + timedelta(days=DAILY_5_LOOKAHEAD_DAYS)
    event_rows = list(
        (
            await db.scalars(
                select_events_with_classification().where(
                    public_event_filter(),
                    event_not_ended_filter(now),
                    Event.starts_at <= cutoff,
                    canonical_event_filter(),
                )
            )
        ).all()
    )
    collapsed, candidate_series_key = collapse_series_duplicates(event_rows)
    return collapsed, candidate_series_key, _precompute_event_factors(collapsed, now)


async def _verified_user_ids(db: AsyncSession) -> list[int]:
    """Verified user ids, paged by build_daily_feeds — see FEED_BUILD_USER_BATCH_SIZE.
    Filters on email_verified, not on persona/onboarding state — see the reverted
    _eligible_user_ids attempt in git history for why a persona-based filter is
    wrong (NEUTRAL_SCORE means a zero-persona user can still get a real feed).
    email_verified is different: a session token can only be issued from inside
    verify_magic_link, so an unverified row is provably one nobody has ever been
    able to log into — no feed or digest is reachable for it, so skipping it here
    wastes no legitimate value and closes the unverified-signup digest-spam gap."""
    return list(
        (await db.scalars(select(User.id).where(User.email_verified == true()))).all()
    )


async def _load_feed_build_context(
    db: AsyncSession,
    now: datetime,
    today: date,
    only_user_ids: list[int] | None = None,
    shared: _SharedFeedContext | None = None,
) -> _FeedBuildContext | None:
    """Bulk-load candidates plus all per-user data. None when there are no users.

    `only_user_ids` scopes the user query to a single user (or a small set) —
    used by `build_daily_feed_for_user` at onboarding completion. Every
    downstream lookup already filters by the loaded `user_ids`, so no other
    change is needed to build a feed for a subset of users.

    `shared` lets a paged caller (build_daily_feeds) pass in the candidate
    events + series keys once instead of re-running the identical query per
    page; when None (the default), it's loaded here exactly as before."""
    if shared is None:
        event_rows, candidate_series_key, event_factors = await _load_candidate_events(
            db, now
        )
        shared = _SharedFeedContext(
            event_rows=event_rows,
            candidate_series_key=candidate_series_key,
            event_factors=event_factors,
        )
    event_rows = shared.event_rows
    candidate_event_ids = [e.id for e in event_rows]

    users_query = select(User)
    if only_user_ids is not None:
        users_query = users_query.where(User.id.in_(only_user_ids))
    users = list((await db.scalars(users_query)).all())
    user_ids = [u.id for u in users]
    if not users:
        return None

    personas_by_user: dict[int, list[tuple[float, dict]]] = {uid: [] for uid in user_ids}
    up_rows = (
        await db.scalars(
            select(UserPersona)
            .where(UserPersona.user_id.in_(user_ids))
            .options(selectinload(UserPersona.persona))
        )
    ).all()
    for up_row in up_rows:
        personas_by_user.setdefault(up_row.user_id, []).append(
            persona_weight_tuple(up_row)
        )

    fb_by_user: dict[int, list[UserEventFeedback]] = {uid: [] for uid in user_ids}
    fb_rows = (
        await db.scalars(
            select(UserEventFeedback)
            .where(
                UserEventFeedback.user_id.in_(user_ids),
                UserEventFeedback.signal.in_((SIGNAL_LIKE, SIGNAL_DISLIKE)),
                # Likes older than the lookback are numerically negligible
                # (0.9^days decay) — same bound as browse.py's
                # _load_feedback_context. Dislikes are kept regardless: a
                # dislike is a hard exclude, not a decayed weight (Big-O
                # audit M2).
                or_(
                    UserEventFeedback.created_at
                    >= now - timedelta(days=FEEDBACK_HISTORY_LOOKBACK_DAYS),
                    UserEventFeedback.signal == SIGNAL_DISLIKE,
                ),
            )
            .options(
                selectinload(UserEventFeedback.event).selectinload(
                    Event.classification
                )
            )
        )
    ).all()
    for fb_row in fb_rows:
        fb_by_user.setdefault(fb_row.user_id, []).append(fb_row)

    recent_series_by_user = await _load_recent_series_by_user(db, user_ids, today)

    # Cached scores: the feedback router DELETEs the (user, event) row on
    # signal change, so an existing row reflects the most recent signal.
    # Chunked on event_id — user_ids is already bounded (≤500), but the 14-day
    # candidate pool has no such ceiling, and SQLAlchemy expands each `IN` to
    # one bind parameter per element. Past ~32k candidates this would hit
    # Postgres's per-statement parameter limit, the same one
    # SCORE_INSERT_CHUNK_SIZE exists to respect on the write side.
    score_cache: dict[tuple[int, int], float] = {}
    event_ids = list(candidate_event_ids)
    for i in range(0, len(event_ids), SCORE_INSERT_CHUNK_SIZE):
        chunk = event_ids[i : i + SCORE_INSERT_CHUNK_SIZE]
        # Column tuples, not ORM rows: this is U x chunk rows per page, and
        # hydrating a UserEventScore object per row cost ~1M objects/page
        # (Big-O audit M1).
        ues_rows = (
            await db.execute(
                select(
                    UserEventScore.user_id,
                    UserEventScore.event_id,
                    UserEventScore.score,
                ).where(
                    UserEventScore.user_id.in_(user_ids),
                    UserEventScore.event_id.in_(chunk),
                )
            )
        ).all()
        for ues_user_id, ues_event_id, ues_score in ues_rows:
            score_cache[(ues_user_id, ues_event_id)] = ues_score

    return _FeedBuildContext(
        shared=shared,
        users=users,
        personas_by_user=personas_by_user,
        fb_by_user=fb_by_user,
        recent_series_by_user=recent_series_by_user,
        score_cache=score_cache,
    )


def _score_user_candidates(
    user: User,
    build_ctx: _FeedBuildContext,
    fb_ctx: FeedbackContext,
    new_score_rows: list[dict],
    now: datetime,
) -> tuple[list[tuple[float, Event]], list[tuple[float, Event]], int]:
    """Score every candidate for one user, splitting series-cooled events into
    the backfill-only pool. Appends freshly computed scores to new_score_rows.
    Returns (scored, cooled_scored, scores_reused)."""
    user_persona_weights = build_ctx.personas_by_user.get(user.id, [])
    recent_series = build_ctx.recent_series_by_user.get(user.id, set())
    scores_reused = 0

    def _score_or_reuse(event: Event) -> float | None:
        """Cache lookup with a dislike re-check, else fresh score_event + cache write.
        Returns None when hard-excluded (dedup-group dislike, or cached-and-disliked)."""
        nonlocal scores_reused
        cached = build_ctx.score_cache.get((user.id, event.id))
        if cached is not None:
            # Re-check dislike independently of cache freshness: covers both
            # direct event dislikes and dedup_group dislikes so the cache path
            # stays correct under any future invalidation tightening.
            if event.id in fb_ctx.disliked_event_ids or (
                event.dedup_group_id is not None
                and event.dedup_group_id in fb_ctx.disliked_groups
            ):
                return None
            scores_reused += 1
            return cached

        s = score_event(
            user_persona_weights,
            fb_ctx,
            event,
            now,
            precomputed=build_ctx.event_factors.get(event.id),
            affinity_cache=build_ctx.affinity_cache,
        )
        if s is None:
            return None
        new_score_rows.append(
            {"user_id": user.id, "event_id": event.id, "score": s, "computed_at": now}
        )
        return s

    scored: list[tuple[float, Event]] = []
    cooled_scored: list[tuple[float, Event]] = []
    for event in build_ctx.event_rows:
        s = _score_or_reuse(event)
        if s is None:
            continue
        # Series cooldown: a candidate whose recurring series this user was
        # already shown within the window goes to the backfill-only pool —
        # still scored and cached, only consumed if the fresh pool can't reach n.
        if build_ctx.candidate_series_key[event.id] in recent_series:
            cooled_scored.append((s, event))
        else:
            scored.append((s, event))
    return scored, cooled_scored, scores_reused


async def _persist_new_scores(db: AsyncSession, new_score_rows: list[dict]) -> None:
    """Bulk upsert newly computed (user_id, event_id) scores.

    Chunked at SCORE_INSERT_CHUNK_SIZE rows/statement — new_score_rows
    accumulates one row per (user x cache-missing candidate event) across the
    whole build_daily_feeds run, and a single unchunked statement can exceed
    the Postgres wire protocol's ~32767 bind-parameter cap (4 params/row) once
    the score cache is mostly cold (see SCORE_INSERT_CHUNK_SIZE)."""
    for i in range(0, len(new_score_rows), SCORE_INSERT_CHUNK_SIZE):
        chunk = new_score_rows[i : i + SCORE_INSERT_CHUNK_SIZE]
        stmt = pg_insert(UserEventScore).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "event_id"],
            set_={"score": stmt.excluded.score, "computed_at": stmt.excluded.computed_at},
        )
        await db.execute(stmt)


async def _persist_daily_feeds(db: AsyncSession, daily_feed_rows: list[dict]) -> None:
    """Bulk upsert DailyFeed rows keyed on (user_id, feed_date).

    An ON CONFLICT DO UPDATE — rather than a pre-loaded existing-row lookup
    plus a plain INSERT — so the synchronous onboarding-completion build
    (`build_daily_feed_for_user`) racing the 06:00 scheduled `build_daily_feeds`
    job for the same user resolves atomically at the DB level instead of
    raising a unique-violation on the `(user_id, feed_date)` constraint that
    would roll back the whole batch's single commit.

    Chunked at SCORE_INSERT_CHUNK_SIZE rows/statement for the same
    bind-parameter-limit reason as _persist_new_scores — this table has fewer
    params/row (3 vs 4) so it survives longer, but the chunking is kept
    uniform across both callers rather than only guarding the tighter one."""
    for i in range(0, len(daily_feed_rows), SCORE_INSERT_CHUNK_SIZE):
        chunk = daily_feed_rows[i : i + SCORE_INSERT_CHUNK_SIZE]
        stmt = pg_insert(DailyFeed).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "feed_date"],
            set_={
                "event_ids": stmt.excluded.event_ids,
                "built_at": stmt.excluded.built_at,
            },
        )
        await db.execute(stmt)


def _build_one_user_feed(
    user: User,
    build_ctx: _FeedBuildContext,
    new_score_rows: list[dict],
    now: datetime,
) -> tuple[list[int], int]:
    """Score and select one user's Daily 5 candidates.

    Returns (event_ids, scores_reused). Persisting the resulting DailyFeed
    row is the caller's job (see `_persist_daily_feeds`) so callers can batch
    every user's row into a single upsert statement."""
    fb_ctx = FeedbackContext.from_orm_rows(list(build_ctx.fb_by_user.get(user.id, [])))
    scored, cooled_scored, reused = _score_user_candidates(
        user, build_ctx, fb_ctx, new_score_rows, now
    )

    top_events = _select_with_backfill(
        scored,
        cooled_scored,
        n=DAILY_5_COUNT,
        max_per_category=DAILY_5_MAX_PER_CATEGORY,
        backfill_max_per_category=DAILY_5_BACKFILL_MAX_PER_CATEGORY,
    )
    return [e.id for e in top_events], reused


async def build_daily_feeds(db: AsyncSession) -> dict:
    """
    Build personalized Daily 5 feeds for all active users.
    Runs at 06:00 Europe/Tallinn via APScheduler.

    Pages the full user loop at FEED_BUILD_USER_BATCH_SIZE so memory is
    bounded by a batch size instead of total registered users — candidate
    events + series keys are loaded once (_SharedFeedContext) and reused
    across every page; only personas/feedback/score-cache are reloaded
    per page. Filtered to verified users only (see _verified_user_ids); no
    persona-based pre-filtering beyond that — a user with zero personas can
    still get a non-empty feed and is opted into the digest by default.
    Caches per-(user, event) scores in `user_event_scores`. The feedback
    router invalidates cache rows on signal change so reused scores reflect
    the latest signal-state. Returns summary dict for logging.
    """
    now = datetime.now(TALLINN_TZ)
    today = now.date()

    user_ids = await _verified_user_ids(db)
    if not user_ids:
        return {
            "built": 0,
            "empty": 0,
            "total_users": 0,
            "candidate_events": 0,
            "scores_written": 0,
            "scores_reused": 0,
        }

    event_rows, candidate_series_key, event_factors = await _load_candidate_events(db, now)
    shared = _SharedFeedContext(
        event_rows=event_rows,
        candidate_series_key=candidate_series_key,
        event_factors=event_factors,
    )

    built = empty = scores_reused = scores_written = total_users = 0

    for i in range(0, len(user_ids), FEED_BUILD_USER_BATCH_SIZE):
        page_ids = user_ids[i : i + FEED_BUILD_USER_BATCH_SIZE]
        build_ctx = await _load_feed_build_context(
            db, now, today, only_user_ids=page_ids, shared=shared
        )
        if build_ctx is None:
            continue
        new_score_rows: list[dict] = []
        daily_feed_rows: list[dict] = []
        for user in build_ctx.users:
            event_ids, reused = _build_one_user_feed(user, build_ctx, new_score_rows, now)
            scores_reused += reused
            daily_feed_rows.append(
                {
                    "user_id": user.id,
                    "feed_date": today,
                    "event_ids": event_ids,
                    "built_at": now,
                }
            )
            if event_ids:
                built += 1
            else:
                empty += 1
        await _persist_new_scores(db, new_score_rows)
        await _persist_daily_feeds(db, daily_feed_rows)
        await db.commit()
        total_users += len(build_ctx.users)
        scores_written += len(new_score_rows)

    return {
        "built": built,
        "empty": empty,
        "total_users": total_users,
        "candidate_events": len(event_rows),
        "scores_written": scores_written,
        "scores_reused": scores_reused,
    }


async def build_daily_feed_for_user(db: AsyncSession, user_id: int) -> dict:
    """Build (or rebuild) today's Daily 5 for one user.

    Called synchronously at onboarding completion so a new user sees a
    populated feed immediately instead of waiting for the 06:00 job. Reuses
    the same candidate loading, scoring, series-cooldown, and score-caching
    logic as `build_daily_feeds` — no duplicated ranking logic. The upsert in
    `_persist_daily_feeds` means this can safely race the scheduled job for
    the same user without either write failing."""
    now = datetime.now(TALLINN_TZ)
    today = now.date()

    build_ctx = await _load_feed_build_context(db, now, today, only_user_ids=[user_id])
    if build_ctx is None:
        return {"built": 0, "empty": 0, "total_users": 0, "candidate_events": 0}

    new_score_rows: list[dict] = []
    user = build_ctx.users[0]
    event_ids, reused = _build_one_user_feed(user, build_ctx, new_score_rows, now)

    await _persist_new_scores(db, new_score_rows)
    await _persist_daily_feeds(
        db, [{"user_id": user.id, "feed_date": today, "event_ids": event_ids, "built_at": now}]
    )
    await db.commit()
    return {
        "built": 1 if event_ids else 0,
        "empty": 0 if event_ids else 1,
        "total_users": 1,
        "candidate_events": len(build_ctx.event_rows),
        "scores_written": len(new_score_rows),
        "scores_reused": reused,
    }
