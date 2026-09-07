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
    _select_with_backfill,
    _time_slots_for_event,
    anonymous_score_event,
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
    venue_id: int | None = None,
    venue: MagicMock | None = None,
) -> Event:
    e = MagicMock()
    e.id = event_id
    e.starts_at = starts_at or (_now() + timedelta(days=2))
    e.lat = lat
    e.lng = lng
    e.venue_id = venue_id
    e.venue = venue
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

    def test_liking_an_event_does_not_double_count_via_indirect(self):
        """Scoring the very event a user liked must only carry the direct term —
        the old per-row loop excluded any row with row.event_id == event_id from the
        indirect sum; the aggregated version must reproduce that exactly (verifies the
        liked_decay_by_event self-exclusion subtraction)."""
        ctx = _ctx(("like", 1, ["music"], None, _now()))
        result = feedback_signal(1, ["music"], None, ctx, _now())
        # A pure direct-like signal is FEEDBACK_DECAY_BASE**0 == 1.0 — if the event's
        # own like also leaked into the indirect sum, this would exceed 1.0 before the
        # final [-1, 1] clip (it wouldn't in practice since the clip hides it, so this
        # test relies on test_liked_decay_aggregated_by_distinct_category_set_not_per_row
        # plus test_duplicate_liked_rows_on_same_event_fully_excluded to catch the
        # underlying bug directly rather than through the clip).
        assert result == 1.0

    def test_duplicate_liked_rows_on_same_event_fully_excluded(self):
        """user_event_feedback has no unique constraint — two liked rows can share an
        event_id. Both must be excluded when scoring that event (matches the old loop,
        which skipped every row with row.event_id == event_id), not just one of them."""
        ctx = _ctx(
            ("like", 1, ["music"], None, _now()),
            ("like", 1, ["music"], None, _now()),
        )
        # Scoring event 1 itself: indirect must be fully cancelled regardless of the
        # duplicate, leaving only the two direct-like contributions (each 1.0, clipped).
        result = feedback_signal(1, ["music"], None, ctx, _now())
        assert result == 1.0  # direct signals clip at 1.0; no indirect leak-through

    def test_indirect_credit_from_other_event_survives_self_exclusion(self):
        """Self-exclusion must remove only the scored event's own share, not the
        contribution of a different liked event sharing the same category. Uses an
        old direct like (decayed well below 1.0) so the [-1, 1] clip can't mask the
        indirect contribution from event 99's like."""
        old = _now() - timedelta(days=30)
        with_other_indirect = feedback_signal(
            1, ["music"], None,
            _ctx(
                ("like", 1, ["music"], None, old),
                ("like", 99, ["music"], None, _now()),
            ),
            _now(),
        )
        direct_only = feedback_signal(
            1, ["music"], None,
            _ctx(("like", 1, ["music"], None, old)),
            _now(),
        )
        assert with_other_indirect > direct_only

    def test_multi_category_liked_row_credited_once_not_per_category(self):
        """A liked row with multiple categories must contribute its decay once to any
        overlapping event, not once per overlapping category (each row occupies exactly
        one bucket — its full category_set — not a bucket per individual category)."""
        ctx = _ctx(("like", 99, ["music", "theater"], None, _now()))
        overlap_one = feedback_signal(1, ["music"], None, ctx, _now())
        overlap_two = feedback_signal(1, ["music", "theater"], None, ctx, _now())
        # Same liked row, same bucket — overlapping on one category vs. both categories
        # must yield the identical indirect contribution (bucket-level, not per-category).
        assert overlap_one == overlap_two

    def test_liked_aggregates_lazily_built_and_cached_per_now(self):
        """build_liked_aggregates is idempotent per `now` — feedback_signal's internal
        call must not rebuild on every invocation for the same `now` (the O(1)-amortized
        contract the complexity fix depends on)."""
        ctx = _ctx(("like", 99, ["music"], None, _now()))
        now = _now()
        feedback_signal(1, ["music"], None, ctx, now)
        built_after_first = ctx._liked_aggregates_built_for
        feedback_signal(2, ["music"], None, ctx, now)
        assert ctx._liked_aggregates_built_for == built_after_first == now

    def test_liked_decay_aggregated_by_distinct_category_set_not_per_row(self):
        """Complexity proof: many liked rows sharing one category_set must collapse
        into a single liked_decay_by_catset bucket, not one entry per row — this is
        what makes feedback_signal O(distinct category-sets) instead of O(liked rows)."""
        many_rows = tuple(
            ("like", 100 + i, ["music"], None, _now()) for i in range(50)
        )
        ctx = _ctx(*many_rows)
        feedback_signal(1, ["theater"], None, ctx, _now())  # triggers the lazy build
        assert len(ctx.liked_decay_by_catset) == 1
        assert len(ctx.liked_rows) == 50


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
# score_event / venue-linked locality resolution
# ---------------------------------------------------------------------------


class TestScoreEventVenueLinkedLocality:
    """A venue-linked event's own lat/lng is never backfilled (#176) — the
    read path must resolve coordinates through the linked Venue instead of
    reading Event.lat/lng directly."""

    def _venue_linked_event(self, lat: float | None, lng: float | None) -> Event:
        venue = MagicMock()
        venue.lat = lat
        venue.lng = lng
        return _event(lat=None, lng=None, venue_id=7, venue=venue)

    def test_venue_linked_event_scores_nonzero_locality(self):
        e = self._venue_linked_event(59.437, 24.745)  # Tallinn centre
        v = {"categories": {"music": 1.0}, "vibes": {"underground": 1.0}}
        result = score_event([(1.0, v)], _ctx(), e, _now())
        assert result is not None
        # Own lat/lng are None; without venue resolution locality would be
        # NEUTRAL_SCORE (0.5) rather than the Tallinn-centre 1.0 the linked
        # Venue actually reports.
        no_venue_result = score_event([(1.0, v)], _ctx(), _event(lat=None, lng=None), _now())
        assert result > no_venue_result

    def test_half_geocoded_venue_falls_back_to_neutral(self):
        e = self._venue_linked_event(59.437, None)
        result = score_event([], _ctx(), e, _now())
        assert result is not None


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


class TestAnonymousScoreEvent:
    """Locked formula for anonymous /explore callers (#234): 0.45*NEUTRAL_SCORE
    + 0.25*recency + 0.125*quality + 0.0625*locality — feedback_signal dropped
    entirely, never treated as neutral."""

    def test_never_hard_excludes(self):
        # Even an event whose dedup_group would hard-exclude an authenticated
        # dislike has no meaning here — no feedback context exists at all.
        e = _event(dedup_group=5)
        result = anonymous_score_event(e, _now())
        assert result is not None
        assert 0.0 <= result <= 1.0

    def test_matches_locked_formula(self):
        now = _now()
        e = _event(starts_at=now, quality=0.8, lat=59.437, lng=24.745)
        result = anonymous_score_event(e, now)
        # recency_boost(starts_at == now) == 1.0; locality inside Tallinn bbox == 1.0
        expected = 0.45 * 0.5 + 0.25 * 1.0 + 0.125 * 0.8 + 0.0625 * 1.0
        assert result == expected

    def test_no_classification_uses_neutral_quality(self):
        now = _now()
        e = _event(starts_at=now)
        e.classification = None
        result = anonymous_score_event(e, now)
        expected = 0.45 * 0.5 + 0.25 * 1.0 + 0.125 * 0.5 + 0.0625 * 1.0
        assert result == expected

    def test_ignores_feedback_entirely(self):
        # score_event([], ctx-with-like, e, now) folds a like into the score via
        # fb_normalized; anonymous_score_event has no feedback parameter at all,
        # so an identical event scores the same regardless of any such history.
        now = _now()
        e1 = _event(event_id=1, starts_at=now)
        e2 = _event(event_id=2, starts_at=now)
        assert anonymous_score_event(e1, now) == anonymous_score_event(e2, now)

    def test_higher_recency_scores_higher(self):
        now = _now()
        e_soon = _event(starts_at=now)
        e_later = _event(starts_at=now + timedelta(days=10))
        assert anonymous_score_event(e_soon, now) > anonymous_score_event(e_later, now)


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


class TestSelectWithBackfill:
    def _make_event(self, eid: int, categories: list[str], score: float):
        e = _event(event_id=eid, categories=categories)
        return (score, e)

    def test_cap_excluded_backfill_when_cooldown_empty(self):
        # 6 same-category events: tier 1 picks 2 (cap=2); relaxed-cap fresh
        # adds 1 more (cap=3); uncapped sweep takes the rest to reach n=5.
        scored = [self._make_event(i, ["music"], 0.9 - i * 0.1) for i in range(6)]
        picked = _select_with_backfill(
            scored, [], n=5, max_per_category=2, backfill_max_per_category=3
        )
        assert [e.id for e in picked] == [0, 1, 2, 3, 4]

    def test_cap_excluded_preferred_over_higher_scored_cooled(self):
        # 3rd music event is cap-excluded by tier 1 but still outranks the
        # cooled candidate for backfill purposes, even though the cooled
        # candidate has a higher raw score.
        scored = [
            self._make_event(1, ["music"], 0.9),
            self._make_event(2, ["music"], 0.8),
            self._make_event(3, ["music"], 0.7),
        ]
        cooled = [self._make_event(4, ["theater"], 0.99)]
        picked = _select_with_backfill(
            scored, cooled, n=3, max_per_category=2, backfill_max_per_category=3
        )
        assert [e.id for e in picked] == [1, 2, 3]

    def test_cooled_backfill_used_when_cap_excluded_exhausted(self):
        # No cap-excluded events available (distinct categories) — cooled pool
        # is the only source left to reach n.
        scored = [
            self._make_event(1, ["music"], 0.9),
            self._make_event(2, ["theater"], 0.8),
        ]
        cooled = [
            self._make_event(3, ["cinema"], 0.95),
            self._make_event(4, ["sports"], 0.5),
        ]
        picked = _select_with_backfill(
            scored, cooled, n=4, max_per_category=2, backfill_max_per_category=3
        )
        assert [e.id for e in picked] == [1, 2, 3, 4]

    def test_no_duplicates_across_tiers(self):
        # Same event present in both pools (defensive) must not be picked twice.
        e = self._make_event(1, ["music"], 0.9)
        picked = _select_with_backfill(
            [e], [e], n=3, max_per_category=2, backfill_max_per_category=3
        )
        assert [x.id for x in picked] == [1]

    def test_insufficient_candidates_returns_fewer_than_n(self):
        # Genuinely <5 total candidates across both pools → no fabrication.
        scored = [self._make_event(1, ["music"], 0.9)]
        cooled = [self._make_event(2, ["theater"], 0.5)]
        picked = _select_with_backfill(
            scored, cooled, n=5, max_per_category=2, backfill_max_per_category=3
        )
        assert [e.id for e in picked] == [1, 2]

    def test_tier1_full_skips_backfill(self):
        cats = ["music", "theater", "cinema", "sports", "workshops"]
        scored = [self._make_event(i, [cats[i]], 0.9 - i * 0.05) for i in range(5)]
        cooled = [self._make_event(99, ["music"], 0.99)]
        picked = _select_with_backfill(
            scored, cooled, n=5, max_per_category=2, backfill_max_per_category=3
        )
        assert len(picked) == 5
        assert all(e.id != 99 for e in picked)

    def test_relaxed_cap_prefers_diverse_cooled_over_same_cat_overflow(self):
        # 4 same-category fresh events (tier 1 takes 2) + 2 distinct-category
        # cooled events, n=5. Relaxed cap (3) admits 1 more music event, then
        # diverse cooled fills the rest — the 4th music event loses out.
        scored = [self._make_event(i, ["music"], 0.9 - i * 0.1) for i in range(4)]
        cooled = [
            self._make_event(10, ["theater"], 0.5),
            self._make_event(11, ["cinema"], 0.4),
        ]
        picked = _select_with_backfill(
            scored, cooled, n=5, max_per_category=2, backfill_max_per_category=3
        )
        assert [e.id for e in picked] == [0, 1, 2, 10, 11]
        music_count = sum(1 for e in picked if "music" in e.classification.categories)
        assert music_count == 3
        assert 3 not in [e.id for e in picked]  # 4th music event excluded

    def test_uncapped_fallback_guarantees_n(self):
        # 6 same-category events, no cooled pool — the relaxed cap (3) would
        # leave the feed short, so the uncapped sweep must still reach n=5,
        # even though that means a single-category feed.
        scored = [self._make_event(i, ["music"], 0.9 - i * 0.1) for i in range(6)]
        picked = _select_with_backfill(
            scored, [], n=5, max_per_category=2, backfill_max_per_category=3
        )
        assert len(picked) == 5
        assert all("music" in e.classification.categories for e in picked)


class TestBuildDailyFeedsExplicitFilter:
    async def test_event_query_excludes_explicit_events(self, mock_db):
        from app.ranking.score import build_daily_feeds

        mock_db.scalars.side_effect = [
            _scalar_result([1]),  # user ids (all registered)
            _scalar_result([]),  # candidate events
            _scalar_result([]),  # users (page query) — none found, build_ctx None
        ]

        result = await build_daily_feeds(mock_db)

        assert result["total_users"] == 0
        stmt = mock_db.scalars.call_args_list[1].args[0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "is_explicit" in compiled
        assert "is_non_event" in compiled
        assert "false" in compiled.lower()

    async def test_event_query_keeps_ongoing_events_via_ends_at(self, mock_db):
        # Candidate window must use event_not_ended_filter, not a bare
        # starts_at >= now check, so an ongoing offer (past starts_at, future
        # ends_at) still reaches the Daily 5 pool.
        from app.ranking.score import build_daily_feeds

        mock_db.scalars.side_effect = [
            _scalar_result([1]),  # user ids (all registered)
            _scalar_result([]),  # candidate events
            _scalar_result([]),  # users (page query)
        ]

        await build_daily_feeds(mock_db)

        stmt = mock_db.scalars.call_args_list[1].args[0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "coalesce(events.ends_at, events.starts_at) >=" in compiled

    async def test_verified_user_ids_query_filters_on_email_verified(self, mock_db):
        # Filters on email_verified (a user with zero UserPersona rows can
        # still get a non-empty feed, so no persona-based pre-filter — see
        # _verified_user_ids' docstring for why the two are different).
        from app.ranking.score import _verified_user_ids

        mock_db.scalars.return_value = _scalar_result([])

        await _verified_user_ids(mock_db)

        stmt = mock_db.scalars.call_args_list[0].args[0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "user_personas" not in compiled
        assert "email_verified" in compiled
        assert "SELECT users.id" in compiled


def _scalar_result(items: list) -> MagicMock:
    r = MagicMock()
    r.all.return_value = items
    return r


def _feed_event(eid: int, title: str, venue: str, categories: list[str] | None = None) -> Event:
    e = _event(event_id=eid, categories=categories)
    e.title_orig = title
    e.venue_name = venue
    return e


def _user(uid: int) -> MagicMock:
    u = MagicMock()
    u.id = uid
    return u


def _dislike_row(event_id: int, user_id: int = 1) -> MagicMock:
    row = MagicMock()
    row.user_id = user_id
    row.event_id = event_id
    row.signal = "dislike"
    row.created_at = _now()
    row.event = MagicMock()
    row.event.dedup_group_id = None
    row.event.classification = None
    return row


class TestBuildDailyFeedsSeriesCooldown:
    async def test_recent_series_excluded_from_pool(self, mock_db):
        # User 1 was shown event 150 (series "van gogh"/"vaba lava") within the
        # cooldown window. Today's candidate 100 shares that series key, so it is
        # skipped; candidate 200 (a different series) is kept. Fresh filler
        # candidates (distinct categories) fill the pool to 5 on their own, so
        # backfill never kicks in — this isolates pure cooldown exclusion.
        from app.ranking.score import build_daily_feeds

        ev100 = _feed_event(100, "Van Gogh", "Vaba Lava")
        ev200 = _feed_event(200, "Concert X", "Hall", ["music"])
        ev201 = _feed_event(201, "Play", "Theater", ["theater"])
        ev202 = _feed_event(202, "Film", "Cinema", ["cinema"])
        ev203 = _feed_event(203, "Match", "Stadium", ["sports"])
        ev204 = _feed_event(204, "Workshop", "Studio", ["workshops"])
        ev150 = _feed_event(150, "Van Gogh", "Vaba Lava")  # yesterday's instance
        df = MagicMock()
        df.user_id = 1
        df.event_ids = [150]

        mock_db.scalars.side_effect = [
            _scalar_result([1]),               # user ids (all registered)
            _scalar_result([ev100, ev200, ev201, ev202, ev203, ev204]),  # candidate events
            _scalar_result([_user(1)]),        # users
            _scalar_result([]),                # personas
            _scalar_result([]),                # feedback
            _scalar_result([df]),              # cooldown-window feeds
            _scalar_result([ev150]),           # shown events resolved
            _scalar_result([]),                # cached scores
        ]

        await build_daily_feeds(mock_db)

        upsert_stmt = mock_db.execute.call_args.args[0]
        compiled = str(upsert_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "(1, " in compiled
        assert "ARRAY[200, 201, 202, 203, 204]" in compiled  # 100 cooled down, never backfilled

    async def test_no_recent_history_keeps_series(self, mock_db):
        # Empty cooldown window (e.g. the series last appeared outside it) → the
        # shown-events query is skipped and the candidate is kept.
        from app.ranking.score import build_daily_feeds

        ev100 = _feed_event(100, "Van Gogh", "Vaba Lava")

        mock_db.scalars.side_effect = [
            _scalar_result([1]),       # user ids (all registered)
            _scalar_result([ev100]),   # candidate events
            _scalar_result([_user(1)]),
            _scalar_result([]),        # personas
            _scalar_result([]),        # feedback
            _scalar_result([]),        # cooldown-window feeds (empty → no shown-events query)
            _scalar_result([]),        # cached scores
        ]

        await build_daily_feeds(mock_db)

        upsert_stmt = mock_db.execute.call_args.args[0]
        compiled = str(upsert_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "ARRAY[100]" in compiled

    async def test_other_users_history_does_not_affect_this_user(self, mock_db):
        # Only user 2 was shown the series; user 1's feed must still include it.
        # 5 fresh filler candidates (distinct categories) ensure each user's
        # own fresh pool can fill 5 without backfill — isolating per-user
        # cooldown exclusion from the backfill mechanism.
        from app.ranking.score import build_daily_feeds

        ev100 = _feed_event(100, "Van Gogh", "Vaba Lava")
        ev201 = _feed_event(201, "Play", "Theater", ["theater"])
        ev202 = _feed_event(202, "Film", "Cinema", ["cinema"])
        ev203 = _feed_event(203, "Match", "Stadium", ["sports"])
        ev204 = _feed_event(204, "Workshop", "Studio", ["workshops"])
        ev205 = _feed_event(205, "Gig", "Club", ["nightlife"])
        ev150 = _feed_event(150, "Van Gogh", "Vaba Lava")
        df = MagicMock()
        df.user_id = 2  # belongs to a different user
        df.event_ids = [150]

        mock_db.scalars.side_effect = [
            _scalar_result([1, 2]),                  # user ids (all registered)
            _scalar_result([ev100, ev201, ev202, ev203, ev204, ev205]),  # candidate events
            _scalar_result([_user(1), _user(2)]),    # users
            _scalar_result([]),                      # personas
            _scalar_result([]),                      # feedback
            _scalar_result([df]),                    # cooldown-window feeds (user 2)
            _scalar_result([ev150]),                 # shown events resolved
            _scalar_result([]),                      # cached scores
        ]

        await build_daily_feeds(mock_db)

        # Both users' rows are batched into one upsert statement.
        upsert_stmt = mock_db.execute.call_args.args[0]
        compiled = str(upsert_stmt.compile(compile_kwargs={"literal_binds": True}))
        # user 1 unaffected by user 2's history — keeps 100 among its top 5
        assert "(1, " in compiled and "ARRAY[100, 201, 202, 203, 204]" in compiled
        # user 2 cooled down on 100, but its own fresh pool fills 5 → no backfill needed
        assert "(2, " in compiled and "ARRAY[201, 202, 203, 204, 205]" in compiled

    async def test_cooldown_query_restricts_to_recent_date_window(self, mock_db):
        # The cooldown feed query (5th scalars call) must bound feed_date to
        # [today - DAILY5_SERIES_COOLDOWN_DAYS, today).
        from app.ranking.score import build_daily_feeds

        ev100 = _feed_event(100, "Van Gogh", "Vaba Lava")
        mock_db.scalars.side_effect = [
            _scalar_result([1]),       # user ids (all registered)
            _scalar_result([ev100]),   # candidate events
            _scalar_result([_user(1)]),
            _scalar_result([]),        # personas
            _scalar_result([]),        # feedback
            _scalar_result([]),        # cooldown-window feeds
            _scalar_result([]),        # cached scores
        ]

        await build_daily_feeds(mock_db)

        cooldown_stmt = mock_db.scalars.call_args_list[5].args[0]
        compiled = str(cooldown_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "daily_feeds.feed_date >=" in compiled
        assert "daily_feeds.feed_date <" in compiled

    async def test_cooled_series_backfilled_when_fresh_pool_short(self, mock_db):
        # 4 fresh candidates (distinct categories, no cap collision) can't reach
        # DAILY_5_COUNT=5 on their own. The 5th candidate shares a series with
        # yesterday's feed (cooldown) but gets backfilled in to complete the 5.
        from app.ranking.score import build_daily_feeds

        ev1 = _feed_event(1, "Concert", "Hall", ["music"])
        ev2 = _feed_event(2, "Play", "Theater", ["theater"])
        ev3 = _feed_event(3, "Film", "Cinema", ["cinema"])
        ev4 = _feed_event(4, "Match", "Stadium", ["sports"])
        ev5 = _feed_event(5, "Workshop", "Studio", ["workshops"])
        ev150 = _feed_event(150, "Workshop", "Studio", ["workshops"])  # yesterday's instance
        df = MagicMock()
        df.user_id = 1
        df.event_ids = [150]

        mock_db.scalars.side_effect = [
            _scalar_result([1]),                        # user ids (all registered)
            _scalar_result([ev1, ev2, ev3, ev4, ev5]),  # candidate events
            _scalar_result([_user(1)]),                 # users
            _scalar_result([]),                          # personas
            _scalar_result([]),                          # feedback
            _scalar_result([df]),                        # cooldown-window feeds
            _scalar_result([ev150]),                      # shown events resolved
            _scalar_result([]),                          # cached scores
        ]

        await build_daily_feeds(mock_db)

        upsert_stmt = mock_db.execute.call_args.args[0]
        compiled = str(upsert_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "ARRAY[1, 2, 3, 4, 5]" in compiled  # ev5 backfilled in despite cooldown

    async def test_disliked_cooled_event_not_backfilled(self, mock_db):
        # Same shortfall as above, but the cooled candidate is directly
        # disliked and was previously cached — the cache+dislike guard must
        # exclude it from the backfill pool entirely (no fabrication).
        from app.ranking.score import build_daily_feeds

        ev1 = _feed_event(1, "Concert", "Hall", ["music"])
        ev2 = _feed_event(2, "Play", "Theater", ["theater"])
        ev3 = _feed_event(3, "Film", "Cinema", ["cinema"])
        ev5 = _feed_event(5, "Workshop", "Studio", ["workshops"])
        ev150 = _feed_event(150, "Workshop", "Studio", ["workshops"])
        df = MagicMock()
        df.user_id = 1
        df.event_ids = [150]

        cached_row = MagicMock()
        cached_row.user_id = 1
        cached_row.event_id = 5
        cached_row.score = 0.9

        mock_db.scalars.side_effect = [
            _scalar_result([1]),                     # user ids (all registered)
            _scalar_result([ev1, ev2, ev3, ev5]),   # candidate events
            _scalar_result([_user(1)]),              # users
            _scalar_result([]),                       # personas
            _scalar_result([_dislike_row(5)]),         # feedback: direct dislike of ev5
            _scalar_result([df]),                     # cooldown-window feeds
            _scalar_result([ev150]),                   # shown events resolved
            _scalar_result([cached_row]),              # cached scores (ev5 cached)
        ]

        await build_daily_feeds(mock_db)

        upsert_stmt = mock_db.execute.call_args.args[0]
        compiled = str(upsert_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "ARRAY[1, 2, 3]" in compiled  # ev5 excluded, feed stays short — no fabrication

    async def test_backfilled_cooled_event_persisted_to_score_cache(self, mock_db):
        # The cooled event that gets backfilled in must still be written to
        # user_event_scores like any other freshly-scored candidate.
        from app.ranking.score import build_daily_feeds

        ev1 = _feed_event(1, "Concert", "Hall", ["music"])
        ev2 = _feed_event(2, "Play", "Theater", ["theater"])
        ev3 = _feed_event(3, "Film", "Cinema", ["cinema"])
        ev4 = _feed_event(4, "Match", "Stadium", ["sports"])
        ev5 = _feed_event(5, "Workshop", "Studio", ["workshops"])
        ev150 = _feed_event(150, "Workshop", "Studio", ["workshops"])
        df = MagicMock()
        df.user_id = 1
        df.event_ids = [150]

        mock_db.scalars.side_effect = [
            _scalar_result([1]),
            _scalar_result([ev1, ev2, ev3, ev4, ev5]),
            _scalar_result([_user(1)]),
            _scalar_result([]),
            _scalar_result([]),
            _scalar_result([df]),
            _scalar_result([ev150]),
            _scalar_result([]),
        ]

        await build_daily_feeds(mock_db)

        # The score upsert executes before the daily-feed upsert — first call.
        execute_stmt = mock_db.execute.call_args_list[0].args[0]
        compiled = str(execute_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "user_event_scores" in compiled
        assert "(1, 5," in compiled  # backfilled cooled event (user_id=1, event_id=5) was upserted


class TestCollapseSeriesDuplicates:
    def test_keeps_earliest_starts_at_per_series(self):
        from app.routers.utils import collapse_series_duplicates

        later = _feed_event(1, "Workshop", "Studio")
        later.starts_at = _now() + timedelta(days=5)
        earlier = _feed_event(2, "Workshop", "Studio")
        earlier.starts_at = _now() + timedelta(days=1)
        middle = _feed_event(3, "Workshop", "Studio")
        middle.starts_at = _now() + timedelta(days=3)

        collapsed, series_key_by_event_id = collapse_series_duplicates(
            [later, earlier, middle]
        )

        assert [e.id for e in collapsed] == [2]
        assert set(series_key_by_event_id) == {2}

    def test_ties_on_starts_at_break_deterministically_by_event_id(self):
        # Two instances sharing an exact starts_at (e.g. duplicate showtimes)
        # must resolve to the same survivor every call, independent of input
        # order or DB row order (the underlying query has no ORDER BY).
        from app.routers.utils import collapse_series_duplicates

        same_time = _now() + timedelta(days=2)
        ev5 = _feed_event(5, "Workshop", "Studio")
        ev5.starts_at = same_time
        ev2 = _feed_event(2, "Workshop", "Studio")
        ev2.starts_at = same_time

        collapsed_a, _ = collapse_series_duplicates([ev5, ev2])
        collapsed_b, _ = collapse_series_duplicates([ev2, ev5])

        assert [e.id for e in collapsed_a] == [2]
        assert [e.id for e in collapsed_b] == [2]

    def test_distinct_series_all_kept(self):
        from app.routers.utils import collapse_series_duplicates

        ev1 = _feed_event(1, "Concert", "Hall")
        ev2 = _feed_event(2, "Play", "Theater")

        collapsed, series_key_by_event_id = collapse_series_duplicates([ev1, ev2])

        assert {e.id for e in collapsed} == {1, 2}
        assert set(series_key_by_event_id) == {1, 2}


class TestBuildDailyFeedsSeriesDuplicateCollapse:
    async def test_only_nearest_date_instance_reaches_candidate_pool(self, mock_db):
        # A workshop running Tue/Thu/Sat ingests as 3 distinct Event rows
        # sharing an event_series_key. Only the soonest-starting one (event 2)
        # should ever reach scoring/selection — the feed must never contain
        # more than one instance of the same series.
        from app.ranking.score import build_daily_feeds

        ev1 = _feed_event(1, "Workshop", "Studio", ["workshops"])
        ev1.starts_at = _now() + timedelta(days=5)
        ev2 = _feed_event(2, "Workshop", "Studio", ["workshops"])
        ev2.starts_at = _now() + timedelta(days=1)
        ev3 = _feed_event(3, "Workshop", "Studio", ["workshops"])
        ev3.starts_at = _now() + timedelta(days=3)

        mock_db.scalars.side_effect = [
            _scalar_result([1]),                # user ids (all registered)
            _scalar_result([ev1, ev2, ev3]),    # candidate events (same series)
            _scalar_result([_user(1)]),          # users
            _scalar_result([]),                  # personas
            _scalar_result([]),                  # feedback
            _scalar_result([]),                  # cooldown-window feeds
            _scalar_result([]),                  # cached scores
        ]

        result = await build_daily_feeds(mock_db)

        assert result["candidate_events"] == 1
        upsert_stmt = mock_db.execute.call_args.args[0]
        compiled = str(upsert_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "ARRAY[2]" in compiled  # only the nearest-date instance survives


class TestBuildDailyFeedForUser:
    # build_daily_feed_for_user calls _load_feed_build_context with shared=None
    # (the default), so it still loads candidate events itself in one query —
    # no eligibility query, no _SharedFeedContext reuse. Call sequence unchanged.
    async def test_builds_feed_for_single_user_only(self, mock_db):
        # Onboarding-completion build: scopes the user query to one id and
        # writes exactly one DailyFeed row, reusing the same candidate
        # loading / scoring / cooldown / caching pipeline as build_daily_feeds.
        from app.ranking.score import build_daily_feed_for_user

        ev1 = _feed_event(1, "Concert", "Hall", ["music"])
        ev2 = _feed_event(2, "Play", "Theater", ["theater"])

        mock_db.scalars.side_effect = [
            _scalar_result([ev1, ev2]),  # candidate events
            _scalar_result([_user(7)]),  # users (scoped to user_id=7)
            _scalar_result([]),  # personas
            _scalar_result([]),  # feedback
            _scalar_result([]),  # cooldown-window feeds
            _scalar_result([]),  # cached scores
        ]

        result = await build_daily_feed_for_user(mock_db, 7)

        upsert_stmt = mock_db.execute.call_args.args[0]
        compiled = str(upsert_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "(7, " in compiled
        assert "ARRAY[1, 2]" in compiled
        assert result["total_users"] == 1
        assert result["built"] == 1
        mock_db.commit.assert_awaited_once()

        # The users query must scope to the requested id, not select all users.
        users_stmt = mock_db.scalars.call_args_list[1].args[0]
        compiled = str(users_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "users.id IN (7)" in compiled

    async def test_no_user_found_returns_empty_summary(self, mock_db):
        from app.ranking.score import build_daily_feed_for_user

        mock_db.scalars.side_effect = [
            _scalar_result([]),  # candidate events
            _scalar_result([]),  # users — none found (e.g. deleted mid-request)
        ]

        result = await build_daily_feed_for_user(mock_db, 999)

        assert result == {
            "built": 0,
            "empty": 0,
            "total_users": 0,
            "candidate_events": 0,
        }
        mock_db.execute.assert_not_awaited()
        mock_db.commit.assert_not_awaited()


class TestBuildDailyFeedsBatching:
    """FEED_BUILD_USER_BATCH_SIZE pages the user loop — candidate events must
    still be loaded exactly once (the RAM-savings claim), each page commits
    independently, and the aggregate summary must match a hand-computed
    single-pass expectation over the same users/events."""

    async def test_pages_users_reusing_shared_candidates(self, mock_db, monkeypatch):
        import app.ranking.score as score_module

        monkeypatch.setattr(score_module, "FEED_BUILD_USER_BATCH_SIZE", 2)

        ev1 = _feed_event(1, "Concert", "Hall", ["music"])
        ev2 = _feed_event(2, "Play", "Theater", ["theater"])

        # 5 registered users, batch size 2 → pages of [1,2], [3,4], [5].
        # Each page: users, personas, feedback, cooldown-window feeds, cached
        # scores (5 scalars calls/page, no shown-events query — cooldown
        # windows are empty). all-user-ids + candidate-events precede all pages.
        mock_db.scalars.side_effect = [
            _scalar_result([1, 2, 3, 4, 5]),  # user ids (all registered)
            _scalar_result([ev1, ev2]),  # candidate events (loaded once)
            _scalar_result([_user(1), _user(2)]),
            _scalar_result([]),
            _scalar_result([]),
            _scalar_result([]),
            _scalar_result([]),
            _scalar_result([_user(3), _user(4)]),
            _scalar_result([]),
            _scalar_result([]),
            _scalar_result([]),
            _scalar_result([]),
            _scalar_result([_user(5)]),
            _scalar_result([]),
            _scalar_result([]),
            _scalar_result([]),
            _scalar_result([]),
        ]

        result = await score_module.build_daily_feeds(mock_db)

        assert mock_db.commit.await_count == 3  # one per page

        # Candidate-events query ran exactly once regardless of page count —
        # the core RAM-savings claim (identified by its is_explicit marker).
        event_query_calls = [
            call
            for call in mock_db.scalars.call_args_list
            if "is_explicit"
            in str(call.args[0].compile(compile_kwargs={"literal_binds": True}))
        ]
        assert len(event_query_calls) == 1

        # Hand-computed single-pass expectation: 5 users, each scored against
        # the same 2 candidates with no feedback/cooldown/cache — every user
        # gets a 2-event feed (built), no empties, 10 fresh score writes,
        # zero reuse (score_cache is empty on every page — paging by user_id
        # cannot change which scores are cache hits/misses for a given user).
        assert result == {
            "built": 5,
            "empty": 0,
            "total_users": 5,
            "candidate_events": 2,
            "scores_written": 10,
            "scores_reused": 0,
        }
