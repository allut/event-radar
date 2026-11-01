"""Unit tests for the scoring formula — no DB, all pure functions."""
from datetime import datetime, timedelta
from unittest.mock import MagicMock


from app.constants.core import TALLINN_TZ
from app.constants.ranking import SCORE_HARD_EXCLUDE
from app.models.events import Event
from tests.ranking.conftest import fixed_now, make_ctx, make_event
from app.ranking.score import (
    _affinity_for_vector,
    _time_slots_for_event,
    anonymous_score_event,
    feedback_signal,
    locality_bonus,
    persona_affinity,
    recency_boost,
    score_event,
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
    def test_cache_yields_identical_scores_and_is_reused(self):
        # Big-O audit H4: the build-scoped memo must not change any score.
        v1 = {"categories": {"music": 1.0, "theater": 0.5}, "vibes": {"chill": 0.5}}
        v2 = {"categories": {"sports": 1.0}, "times": {"evening": 1.0}}
        weights = [(0.7, v1), (0.3, v2)]
        cache: dict = {}
        for _ in range(2):
            assert persona_affinity(
                weights, ["music"], ["chill"], ["evening"], cache=cache
            ) == persona_affinity(weights, ["music"], ["chill"], ["evening"])
        assert len(cache) == 2  # one entry per (vector, tag-set), reused on repeat

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
        now = fixed_now()
        assert recency_boost(now, now) == 1.0

    def test_21_days_is_zero(self):
        now = fixed_now()
        assert recency_boost(now + timedelta(days=21), now) == 0.0

    def test_past_is_zero(self):
        now = fixed_now()
        assert recency_boost(now - timedelta(hours=1), now) == 0.0

    def test_10_days_is_half(self):
        now = fixed_now()
        result = recency_boost(now + timedelta(days=10.5), now)
        assert abs(result - 0.5) < 0.01

    def test_linear_decay(self):
        now = fixed_now()
        b7 = recency_boost(now + timedelta(days=7), now)
        b14 = recency_boost(now + timedelta(days=14), now)
        assert abs(b7 - 2 * b14) < 1e-9  # exactly linear


# ---------------------------------------------------------------------------
# feedback_signal
# ---------------------------------------------------------------------------


class TestFeedbackSignal:
    def test_no_feedback_returns_zero(self):
        ctx = make_ctx()
        assert feedback_signal(1, ["music"], None, ctx, fixed_now()) == 0.0

    def test_direct_like_returns_positive(self):
        ctx = make_ctx(("like", 1, ["music"], None, fixed_now()))
        result = feedback_signal(1, ["music"], None, ctx, fixed_now())
        assert result > 0.0
        assert result <= 1.0

    def test_direct_dislike_returns_negative(self):
        ctx = make_ctx(("dislike", 1, ["music"], None, fixed_now()))
        result = feedback_signal(1, ["music"], None, ctx, fixed_now())
        assert result < 0.0

    def test_disliked_dedup_group_hard_excludes(self):
        ctx = make_ctx(("dislike", 99, ["music"], 7, fixed_now()))
        # Event with same dedup_group_id=7 should return the hard-exclude sentinel
        result = feedback_signal(2, ["music"], 7, ctx, fixed_now())
        assert result == SCORE_HARD_EXCLUDE

    def test_different_dedup_group_not_excluded(self):
        ctx = make_ctx(("dislike", 99, ["music"], 7, fixed_now()))
        result = feedback_signal(2, ["music"], 8, ctx, fixed_now())
        assert result != -1.0

    def test_indirect_like_via_shared_category(self):
        ctx = make_ctx(("like", 99, ["music"], None, fixed_now()))
        result = feedback_signal(1, ["music"], None, ctx, fixed_now())
        assert result > 0.0

    def test_indirect_like_no_shared_category(self):
        ctx = make_ctx(("like", 99, ["theater"], None, fixed_now()))
        result = feedback_signal(1, ["music"], None, ctx, fixed_now())
        assert result == 0.0

    def test_signal_decays_with_time(self):
        old = fixed_now() - timedelta(days=30)
        ctx_recent = make_ctx(("like", 1, ["music"], None, fixed_now()))
        ctx_old = make_ctx(("like", 1, ["music"], None, old))
        recent_sig = feedback_signal(1, ["music"], None, ctx_recent, fixed_now())
        old_sig = feedback_signal(1, ["music"], None, ctx_old, fixed_now())
        assert recent_sig > old_sig

    def test_result_clipped_to_minus_one(self):
        # Multiple dislikes shouldn't go below -1
        ctx = make_ctx(
            ("dislike", 1, ["music"], None, fixed_now()),
            ("dislike", 1, ["music"], None, fixed_now()),
        )
        result = feedback_signal(1, ["music"], None, ctx, fixed_now())
        assert result >= -1.0

    def test_liking_an_event_does_not_double_count_via_indirect(self):
        """Scoring the very event a user liked must only carry the direct term —
        the old per-row loop excluded any row with row.event_id == event_id from the
        indirect sum; the aggregated version must reproduce that exactly (verifies the
        liked_decay_by_event self-exclusion subtraction)."""
        ctx = make_ctx(("like", 1, ["music"], None, fixed_now()))
        result = feedback_signal(1, ["music"], None, ctx, fixed_now())
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
        ctx = make_ctx(
            ("like", 1, ["music"], None, fixed_now()),
            ("like", 1, ["music"], None, fixed_now()),
        )
        # Scoring event 1 itself: indirect must be fully cancelled regardless of the
        # duplicate, leaving only the two direct-like contributions (each 1.0, clipped).
        result = feedback_signal(1, ["music"], None, ctx, fixed_now())
        assert result == 1.0  # direct signals clip at 1.0; no indirect leak-through

    def test_indirect_credit_from_other_event_survives_self_exclusion(self):
        """Self-exclusion must remove only the scored event's own share, not the
        contribution of a different liked event sharing the same category. Uses an
        old direct like (decayed well below 1.0) so the [-1, 1] clip can't mask the
        indirect contribution from event 99's like."""
        old = fixed_now() - timedelta(days=30)
        with_other_indirect = feedback_signal(
            1, ["music"], None,
            make_ctx(
                ("like", 1, ["music"], None, old),
                ("like", 99, ["music"], None, fixed_now()),
            ),
            fixed_now(),
        )
        direct_only = feedback_signal(
            1, ["music"], None,
            make_ctx(("like", 1, ["music"], None, old)),
            fixed_now(),
        )
        assert with_other_indirect > direct_only

    def test_multi_category_liked_row_credited_once_not_per_category(self):
        """A liked row with multiple categories must contribute its decay once to any
        overlapping event, not once per overlapping category (each row occupies exactly
        one bucket — its full category_set — not a bucket per individual category)."""
        ctx = make_ctx(("like", 99, ["music", "theater"], None, fixed_now()))
        overlap_one = feedback_signal(1, ["music"], None, ctx, fixed_now())
        overlap_two = feedback_signal(1, ["music", "theater"], None, ctx, fixed_now())
        # Same liked row, same bucket — overlapping on one category vs. both categories
        # must yield the identical indirect contribution (bucket-level, not per-category).
        assert overlap_one == overlap_two

    def test_liked_aggregates_lazily_built_and_cached_per_now(self):
        """build_liked_aggregates is idempotent per `now` — feedback_signal's internal
        call must not rebuild on every invocation for the same `now` (the O(1)-amortized
        contract the complexity fix depends on)."""
        ctx = make_ctx(("like", 99, ["music"], None, fixed_now()))
        now = fixed_now()
        feedback_signal(1, ["music"], None, ctx, now)
        built_after_first = ctx._liked_aggregates_built_for
        feedback_signal(2, ["music"], None, ctx, now)
        assert ctx._liked_aggregates_built_for == built_after_first == now

    def test_liked_decay_aggregated_by_distinct_category_set_not_per_row(self):
        """Complexity proof: many liked rows sharing one category_set must collapse
        into a single liked_decay_by_catset bucket, not one entry per row — this is
        what makes feedback_signal O(distinct category-sets) instead of O(liked rows)."""
        many_rows = tuple(
            ("like", 100 + i, ["music"], None, fixed_now()) for i in range(50)
        )
        ctx = make_ctx(*many_rows)
        feedback_signal(1, ["theater"], None, ctx, fixed_now())  # triggers the lazy build
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
        return make_event(lat=None, lng=None, venue_id=7, venue=venue)

    def test_venue_linked_event_scores_nonzero_locality(self):
        e = self._venue_linked_event(59.437, 24.745)  # Tallinn centre
        v = {"categories": {"music": 1.0}, "vibes": {"underground": 1.0}}
        result = score_event([(1.0, v)], make_ctx(), e, fixed_now())
        assert result is not None
        # Own lat/lng are None; without venue resolution locality would be
        # NEUTRAL_SCORE (0.5) rather than the Tallinn-centre 1.0 the linked
        # Venue actually reports.
        no_venue_result = score_event([(1.0, v)], make_ctx(), make_event(lat=None, lng=None), fixed_now())
        assert result > no_venue_result

    def test_half_geocoded_venue_falls_back_to_neutral(self):
        e = self._venue_linked_event(59.437, None)
        result = score_event([], make_ctx(), e, fixed_now())
        assert result is not None


class TestScoreEvent:
    def test_returns_float_in_range(self):
        e = make_event()
        v = {"categories": {"music": 1.0}, "vibes": {"underground": 1.0}}
        ctx = make_ctx()
        result = score_event([(1.0, v)], ctx, e, fixed_now())
        assert result is not None
        assert 0.0 <= result <= 1.0

    def test_hard_excluded_returns_none(self):
        e = make_event(dedup_group=5)
        ctx = make_ctx(("dislike", 99, ["music"], 5, fixed_now()))
        result = score_event([], ctx, e, fixed_now())
        assert result is None

    def test_no_classification_uses_defaults(self):
        e = make_event()
        e.classification = None
        ctx = make_ctx()
        result = score_event([], ctx, e, fixed_now())
        assert result is not None
        assert 0.0 <= result <= 1.0

    def test_high_affinity_scores_higher_than_no_affinity(self):
        e = make_event()
        v_match = {"categories": {"music": 1.0}, "vibes": {"underground": 1.0}}
        v_miss = {"categories": {"theater": 1.0}, "vibes": {}}
        ctx = make_ctx()
        now = fixed_now()
        score_match = score_event([(1.0, v_match)], ctx, e, now)
        score_miss = score_event([(1.0, v_miss)], ctx, e, now)
        assert score_match is not None
        assert score_miss is not None
        assert score_match > score_miss


class TestClaimStatusRankingNeutrality:
    """Regression (#419): claim status must contribute nothing to the ranking
    formula. Neither score_event nor anonymous_score_event reads claim/
    organizer state at all, so two otherwise-identical events — one claimed,
    one not — must score identically."""

    def test_score_event_ignores_claim_status(self):
        now = fixed_now()
        unclaimed = make_event(event_id=1)
        claimed = make_event(event_id=2)
        claimed.claim_status = "claimed"
        claimed.listed_by = "Tallinn Jazz Club"
        v = {"categories": {"music": 1.0}, "vibes": {"underground": 1.0}}
        ctx = make_ctx()

        assert score_event([(1.0, v)], ctx, unclaimed, now) == score_event(
            [(1.0, v)], ctx, claimed, now
        )

    def test_anonymous_score_event_ignores_claim_status(self):
        now = fixed_now()
        unclaimed = make_event(event_id=1)
        claimed = make_event(event_id=2)
        claimed.claim_status = "claimed"
        claimed.listed_by = "Tallinn Jazz Club"

        assert anonymous_score_event(unclaimed, now) == anonymous_score_event(claimed, now)


class TestAnonymousScoreEvent:
    """Locked formula for anonymous /explore callers (#234): 0.45*NEUTRAL_SCORE
    + 0.25*recency + 0.125*quality + 0.0625*locality — feedback_signal dropped
    entirely, never treated as neutral."""

    def test_never_hard_excludes(self):
        # Even an event whose dedup_group would hard-exclude an authenticated
        # dislike has no meaning here — no feedback context exists at all.
        e = make_event(dedup_group=5)
        result = anonymous_score_event(e, fixed_now())
        assert result is not None
        assert 0.0 <= result <= 1.0

    def test_matches_locked_formula(self):
        now = fixed_now()
        e = make_event(starts_at=now, quality=0.8, lat=59.437, lng=24.745)
        result = anonymous_score_event(e, now)
        # recency_boost(starts_at == now) == 1.0; locality inside Tallinn bbox == 1.0
        expected = 0.45 * 0.5 + 0.25 * 1.0 + 0.125 * 0.8 + 0.0625 * 1.0
        assert result == expected

    def test_no_classification_uses_neutral_quality(self):
        now = fixed_now()
        e = make_event(starts_at=now)
        e.classification = None
        result = anonymous_score_event(e, now)
        expected = 0.45 * 0.5 + 0.25 * 1.0 + 0.125 * 0.5 + 0.0625 * 1.0
        assert result == expected

    def test_ignores_feedback_entirely(self):
        # score_event([], ctx-with-like, e, now) folds a like into the score via
        # fb_normalized; anonymous_score_event has no feedback parameter at all,
        # so an identical event scores the same regardless of any such history.
        now = fixed_now()
        e1 = make_event(event_id=1, starts_at=now)
        e2 = make_event(event_id=2, starts_at=now)
        assert anonymous_score_event(e1, now) == anonymous_score_event(e2, now)

    def test_higher_recency_scores_higher(self):
        now = fixed_now()
        e_soon = make_event(starts_at=now)
        e_later = make_event(starts_at=now + timedelta(days=10))
        assert anonymous_score_event(e_soon, now) > anonymous_score_event(e_later, now)
