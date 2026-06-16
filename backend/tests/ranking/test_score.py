"""Unit tests for the scoring formula — no DB, all pure functions."""
from datetime import datetime, timedelta
from typing import cast
from unittest.mock import MagicMock

from app.constants import SCORE_HARD_EXCLUDE, TALLINN_TZ
from app.models.models import Event
from app.ranking.score import (
    FeedbackContext,
    _FeedbackRow,
    _affinity_for_vector,
    _mmr_pick,
    _time_slots_for_event,
    feedback_signal,
    locality_bonus,
    persona_affinity,
    recency_boost,
    score_event,
)


def _now() -> datetime:
    return datetime(2026, 5, 10, 9, 0, 0, tzinfo=TALLINN_TZ)


def _event(
    event_id: int = 1,
    starts_at: datetime | None = None,
    categories: list[str] | None = None,
    vibes: list[str] | None = None,
    quality: float = 0.7,
    lat: float = 59.437,
    lng: float = 24.745,
    dedup_group: int | None = None,
) -> Event:
    e = MagicMock()
    e.id = event_id
    e.starts_at = starts_at or (_now() + timedelta(days=2))
    e.lat = lat
    e.lng = lng
    e.dedup_group_id = dedup_group
    cl = MagicMock()
    cl.categories = categories or ["music"]
    cl.vibes = vibes or ["underground"]
    cl.quality_score = quality
    e.classification = cl
    return cast(Event, e)


def _ctx(*rows: tuple[str, int, list[str], int | None, datetime]) -> FeedbackContext:
    fb_rows = [
        _FeedbackRow(signal=sig, event_id=eid, categories=cats, dedup_group_id=grp, created_at=ts)
        for sig, eid, cats, grp, ts in rows
    ]
    disliked_groups = frozenset(
        r.dedup_group_id
        for r in fb_rows
        if r.signal == "dislike" and r.dedup_group_id is not None
    )
    disliked_event_ids = frozenset(r.event_id for r in fb_rows if r.signal == "dislike")
    direct_map: dict[int, list[_FeedbackRow]] = {}
    for r in fb_rows:
        direct_map.setdefault(r.event_id, []).append(r)
    liked_rows = [r for r in fb_rows if r.signal == "like"]
    return FeedbackContext(
        rows=fb_rows,
        disliked_groups=disliked_groups,
        disliked_event_ids=disliked_event_ids,
        direct_map=direct_map,
        liked_rows=liked_rows,
    )


# ---------------------------------------------------------------------------
# _affinity_for_vector
# ---------------------------------------------------------------------------


class TestAffinityForVector:
    def test_perfect_match_all_categories(self):
        v = {"categories": {"music": 1.0}, "vibes": {"underground": 1.0}}
        # raw=2.0, max_possible=2.0 → normalized=1.0 → [0,1] = 1.0
        assert _affinity_for_vector(v, ["music"], ["underground"]) == 1.0

    def test_partial_match_discriminates(self):
        # Events matching only one of two persona categories should score < full match
        v = {"categories": {"music": 1.0, "nightlife": 1.0}, "vibes": {}}
        full = _affinity_for_vector(v, ["music", "nightlife"], [])
        partial = _affinity_for_vector(v, ["music"], [])
        assert full > partial  # normalization ensures discrimination

    def test_no_match_returns_half(self):
        v = {"categories": {"nightlife": 1.0}, "vibes": {}}
        # raw=0, max_possible=1 → normalized=0 → [0,1] = 0.5
        assert _affinity_for_vector(v, ["theater"], ["casual"]) == 0.5

    def test_empty_vector(self):
        assert _affinity_for_vector({}, ["music"], ["trendy"]) == 0.5

    def test_partial_match_value(self):
        v = {"categories": {"music": 1.0, "nightlife": 1.0}, "vibes": {}}
        # raw=1.0, max_possible=2.0 → normalized=0.5 → [0,1] = 0.75
        result = _affinity_for_vector(v, ["music"], [])
        assert abs(result - 0.75) < 1e-9

    def test_all_negative_weights_returns_neutral(self):
        # All-negative weights have max_possible <= 0 → neutral 0.5 (no meaningful signal)
        v = {"categories": {"music": -0.5}, "vibes": {}}
        assert _affinity_for_vector(v, ["music"], []) == 0.5

    def test_time_match_boosts_score(self):
        v = {"categories": {"music": 1.0}, "vibes": {}, "times": {"weekend": 1.0}}
        no_time = _affinity_for_vector(v, ["music"], [], [])
        with_time = _affinity_for_vector(v, ["music"], [], ["weekend"])
        assert with_time > no_time

    def test_time_miss_does_not_boost(self):
        v = {"categories": {"music": 1.0}, "vibes": {}, "times": {"weekend": 1.0}}
        assert _affinity_for_vector(v, ["music"], [], ["weekday"]) == _affinity_for_vector(v, ["music"], [], [])

    def test_multiple_time_slots_accumulate(self):
        # Saturday evening → both 'weekend' and 'evening' match
        v = {"categories": {}, "vibes": {}, "times": {"weekend": 0.5, "evening": 0.5}}
        single = _affinity_for_vector(v, [], [], ["weekend"])
        multi = _affinity_for_vector(v, [], [], ["weekend", "evening"])
        assert multi > single

    def test_perfect_category_vibe_match_beats_neutral_even_with_time_miss(self):
        # Calibration pin: time weights are part of max_possible, so a category+vibe perfect
        # match that misses the time preference scores lower than pre-times but still >> neutral.
        v = {"categories": {"music": 1.0}, "vibes": {"underground": 1.0}, "times": {"weekend": 1.0}}
        perfect_no_time = _affinity_for_vector(v, ["music"], ["underground"], [])
        neutral = _affinity_for_vector({}, [], [], [])  # empty vector → 0.5
        assert perfect_no_time > neutral


# ---------------------------------------------------------------------------
# _time_slots_for_event
# ---------------------------------------------------------------------------


class TestTimeSlotsForEvent:
    def _dt(self, weekday_offset: int, hour: int) -> datetime:
        # 2026-05-10 is a Sunday (weekday=6). offset 0=Sun, -1=Sat, -2=Fri, etc.
        base = datetime(2026, 5, 10, 0, 0, tzinfo=TALLINN_TZ)
        return base + timedelta(days=weekday_offset, hours=hour)

    def test_late_night_hour_22(self):
        slots = _time_slots_for_event(self._dt(0, 22))
        assert "late_night" in slots

    def test_late_night_hour_2(self):
        slots = _time_slots_for_event(self._dt(0, 2))
        assert "late_night" in slots

    def test_evening(self):
        slots = _time_slots_for_event(self._dt(0, 19))
        assert "evening" in slots
        assert "late_night" not in slots

    def test_daytime(self):
        slots = _time_slots_for_event(self._dt(0, 14))
        assert "daytime" in slots

    def test_morning(self):
        slots = _time_slots_for_event(self._dt(0, 7))
        assert "morning" in slots

    def test_weekend_sunday(self):
        slots = _time_slots_for_event(self._dt(0, 14))  # Sunday
        assert "weekend" in slots
        assert "weekday" not in slots

    def test_weekend_saturday(self):
        slots = _time_slots_for_event(self._dt(-1, 14))  # Saturday
        assert "weekend" in slots

    def test_weekday_friday(self):
        slots = _time_slots_for_event(self._dt(-2, 14))  # Friday
        assert "weekday" in slots
        assert "weekend" not in slots

    def test_saturday_evening_both_slots(self):
        slots = _time_slots_for_event(self._dt(-1, 20))  # Saturday 20:00
        assert "weekend" in slots
        assert "evening" in slots


# ---------------------------------------------------------------------------
# persona_affinity
# ---------------------------------------------------------------------------


class TestPersonaAffinity:
    def test_no_personas_returns_half(self):
        assert persona_affinity([], ["music"], ["underground"]) == 0.5

    def test_single_persona_full_match(self):
        v = {"categories": {"music": 1.0}, "vibes": {}}
        # raw = 1.0 → clipped → 1.0 → [0,1] = 1.0
        result = persona_affinity([(1.0, v)], ["music"], [])
        assert result == 1.0

    def test_weighted_blend(self):
        primary = {"categories": {"music": 1.0}, "vibes": {}}     # affinity = 1.0
        secondary = {"categories": {"theater": 1.0}, "vibes": {}} # affinity = 0.5 (no match)
        result = persona_affinity([(1.0, primary), (0.4, secondary)], ["music"], [])
        # = (1.0*1.0 + 0.4*0.5) / 1.4 = (1.0 + 0.2) / 1.4 ≈ 0.857
        expected = (1.0 * 1.0 + 0.4 * 0.5) / 1.4
        assert abs(result - expected) < 1e-9

    def test_zero_weight_returns_half(self):
        assert persona_affinity([(0.0, {})], ["music"], []) == 0.5


# ---------------------------------------------------------------------------
# recency_boost
# ---------------------------------------------------------------------------


class TestRecencyBoost:
    def test_today_is_one(self):
        now = _now()
        assert recency_boost(now, now) == 1.0

    def test_21_days_is_zero(self):
        now = _now()
        assert recency_boost(now + timedelta(days=21), now) == 0.0

    def test_past_is_zero(self):
        now = _now()
        assert recency_boost(now - timedelta(hours=1), now) == 0.0

    def test_10_days_is_half(self):
        now = _now()
        result = recency_boost(now + timedelta(days=10.5), now)
        assert abs(result - 0.5) < 0.01

    def test_linear_decay(self):
        now = _now()
        b7 = recency_boost(now + timedelta(days=7), now)
        b14 = recency_boost(now + timedelta(days=14), now)
        assert abs(b7 - 2 * b14) < 1e-9  # exactly linear


# ---------------------------------------------------------------------------
# feedback_signal
# ---------------------------------------------------------------------------


class TestFeedbackSignal:
    def test_no_feedback_returns_zero(self):
        ctx = _ctx()
        assert feedback_signal(1, ["music"], None, ctx, _now()) == 0.0

    def test_direct_like_returns_positive(self):
        ctx = _ctx(("like", 1, ["music"], None, _now()))
        result = feedback_signal(1, ["music"], None, ctx, _now())
        assert result > 0.0
        assert result <= 1.0

    def test_direct_dislike_returns_negative(self):
        ctx = _ctx(("dislike", 1, ["music"], None, _now()))
        result = feedback_signal(1, ["music"], None, ctx, _now())
        assert result < 0.0

    def test_disliked_dedup_group_hard_excludes(self):
        ctx = _ctx(("dislike", 99, ["music"], 7, _now()))
        # Event with same dedup_group_id=7 should return the hard-exclude sentinel
        result = feedback_signal(2, ["music"], 7, ctx, _now())
        assert result == SCORE_HARD_EXCLUDE

    def test_different_dedup_group_not_excluded(self):
        ctx = _ctx(("dislike", 99, ["music"], 7, _now()))
        result = feedback_signal(2, ["music"], 8, ctx, _now())
        assert result != -1.0

    def test_indirect_like_via_shared_category(self):
        ctx = _ctx(("like", 99, ["music"], None, _now()))
        result = feedback_signal(1, ["music"], None, ctx, _now())
        assert result > 0.0

    def test_indirect_like_no_shared_category(self):
        ctx = _ctx(("like", 99, ["theater"], None, _now()))
        result = feedback_signal(1, ["music"], None, ctx, _now())
        assert result == 0.0

    def test_signal_decays_with_time(self):
        old = _now() - timedelta(days=30)
        ctx_recent = _ctx(("like", 1, ["music"], None, _now()))
        ctx_old = _ctx(("like", 1, ["music"], None, old))
        recent_sig = feedback_signal(1, ["music"], None, ctx_recent, _now())
        old_sig = feedback_signal(1, ["music"], None, ctx_old, _now())
        assert recent_sig > old_sig

    def test_result_clipped_to_minus_one(self):
        # Multiple dislikes shouldn't go below -1
        ctx = _ctx(
            ("dislike", 1, ["music"], None, _now()),
            ("dislike", 1, ["music"], None, _now()),
        )
        result = feedback_signal(1, ["music"], None, ctx, _now())
        assert result >= -1.0


# ---------------------------------------------------------------------------
# locality_bonus
# ---------------------------------------------------------------------------


class TestLocalityBonus:
    def test_tallinn_centre_is_one(self):
        assert locality_bonus(59.437, 24.745) == 1.0

    def test_unknown_location_is_half(self):
        assert locality_bonus(None, None) == 0.5
        assert locality_bonus(59.4, None) == 0.5

    def test_outside_tallinn_is_zero(self):
        assert locality_bonus(56.946, 24.105) == 0.0  # Riga


# ---------------------------------------------------------------------------
# score_event
# ---------------------------------------------------------------------------


class TestScoreEvent:
    def test_returns_float_in_range(self):
        e = _event()
        v = {"categories": {"music": 1.0}, "vibes": {"underground": 1.0}}
        ctx = _ctx()
        result = score_event([(1.0, v)], ctx, e, _now())
        assert result is not None
        assert 0.0 <= result <= 1.0

    def test_hard_excluded_returns_none(self):
        e = _event(dedup_group=5)
        ctx = _ctx(("dislike", 99, ["music"], 5, _now()))
        result = score_event([], ctx, e, _now())
        assert result is None

    def test_no_classification_uses_defaults(self):
        e = _event()
        e.classification = None
        ctx = _ctx()
        result = score_event([], ctx, e, _now())
        assert result is not None
        assert 0.0 <= result <= 1.0

    def test_high_affinity_scores_higher_than_no_affinity(self):
        e = _event()
        v_match = {"categories": {"music": 1.0}, "vibes": {"underground": 1.0}}
        v_miss = {"categories": {"theater": 1.0}, "vibes": {}}
        ctx = _ctx()
        now = _now()
        score_match = score_event([(1.0, v_match)], ctx, e, now)
        score_miss = score_event([(1.0, v_miss)], ctx, e, now)
        assert score_match is not None
        assert score_miss is not None
        assert score_match > score_miss


# ---------------------------------------------------------------------------
# _mmr_pick
# ---------------------------------------------------------------------------


class TestMmrPick:
    def _make_event(self, eid: int, categories: list[str], score: float):
        e = _event(event_id=eid, categories=categories)
        return (score, e)

    def test_picks_top_n(self):
        # Use distinct categories so the per-category cap doesn't block selection
        cats = ["music", "theater", "cinema", "sports", "workshops",
                "nightlife", "family", "exhibitions", "literature", "food_drink"]
        scored = [self._make_event(i, [cats[i]], 1.0 - i * 0.05) for i in range(10)]
        picked = _mmr_pick(scored, n=5, max_per_category=2)
        assert len(picked) == 5

    def test_category_cap_enforced(self):
        # 3 music events, cap=2 → only 2 music picked
        scored = [
            self._make_event(1, ["music"], 0.9),
            self._make_event(2, ["music"], 0.8),
            self._make_event(3, ["music"], 0.7),
            self._make_event(4, ["theater"], 0.6),
        ]
        picked = _mmr_pick(scored, n=4, max_per_category=2)
        music = [
            e
            for e in picked
            if "music" in (e.classification.categories if e.classification else [])
        ]
        assert len(music) == 2
        assert any(e.id == 4 for e in picked)

    def test_no_categories_bypass_cap(self):
        e = _event(event_id=1, categories=[])
        assert e.classification is not None
        e.classification.categories = []
        scored = [(0.9, e)]
        picked = _mmr_pick(scored, n=5, max_per_category=1)
        assert len(picked) == 1

    def test_empty_input(self):
        assert _mmr_pick([], n=5, max_per_category=2) == []

    def test_fewer_events_than_n(self):
        scored = [self._make_event(i, ["music"], 0.9) for i in range(2)]
        picked = _mmr_pick(scored, n=5, max_per_category=5)
        assert len(picked) == 2


class TestBuildDailyFeedsExplicitFilter:
    async def test_event_query_excludes_explicit_events(self, mock_db):
        from app.ranking.score import build_daily_feeds

        empty = MagicMock()
        empty.all.return_value = []
        mock_db.scalars.return_value = empty

        result = await build_daily_feeds(mock_db)

        assert result["total_users"] == 0
        stmt = mock_db.scalars.call_args_list[0].args[0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "is_explicit" in compiled
        assert "false" in compiled.lower()
