"""Unit tests for Daily 5 selection — no DB, all pure functions."""

from app.ranking.selection import _mmr_pick, select_with_backfill
from tests.ranking.conftest import make_event


class TestMmrPick:
    def _make_event(self, eid: int, categories: list[str], score: float):
        e = make_event(event_id=eid, categories=categories)
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
        e = make_event(event_id=1, categories=[])
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
        e = make_event(event_id=eid, categories=categories)
        return (score, e)

    def test_cap_excluded_backfill_when_cooldown_empty(self):
        # 6 same-category events: tier 1 picks 2 (cap=2); relaxed-cap fresh
        # adds 1 more (cap=3); uncapped sweep takes the rest to reach n=5.
        scored = [self._make_event(i, ["music"], 0.9 - i * 0.1) for i in range(6)]
        picked = select_with_backfill(
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
        picked = select_with_backfill(
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
        picked = select_with_backfill(
            scored, cooled, n=4, max_per_category=2, backfill_max_per_category=3
        )
        assert [e.id for e in picked] == [1, 2, 3, 4]

    def test_no_duplicates_across_tiers(self):
        # Same event present in both pools (defensive) must not be picked twice.
        e = self._make_event(1, ["music"], 0.9)
        picked = select_with_backfill(
            [e], [e], n=3, max_per_category=2, backfill_max_per_category=3
        )
        assert [x.id for x in picked] == [1]

    def test_insufficient_candidates_returns_fewer_than_n(self):
        # Genuinely <5 total candidates across both pools → no fabrication.
        scored = [self._make_event(1, ["music"], 0.9)]
        cooled = [self._make_event(2, ["theater"], 0.5)]
        picked = select_with_backfill(
            scored, cooled, n=5, max_per_category=2, backfill_max_per_category=3
        )
        assert [e.id for e in picked] == [1, 2]

    def test_tier1_full_skips_backfill(self):
        cats = ["music", "theater", "cinema", "sports", "workshops"]
        scored = [self._make_event(i, [cats[i]], 0.9 - i * 0.05) for i in range(5)]
        cooled = [self._make_event(99, ["music"], 0.99)]
        picked = select_with_backfill(
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
        picked = select_with_backfill(
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
        picked = select_with_backfill(
            scored, [], n=5, max_per_category=2, backfill_max_per_category=3
        )
        assert len(picked) == 5
        assert all("music" in e.classification.categories for e in picked)
