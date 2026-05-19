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
from datetime import datetime, timedelta
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.constants import (
    DAILY_5_COUNT,
    DAILY_5_LOOKAHEAD_DAYS,
    DAILY_5_MAX_PER_CATEGORY,
    EVENT_STATUS_PUBLISHED,
    FEEDBACK_DECAY_BASE,
    FEEDBACK_INDIRECT_WEIGHT,
    RECENCY_DECAY_DAYS,
    SCORE_HARD_EXCLUDE,
    SCORE_WEIGHT_AFFINITY,
    SCORE_WEIGHT_FEEDBACK,
    SCORE_WEIGHT_LOCALITY,
    SCORE_WEIGHT_QUALITY,
    SCORE_WEIGHT_RECENCY,
    SECONDS_PER_DAY,
    TALLINN_CENTER_LAT,
    TALLINN_CENTER_LNG,
    TALLINN_LAT_DELTA,
    TALLINN_LNG_DELTA,
    TALLINN_TZ,
    TIME_DAYTIME_START,
    TIME_EVENING_START,
    TIME_LATE_NIGHT_START,
    TIME_MORNING_START,
)
from app.models.models import (
    DailyFeed,
    Event,
    EventClassification,
    User,
    UserEventFeedback,
    UserPersona,
)
from app.routers.utils import select_events_with_classification

# ---------------------------------------------------------------------------
# Feedback context (precomputed for one user, reused across event scoring)
# ---------------------------------------------------------------------------


@dataclass
class _FeedbackRow:
    signal: str
    event_id: int
    categories: list[str]
    dedup_group_id: Optional[int]
    created_at: datetime


@dataclass
class FeedbackContext:
    rows: list[_FeedbackRow] = field(default_factory=list)
    disliked_groups: frozenset[int] = field(default_factory=frozenset)

    @classmethod
    def from_orm_rows(cls, orm_rows: list[UserEventFeedback]) -> "FeedbackContext":
        rows: list[_FeedbackRow] = []
        for r in orm_rows:
            cats: list[str] = []
            dedup_group: Optional[int] = None
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
            if row.signal == "dislike" and row.dedup_group_id is not None
        )
        return cls(rows=rows, disliked_groups=disliked_groups)


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
        slots.append("late_night")
    elif hour >= TIME_EVENING_START:
        slots.append("evening")
    elif hour >= TIME_DAYTIME_START:
        slots.append("daytime")
    elif hour >= TIME_MORNING_START:
        slots.append("morning")
    if local.weekday() >= 5:
        slots.append("weekend")
    else:
        slots.append("weekday")
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
        return 0.5
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
    """Weighted blend of persona affinities → [0, 1]. Returns 0.5 when no personas."""
    if not user_persona_weights:
        return 0.5
    total_weight = sum(w for w, _ in user_persona_weights)
    if total_weight == 0:
        return 0.5
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
    event_dedup_group: Optional[int],
    ctx: FeedbackContext,
    now: datetime,
) -> float:
    """
    Feedback score in [-1, 1].
    Returns exactly -1.0 as a hard-exclude sentinel when the event belongs to a
    disliked dedup_group (caller should skip the event entirely).
    """
    if event_dedup_group is not None and event_dedup_group in ctx.disliked_groups:
        return SCORE_HARD_EXCLUDE

    event_cat_set = set(event_categories)
    signals: list[float] = []

    for row in ctx.rows:
        days = max(0.0, (now - row.created_at).total_seconds() / SECONDS_PER_DAY)
        decay = FEEDBACK_DECAY_BASE**days

        if row.event_id == event_id:
            if row.signal == "like":
                signals.append(decay)
            elif row.signal == "dislike":
                signals.append(-1.0)
        elif row.signal == "like" and event_cat_set & set(row.categories):
            # Indirect: liked another event that shares a category with this one
            signals.append(FEEDBACK_INDIRECT_WEIGHT * decay)

    if not signals:
        return 0.0
    return max(-1.0, min(1.0, sum(signals)))


def locality_bonus(lat: Optional[float], lng: Optional[float]) -> float:
    """1.0 if within central Tallinn bounding box; 0.5 when location unknown; 0.0 otherwise."""
    if lat is None or lng is None:
        return 0.5
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
) -> Optional[float]:
    """
    Compute personalized score for one event. Returns None if hard-excluded.
    Score is in [0, 1].
    """
    cl: Optional[EventClassification] = event.classification
    categories: list[str] = cl.categories if cl else []
    vibes: list[str] = cl.vibes if cl else []
    time_slots = _time_slots_for_event(event.starts_at)

    fb = feedback_signal(event.id, categories, event.dedup_group_id, ctx, now)
    if fb == SCORE_HARD_EXCLUDE:
        return None  # hard exclude

    affinity = persona_affinity(user_persona_weights, categories, vibes, time_slots)
    recency = recency_boost(event.starts_at, now)
    quality = cl.quality_score if cl and cl.quality_score is not None else 0.5
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


# ---------------------------------------------------------------------------
# Daily feed builder (async, touches DB)
# ---------------------------------------------------------------------------


async def build_daily_feeds(db: AsyncSession) -> dict:
    """
    Build personalized Daily 5 feeds for all active users.
    Runs at 06:00 Europe/Tallinn via APScheduler.
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
                Event.starts_at >= now,
                Event.starts_at <= cutoff,
            )
        )
    ).all()

    users = (await db.scalars(select(User))).all()

    built = 0
    empty = 0

    for user in users:
        # Persona weights with affinity vectors
        up_rows = (
            await db.scalars(
                select(UserPersona)
                .where(UserPersona.user_id == user.id)
                .options(selectinload(UserPersona.persona))
            )
        ).all()
        user_persona_weights: list[tuple[float, dict]] = [
            (row.weight, row.persona.affinity_vector) for row in up_rows
        ]

        # Feedback with event + classification for indirect category matching
        fb_rows = (
            await db.scalars(
                select(UserEventFeedback)
                .where(UserEventFeedback.user_id == user.id)
                .options(
                    selectinload(UserEventFeedback.event).selectinload(
                        Event.classification
                    )
                )
            )
        ).all()
        ctx = FeedbackContext.from_orm_rows(list(fb_rows))

        # Score each candidate event
        scored: list[tuple[float, Event]] = []
        for event in event_rows:
            s = score_event(user_persona_weights, ctx, event, now)
            if s is not None:
                scored.append((s, event))

        top_events = _mmr_pick(
            scored, n=DAILY_5_COUNT, max_per_category=DAILY_5_MAX_PER_CATEGORY
        )
        event_ids = [e.id for e in top_events]

        # Upsert daily feed (rebuild if already exists for today)
        existing = await db.scalar(
            select(DailyFeed).where(
                DailyFeed.user_id == user.id,
                DailyFeed.feed_date == today,
            )
        )
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

    await db.commit()
    return {
        "built": built,
        "empty": empty,
        "total_users": len(users),
        "candidate_events": len(event_rows),
    }
