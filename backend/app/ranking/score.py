"""
Personalized event scoring.

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
from datetime import datetime
from functools import cached_property


from app.constants.core import SECONDS_PER_DAY, TALLINN_TZ
from app.constants.events import (
    TALLINN_CENTER_LAT,
    TALLINN_CENTER_LNG,
    TALLINN_LAT_DELTA,
    TALLINN_LNG_DELTA,
)
from app.constants.ranking import (
    FEEDBACK_DECAY_BASE,
    FEEDBACK_INDIRECT_WEIGHT,
    NEUTRAL_SCORE,
    RECENCY_DECAY_DAYS,
    SCORE_HARD_EXCLUDE,
    SCORE_WEIGHT_AFFINITY,
    SCORE_WEIGHT_ANON_LOCALITY,
    SCORE_WEIGHT_ANON_QUALITY,
    SCORE_WEIGHT_ANON_RECENCY,
    SCORE_WEIGHT_FEEDBACK,
    SCORE_WEIGHT_LOCALITY,
    SCORE_WEIGHT_QUALITY,
    SCORE_WEIGHT_RECENCY,
    SIGNAL_DISLIKE,
    SIGNAL_LIKE,
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
from app.models.events import Event, EventClassification
from app.models.feeds import UserEventFeedback
from app.models.users import Persona, UserPersona
from app.events.venue import resolve_venue_coords

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
    event into precompute_event_factors' result and threads it through as
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
    categories: Sequence[str],
    vibes: Sequence[str],
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
    categories: Sequence[str],
    vibes: Sequence[str],
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
    event_categories: Sequence[str],
    event_dedup_group: int | None,
    ctx: FeedbackContext,
    now: datetime,
    event_cat_set: frozenset[str] | None = None,
) -> float:
    """
    Feedback score in [-1, 1] for normal events.
    Returns SCORE_HARD_EXCLUDE (-2.0, deliberately outside the [-1, 1] range so it
    cannot collide with a legitimately disliked event's -1.0) when the event belongs
    to a disliked dedup_group; the caller skips the event entirely.

    ``event_cat_set`` is ``frozenset(event_categories)`` when the caller already
    holds it (the precomputed per-event factors); omitted, it is built here.
    """
    if event_dedup_group is not None and event_dedup_group in ctx.disliked_groups:
        return SCORE_HARD_EXCLUDE

    signals = _direct_feedback_signal(event_id, ctx, now)

    # No-op if already built for this `now` (the normal per-user-per-build
    # case) — self-healing for any caller that forgot to build.
    ctx.build_liked_aggregates(now)
    if event_cat_set is None:
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


# (recency, quality, locality, time_slots, categories, vibes, category_set)
EventFactors = tuple[
    float, float, float, tuple[str, ...], tuple[str, ...], tuple[str, ...], frozenset[str]
]


def precompute_event_factors(
    event_rows: list[Event], now: datetime
) -> dict[int, EventFactors]:
    """Per-event score inputs — invariant across every user.

    build_daily_feeds' inner loop calls score_event once per (user, candidate)
    pair; these factors depend only on the event and the run's fixed ``now``,
    so without this they're recomputed identically U times per event at U x E
    scale. Hoisted once here and threaded through as ``precomputed``. The tag
    tuples and category frozenset are built here too, so the affinity memo key
    and the indirect-feedback lookup allocate nothing per call.
    """
    factors: dict[int, EventFactors] = {}
    for event in event_rows:
        cl = event.classification
        quality = cl.quality_score if cl and cl.quality_score is not None else NEUTRAL_SCORE
        lat, lng = resolve_venue_coords(event)
        categories = tuple(cl.categories) if cl else ()
        factors[event.id] = (
            recency_boost(event.starts_at, now),
            quality,
            locality_bonus(lat, lng),
            tuple(_time_slots_for_event(event.starts_at)),
            categories,
            tuple(cl.vibes) if cl else (),
            frozenset(categories),
        )
    return factors


def score_event(
    user_persona_weights: list[tuple[float, dict]],
    ctx: FeedbackContext,
    event: Event,
    now: datetime,
    precomputed: EventFactors | None = None,
    affinity_cache: AffinityCache | None = None,
) -> float | None:
    """
    Compute personalized score for one event. Returns None if hard-excluded.
    Score is in [0, 1].

    ``precomputed`` is the tuple from ``precompute_event_factors`` — pass it
    from a caller iterating many users over the same candidate pool to skip
    recomputing these per-event-only values on every call. Callers scoring a
    single user's events ad hoc (e.g. browse.py) omit it and get the values
    computed inline, as before.
    """
    cl: EventClassification | None = event.classification
    categories: Sequence[str]
    vibes: Sequence[str]
    time_slots: Sequence[str]
    cat_set: frozenset[str] | None = None
    if precomputed is not None:
        recency, quality, locality, time_slots, categories, vibes, cat_set = precomputed
    else:
        categories = cl.categories if cl else []
        vibes = cl.vibes if cl else []

    fb = feedback_signal(
        event.id, categories, event.dedup_group_id, ctx, now, event_cat_set=cat_set
    )
    if fb == SCORE_HARD_EXCLUDE:
        return None  # hard exclude

    if precomputed is None:
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


def persona_weight_tuple(
    user_persona: UserPersona, persona: Persona | None = None
) -> tuple[float, dict]:
    """(weight, affinity_vector) shape consumed by ``ranking/score.py::persona_affinity``.

    Shared by the single-user load in browse.py and the bulk multi-user load in
    ranking/daily_feed.py::build_daily_feeds, which query ``UserPersona`` differently
    (single vs. ``user_id.in_(...)``) but must agree on this row->tuple mapping.
    ``persona`` covers routers/settings.py's ``(UserPersona, Persona)``-tuple
    join query, which loads the row directly rather than via the
    ``UserPersona.persona`` relationship; omit it when that relationship is
    already eager-loaded (browse.py/score.py both ``selectinload`` it).
    """
    return (
        user_persona.weight,
        (persona if persona is not None else user_persona.persona).affinity_vector,
    )
