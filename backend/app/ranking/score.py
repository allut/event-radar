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
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.constants import (
    DAILY5_SERIES_COOLDOWN_DAYS,
    DAILY_5_BACKFILL_MAX_PER_CATEGORY,
    DAILY_5_COUNT,
    DAILY_5_LOOKAHEAD_DAYS,
    DAILY_5_MAX_PER_CATEGORY,
    EVENT_STATUS_PUBLISHED,
    FEEDBACK_DECAY_BASE,
    FEEDBACK_INDIRECT_WEIGHT,
    NEUTRAL_SCORE,
    RECENCY_DECAY_DAYS,
    SCORE_HARD_EXCLUDE,
    SCORE_WEIGHT_AFFINITY,
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
    canonical_event_filter,
    event_not_ended_filter,
    event_series_key,
    select_events_with_classification,
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


def persona_affinity(
    user_persona_weights: list[tuple[float, dict]],
    categories: list[str],
    vibes: list[str],
    time_slots: Sequence[str] = (),
) -> float:
    """Weighted blend of persona affinities → [0, 1]. Returns NEUTRAL_SCORE with no personas."""
    if not user_persona_weights:
        return NEUTRAL_SCORE
    total_weight = sum(w for w, _ in user_persona_weights)
    if total_weight == 0:
        return NEUTRAL_SCORE
    weighted = sum(
        w * _affinity_for_vector(vec, categories, vibes, time_slots)
        for w, vec in user_persona_weights
    )
    return weighted / total_weight


def recency_boost(starts_at: datetime, now: datetime) -> float:
    """Linear decay 1.0 at starts_at == now to 0.0 at +21 days. 0.0 for past events."""
    delta_days = (starts_at - now).total_seconds() / SECONDS_PER_DAY
    if delta_days < 0:
        return 0.0
    return max(0.0, 1.0 - delta_days / RECENCY_DECAY_DAYS)


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

    event_cat_set = set(event_categories)
    signals: list[float] = []

    # Direct: O(1) dict lookup instead of O(F) full-row scan
    for row in ctx.direct_map.get(event_id, []):
        days = max(0.0, (now - row.created_at).total_seconds() / SECONDS_PER_DAY)
        decay = FEEDBACK_DECAY_BASE**days
        if row.signal == SIGNAL_LIKE:
            signals.append(decay)
        elif row.signal == SIGNAL_DISLIKE:
            signals.append(-1.0)

    # Indirect: iterate only liked rows, skipping the event itself
    for row in ctx.liked_rows:
        if row.event_id != event_id and event_cat_set & row.category_set:
            days = max(0.0, (now - row.created_at).total_seconds() / SECONDS_PER_DAY)
            decay = FEEDBACK_DECAY_BASE**days
            signals.append(FEEDBACK_INDIRECT_WEIGHT * decay)

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


def score_event(
    user_persona_weights: list[tuple[float, dict]],
    ctx: FeedbackContext,
    event: Event,
    now: datetime,
) -> float | None:
    """
    Compute personalized score for one event. Returns None if hard-excluded.
    Score is in [0, 1].
    """
    cl: EventClassification | None = event.classification
    categories: list[str] = cl.categories if cl else []
    vibes: list[str] = cl.vibes if cl else []
    time_slots = _time_slots_for_event(event.starts_at)

    fb = feedback_signal(event.id, categories, event.dedup_group_id, ctx, now)
    if fb == SCORE_HARD_EXCLUDE:
        return None  # hard exclude

    affinity = persona_affinity(user_persona_weights, categories, vibes, time_slots)
    recency = recency_boost(event.starts_at, now)
    quality = cl.quality_score if cl and cl.quality_score is not None else NEUTRAL_SCORE
    locality = locality_bonus(event.lat, event.lng)
    fb_normalized = (fb + 1.0) / 2.0  # map [-1, 1] → [0, 1]

    return (
        SCORE_WEIGHT_AFFINITY * affinity
        + SCORE_WEIGHT_RECENCY * recency
        + SCORE_WEIGHT_FEEDBACK * fb_normalized
        + SCORE_WEIGHT_QUALITY * quality
        + SCORE_WEIGHT_LOCALITY * locality
    )


def _mmr_pick(
    scored: list[tuple[float, Event]], n: int, max_per_category: int
) -> list[Event]:
    """
    MMR-lite diversity pick: greedy top-n with at most max_per_category events per category.
    Events with no categories bypass the category cap.
    """
    category_counts: dict[str, int] = {}
    picked: list[Event] = []

    for _, event in sorted(scored, key=lambda x: x[0], reverse=True):
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
    pool: list[tuple[float, Event]],
    n: int,
    max_per_category: int | None,
) -> None:
    """Append highest-scored events from pool (not already picked) until len(picked) == n.
    When max_per_category is not None, skip an event whose category already hit the cap
    (events with no categories bypass it, matching _mmr_pick)."""
    for _, event in sorted(pool, key=lambda x: x[0], reverse=True):
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
    """
    picked = _mmr_pick(scored, n, max_per_category)
    if len(picked) >= n:
        return picked
    picked_ids = {e.id for e in picked}
    category_counts: dict[str, int] = {}
    for e in picked:
        for c in e.classification.categories if e.classification else []:
            category_counts[c] = category_counts.get(c, 0) + 1
    # relaxed-cap tiers (diversity preserved)
    _greedy_fill(
        picked, picked_ids, category_counts, scored, n, backfill_max_per_category
    )
    if len(picked) < n:
        _greedy_fill(
            picked,
            picked_ids,
            category_counts,
            cooled_scored,
            n,
            backfill_max_per_category,
        )
    # uncapped last resort (guarantee n when relaxed cap left it short)
    if len(picked) < n:
        _greedy_fill(picked, picked_ids, category_counts, scored, n, None)
    if len(picked) < n:
        _greedy_fill(picked, picked_ids, category_counts, cooled_scored, n, None)
    return picked


# ---------------------------------------------------------------------------
# Daily feed builder (async, touches DB)
# ---------------------------------------------------------------------------


async def build_daily_feeds(db: AsyncSession) -> dict:
    """
    Build personalized Daily 5 feeds for all active users.
    Runs at 06:00 Europe/Tallinn via APScheduler.

    Bulk-loads all per-user data in a fixed number of queries (independent of
    user count) and caches per-(user, event) scores in `user_event_scores`.
    The feedback router invalidates cache rows on signal change so reused
    scores reflect the latest signal-state at write time.
    Returns summary dict for logging.
    """
    now = datetime.now(TALLINN_TZ)
    today = now.date()
    cutoff = now + timedelta(days=DAILY_5_LOOKAHEAD_DAYS)

    # Load all published events within the lookahead window
    event_rows = (
        await db.scalars(
            select_events_with_classification().where(
                Event.status == EVENT_STATUS_PUBLISHED,
                Event.is_explicit.is_(False),
                event_not_ended_filter(now),
                Event.starts_at <= cutoff,
                canonical_event_filter(),
            )
        )
    ).all()
    candidate_event_ids = [e.id for e in event_rows]

    users = (await db.scalars(select(User))).all()
    user_ids = [u.id for u in users]

    if not users:
        return {"built": 0, "empty": 0, "total_users": 0, "candidate_events": 0}

    # --- Bulk-fetch personas grouped by user_id ---
    personas_by_user: dict[int, list[tuple[float, dict]]] = {uid: [] for uid in user_ids}
    if user_ids:
        up_rows = (
            await db.scalars(
                select(UserPersona)
                .where(UserPersona.user_id.in_(user_ids))
                .options(selectinload(UserPersona.persona))
            )
        ).all()
        for up_row in up_rows:
            personas_by_user.setdefault(up_row.user_id, []).append(
                (up_row.weight, up_row.persona.affinity_vector)
            )

    # --- Bulk-fetch feedback grouped by user_id ---
    fb_by_user: dict[int, list[UserEventFeedback]] = {uid: [] for uid in user_ids}
    if user_ids:
        fb_rows = (
            await db.scalars(
                select(UserEventFeedback)
                .where(UserEventFeedback.user_id.in_(user_ids))
                .options(
                    selectinload(UserEventFeedback.event).selectinload(
                        Event.classification
                    )
                )
            )
        ).all()
        for fb_row in fb_rows:
            fb_by_user.setdefault(fb_row.user_id, []).append(fb_row)

    # --- Bulk-fetch today's DailyFeed rows (existing -> update; missing -> insert) ---
    daily_by_user: dict[int, DailyFeed] = {}
    if user_ids:
        df_rows = (
            await db.scalars(
                select(DailyFeed).where(
                    DailyFeed.user_id.in_(user_ids),
                    DailyFeed.feed_date == today,
                )
            )
        ).all()
        for df_row in df_rows:
            daily_by_user[df_row.user_id] = df_row

    # --- Bulk-fetch the recent cooldown window's feeds to suppress repeat
    # recommendations of the same recurring series across days. A multi-day
    # series (one canonical event per day) would otherwise score well and be
    # re-picked night after night. Independent of dedup_group_id — series are
    # intentionally not dedup-grouped across days; this is a feed-level filter. ---
    recent_series_by_user: dict[int, set[tuple[str, str]]] = {}
    if user_ids:
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
            # One bulk SELECT to resolve each shown event to its series key —
            # these may be outside the current lookahead window, so resolve them
            # directly rather than from event_rows.
            shown_event_rows = (
                await db.scalars(
                    select(Event).where(Event.id.in_(list(shown_event_users.keys())))
                )
            ).all()
            for shown_ev in shown_event_rows:
                key = event_series_key(shown_ev.title_orig, shown_ev.venue_name)
                for uid in shown_event_users[shown_ev.id]:
                    recent_series_by_user.setdefault(uid, set()).add(key)

    # Precompute each candidate's series key once (reused across all users).
    candidate_series_key: dict[int, tuple[str, str]] = {
        e.id: event_series_key(e.title_orig, e.venue_name) for e in event_rows
    }

    # --- Bulk-fetch cached scores for the (user_id, event_id) cartesian we care about ---
    # The feedback router DELETEs the (user, event) row on signal change, so an
    # existing row means "score reflects the most recent signal seen for that event".
    score_cache: dict[tuple[int, int], float] = {}
    if user_ids and candidate_event_ids:
        ues_rows = (
            await db.scalars(
                select(UserEventScore).where(
                    UserEventScore.user_id.in_(user_ids),
                    UserEventScore.event_id.in_(candidate_event_ids),
                )
            )
        ).all()
        for ues_row in ues_rows:
            score_cache[(ues_row.user_id, ues_row.event_id)] = ues_row.score

    built = 0
    empty = 0
    new_score_rows: list[dict] = []
    scores_reused = 0

    for user in users:
        user_persona_weights = personas_by_user.get(user.id, [])
        ctx = FeedbackContext.from_orm_rows(list(fb_by_user.get(user.id, [])))

        recent_series = recent_series_by_user.get(user.id, set())

        def _score_or_reuse(event: Event) -> float | None:
            """Cache lookup with a dislike re-check, else fresh score_event + cache write.
            Returns None when hard-excluded (dedup-group dislike, or cached-and-disliked)."""
            nonlocal scores_reused
            cached = score_cache.get((user.id, event.id))
            if cached is not None:
                # Re-check dislike independently of cache freshness: covers
                # both direct event dislikes and dedup_group dislikes so the
                # cache path stays correct under any future invalidation
                # tightening.
                if event.id in ctx.disliked_event_ids or (
                    event.dedup_group_id is not None
                    and event.dedup_group_id in ctx.disliked_groups
                ):
                    return None
                scores_reused += 1
                return cached

            s = score_event(user_persona_weights, ctx, event, now)
            if s is None:
                return None
            new_score_rows.append(
                {
                    "user_id": user.id,
                    "event_id": event.id,
                    "score": s,
                    "computed_at": now,
                }
            )
            return s

        scored: list[tuple[float, Event]] = []
        cooled_scored: list[tuple[float, Event]] = []
        for event in event_rows:
            # Series cooldown: route a candidate whose recurring series this
            # user was already shown within the cooldown window into the
            # backfill-only pool instead of the normal pool. Still scored and
            # cached like any other candidate; only consumed by
            # _select_with_backfill if the fresh pool can't reach n.
            if candidate_series_key[event.id] in recent_series:
                s = _score_or_reuse(event)
                if s is not None:
                    cooled_scored.append((s, event))
                continue

            s = _score_or_reuse(event)
            if s is None:
                continue
            scored.append((s, event))

        top_events = _select_with_backfill(
            scored,
            cooled_scored,
            n=DAILY_5_COUNT,
            max_per_category=DAILY_5_MAX_PER_CATEGORY,
            backfill_max_per_category=DAILY_5_BACKFILL_MAX_PER_CATEGORY,
        )
        event_ids = [e.id for e in top_events]

        existing = daily_by_user.get(user.id)
        if existing:
            existing.event_ids = event_ids
            existing.built_at = now
        else:
            db.add(
                DailyFeed(
                    user_id=user.id,
                    feed_date=today,
                    event_ids=event_ids,
                    built_at=now,
                )
            )

        if event_ids:
            built += 1
        else:
            empty += 1

    # Bulk upsert newly computed (user_id, event_id) scores.
    if new_score_rows:
        stmt = pg_insert(UserEventScore).values(new_score_rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["user_id", "event_id"],
            set_={"score": stmt.excluded.score, "computed_at": stmt.excluded.computed_at},
        )
        await db.execute(stmt)

    await db.commit()
    return {
        "built": built,
        "empty": empty,
        "total_users": len(users),
        "candidate_events": len(event_rows),
        "scores_written": len(new_score_rows),
        "scores_reused": scores_reused,
    }
