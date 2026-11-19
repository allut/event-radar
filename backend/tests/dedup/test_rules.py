"""Tests for app.dedup.rules — rule-based deduplication pre-filter."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from rapidfuzz.fuzz import token_set_ratio

from app.constants.core import TALLINN_TZ
from app.constants.dedup import (
    TIME_WINDOW_HOURS,
    TITLE_RATIO_THRESHOLD,
    TITLE_RATIO_VENUE_BYPASS_THRESHOLD,
)
from app.dedup.rules import (
    _find,
    apply_same_day_title_unions,
    build_cluster_assignments,
    cluster_events,
    is_candidate_pair,
    same_group,
    _venue_compatible,
)


def _event(
    eid: int,
    title: str,
    starts_at: datetime,
    venue_name: str | None = None,
    status: str = "draft",
    price_min: float | None = None,
    venue_address: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    description_orig: str = "",
) -> MagicMock:
    e = MagicMock()
    e.id = eid
    e.title_orig = title
    e.starts_at = starts_at
    e.venue_name = venue_name
    e.status = status
    e.price_min = price_min
    e.venue_address = venue_address
    e.lat = lat
    e.lng = lng
    e.description_orig = description_orig
    return e


_BASE = datetime(2026, 7, 1, 20, 0, 0, tzinfo=TALLINN_TZ)


# ---------------------------------------------------------------------------
# _venue_compatible
# ---------------------------------------------------------------------------


class TestVenueCompatible:
    def test_both_none(self):
        assert _venue_compatible(None, None) is True

    def test_one_none(self):
        assert _venue_compatible("Von Krahli", None) is True
        assert _venue_compatible(None, "Von Krahli") is True

    def test_same_venue(self):
        assert _venue_compatible("Von Krahli", "Von Krahli") is True

    def test_similar_venue_fuzzy(self):
        # Slight variation (abbreviation / extra word) should still match
        assert _venue_compatible("Telliskivi Creative City", "Telliskivi") is True

    def test_different_venues(self):
        assert _venue_compatible("Von Krahli", "Fotografiska") is False

    def test_empty_string_venue_not_treated_as_none(self):
        # "" is not None — two events with different non-null venues must NOT be
        # auto-compatible just because a source wrote venue_name=""
        assert _venue_compatible("Von Krahli", "") is False
        assert _venue_compatible("", "Fotografiska") is False


# ---------------------------------------------------------------------------
# is_candidate_pair
# ---------------------------------------------------------------------------


class TestIsCandidatePair:
    def test_identical_titles_same_time(self):
        a = _event(1, "Jazz Night", _BASE)
        b = _event(2, "Jazz Night", _BASE)
        assert is_candidate_pair(a, b) is True

    def test_identical_titles_11h_apart(self):
        a = _event(1, "Jazz Night", _BASE)
        b = _event(2, "Jazz Night", _BASE + timedelta(hours=11))
        assert is_candidate_pair(a, b) is True

    def test_identical_titles_12h_exactly_boundary(self):
        # Exactly 12h — still within window (strictly less than is not required by plan)
        a = _event(1, "Jazz Night", _BASE)
        b = _event(2, "Jazz Night", _BASE + timedelta(hours=TIME_WINDOW_HOURS))
        assert is_candidate_pair(a, b) is True

    def test_identical_titles_13h_apart(self):
        a = _event(1, "Jazz Night", _BASE)
        b = _event(2, "Jazz Night", _BASE + timedelta(hours=13))
        assert is_candidate_pair(a, b) is False

    def test_title_below_threshold(self):
        a = _event(1, "Jazz Night at Von Krahli", _BASE)
        b = _event(2, "Completely Different Circus Show", _BASE)
        assert is_candidate_pair(a, b) is False

    def test_title_above_threshold_different_venues(self):
        a = _event(1, "Jazz Night", _BASE, venue_name="Von Krahli")
        b = _event(2, "Jazz Night", _BASE, venue_name="Fotografiska")
        assert is_candidate_pair(a, b) is False

    def test_title_match_venue_none(self):
        a = _event(1, "Jazz Night", _BASE, venue_name=None)
        b = _event(2, "Jazz Night", _BASE, venue_name="Von Krahli")
        assert is_candidate_pair(a, b) is True

    def test_case_insensitive_title(self):
        a = _event(1, "JAZZ NIGHT", _BASE)
        b = _event(2, "jazz night", _BASE)
        assert is_candidate_pair(a, b) is True

    def test_minor_title_variation(self):
        # Typical cross-source duplicate: "TMW Jazz Night" vs "TMW Jazz Night — Tickets"
        a = _event(1, "TMW Jazz Night", _BASE)
        b = _event(2, "TMW Jazz Night - Tallinn Music Week", _BASE)
        assert is_candidate_pair(a, b) is True

    def test_bypass_flag_off_exact_title_different_venue_still_false(self):
        # Rule-only path (flag default False) stays strict — unaffected by the bypass.
        a = _event(1, "Klassikatähed", _BASE, venue_name="Estonia Concert Hall")
        b = _event(2, "Klassikatähed", _BASE, venue_name="Eesti Kontsert")
        assert is_candidate_pair(a, b) is False

    def test_bypass_flag_on_exact_title_different_venue_true(self):
        # Near-exact title (>= TITLE_RATIO_VENUE_BYPASS_THRESHOLD) bypasses the
        # venue gate on the LLM path, letting the LLM judge differently-spelled
        # venues.
        a = _event(1, "Klassikatähed", _BASE, venue_name="Estonia Concert Hall")
        b = _event(2, "Klassikatähed", _BASE, venue_name="Eesti Kontsert")
        assert is_candidate_pair(a, b, bypass_venue_on_near_exact_title=True) is True

    def test_bypass_flag_on_ratio_85_to_89_cross_venue_now_candidate(self):
        # Title ratio in [85, 90): blocked under the old 90 strong threshold, now
        # reaches the LLM under the 85 bypass threshold. This is the cross-language
        # / cross-venue gap Fix 2 targets.
        a = _event(1, "Bach Cantata Evening Series", _BASE, venue_name="Estonia")
        b = _event(2, "Bach Cantata Evening Show", _BASE, venue_name="Eesti Kontsert")
        ratio = token_set_ratio(a.title_orig.lower(), b.title_orig.lower())
        assert TITLE_RATIO_VENUE_BYPASS_THRESHOLD <= ratio < 90
        assert is_candidate_pair(a, b, bypass_venue_on_near_exact_title=True) is True
        # Rule-only path (bypass off) still rejects the venue mismatch.
        assert is_candidate_pair(a, b) is False

    def test_bypass_flag_on_below_85_title_different_venue_still_false(self):
        # Title ratio in [TITLE_RATIO_THRESHOLD, 85) is above the candidate bar but
        # not near-exact — venue still gates it even with the bypass flag on.
        a = _event(1, "Jazz Night at Von Krahli", _BASE, venue_name="Von Krahli")
        b = _event(2, "Jazz Night Tallinn", _BASE, venue_name="Fotografiska")
        ratio = token_set_ratio(a.title_orig.lower(), b.title_orig.lower())
        assert TITLE_RATIO_THRESHOLD <= ratio < TITLE_RATIO_VENUE_BYPASS_THRESHOLD
        assert is_candidate_pair(a, b, bypass_venue_on_near_exact_title=True) is False

    def test_cross_language_titles_exact_time_venue_default_false(self):
        # Rule-only path (default): completely different scripts score ~0 on
        # token_set_ratio and stay rejected — the flag is off.
        a = _event(1, "Energia avastuskeskuse sissepääsupilet", _BASE, venue_name="Energia avastuskeskus")
        b = _event(2, "Входной билет Познавательного центра", _BASE, venue_name="Energia avastuskeskus")
        assert is_candidate_pair(a, b) is False

    def test_cross_language_titles_exact_time_venue_bypass_true(self):
        # LLM path: exact starts_at + compatible venue reaches the LLM regardless
        # of title similarity — this is the 142/143/144 language-variant case.
        a = _event(1, "Energia avastuskeskuse sissepääsupilet", _BASE, venue_name="Energia avastuskeskus")
        b = _event(2, "Входной билет Познавательного центра", _BASE, venue_name="Energia avastuskeskus")
        assert (
            is_candidate_pair(a, b, bypass_title_on_exact_time_and_venue=True)
            is True
        )

    def test_title_bypass_requires_exact_time_not_just_within_window(self):
        # Even 1 minute apart is enough to fail the *exact* time-equality bypass —
        # deliberately narrower than the 12h candidate window, so it falls through
        # to the ordinary title-ratio gate and is rejected.
        a = _event(1, "Energia avastuskeskuse sissepääsupilet", _BASE, venue_name="Energia avastuskeskus")
        b = _event(
            2, "Входной билет Познавательного центра",
            _BASE + timedelta(minutes=1), venue_name="Energia avastuskeskus",
        )
        assert (
            is_candidate_pair(a, b, bypass_title_on_exact_time_and_venue=True)
            is False
        )

    def test_title_bypass_requires_non_null_venue_on_both_sides(self):
        # Adversarial-review finding: with venue_name=None on either side,
        # _venue_compatible's normal "unknown is compatible" rule must NOT let
        # an arbitrary identical-round-time pair (zero title/venue evidence)
        # become an LLM candidate.
        a = _event(1, "Unrelated Ticket A", _BASE, venue_name=None)
        b = _event(2, "Completely Different Thing B", _BASE, venue_name="Von Krahli")
        assert (
            is_candidate_pair(a, b, bypass_title_on_exact_time_and_venue=True)
            is False
        )
        c = _event(3, "Unrelated Ticket A", _BASE, venue_name=None)
        d = _event(4, "Completely Different Thing B", _BASE, venue_name=None)
        assert (
            is_candidate_pair(c, d, bypass_title_on_exact_time_and_venue=True)
            is False
        )

    def test_title_bypass_requires_compatible_venue(self):
        # Exact time match alone is not enough — an incompatible venue still gates,
        # even with the bypass flag on.
        a = _event(1, "Ticket A", _BASE, venue_name="Von Krahli")
        b = _event(2, "Совершенно другое", _BASE, venue_name="Fotografiska")
        assert (
            is_candidate_pair(a, b, bypass_title_on_exact_time_and_venue=True)
            is False
        )

    def test_title_bypass_off_by_default_distinct_products_same_slot(self):
        # False-positive pattern found in the DB scan: same organizer, same
        # venue/time, genuinely distinct products (title ratio ~51, below
        # TITLE_RATIO_THRESHOLD). Default (flag off) rejects — only the LLM path
        # (flag on) would even consider it, and the LLM prompt is responsible for
        # telling these apart, not the rule layer.
        a = _event(1, "Sauna Social + Bar @Heldeke", _BASE, venue_name="Heldeke!")
        b = _event(2, "No Stress Chess @Heldeke", _BASE, venue_name="Heldeke!")
        assert is_candidate_pair(a, b) is False


# ---------------------------------------------------------------------------
# cluster_events
# ---------------------------------------------------------------------------


class TestClusterEvents:
    def test_empty(self):
        assert cluster_events([]) == {}

    def test_single_event(self):
        assert cluster_events([_event(1, "Solo Show", _BASE)]) == {}

    def test_two_duplicates(self):
        a = _event(1, "Jazz Night", _BASE)
        b = _event(2, "Jazz Night", _BASE)
        result = cluster_events([a, b])
        assert result == {1: 1, 2: 1}

    def test_two_non_duplicates(self):
        a = _event(1, "Jazz Night", _BASE)
        b = _event(2, "Totally Different Show", _BASE)
        assert cluster_events([a, b]) == {}

    def test_three_events_two_duplicates(self):
        a = _event(1, "Jazz Night", _BASE)
        b = _event(2, "Jazz Night", _BASE)
        c = _event(3, "Circus Act", _BASE)
        result = cluster_events([a, b, c])
        assert result == {1: 1, 2: 1}
        assert 3 not in result

    def test_three_way_duplicate(self):
        a = _event(1, "Jazz Night", _BASE)
        b = _event(2, "Jazz Night", _BASE)
        c = _event(3, "Jazz Night", _BASE)
        result = cluster_events([a, b, c])
        assert result[1] == 1
        assert result[2] == 1
        assert result[3] == 1

    def test_group_id_is_min_event_id(self):
        # IDs not in sorted order — group root must still be min
        a = _event(10, "Jazz Night", _BASE)
        b = _event(5, "Jazz Night", _BASE)
        c = _event(7, "Jazz Night", _BASE)
        result = cluster_events([a, b, c])
        assert all(gid == 5 for gid in result.values())

    def test_two_separate_duplicate_groups(self):
        a = _event(1, "Jazz Night", _BASE)
        b = _event(2, "Jazz Night", _BASE)
        c = _event(3, "Salsa Dancing", _BASE + timedelta(days=1))
        d = _event(4, "Salsa Dancing", _BASE + timedelta(days=1))
        result = cluster_events([a, b, c, d])
        assert result[1] == 1
        assert result[2] == 1
        assert result[3] == 3
        assert result[4] == 3

    def test_time_gap_prevents_grouping(self):
        a = _event(1, "Jazz Night", _BASE)
        b = _event(2, "Jazz Night", _BASE + timedelta(hours=25))
        assert cluster_events([a, b]) == {}

    def test_venue_mismatch_prevents_grouping(self):
        a = _event(1, "Jazz Night", _BASE, venue_name="Von Krahli")
        b = _event(2, "Jazz Night", _BASE, venue_name="Fotografiska")
        assert cluster_events([a, b]) == {}

    def test_unfiltered_fallback_raises_above_hard_cap(self):
        """P2-3 hardening: cluster_events() called without candidate_pair_ids (the
        O(N^2) Python fallback) must fail loudly above DEDUP_UNFILTERED_FALLBACK_MAX_EVENTS
        rather than silently running the quadratic scan on a large event list. Existing
        small-N white-box tests (all well under the cap) are unaffected."""
        from app.constants.dedup import DEDUP_UNFILTERED_FALLBACK_MAX_EVENTS

        events = [
            _event(i, "Distinct Title", _BASE + timedelta(days=i))
            for i in range(DEDUP_UNFILTERED_FALLBACK_MAX_EVENTS + 1)
        ]
        try:
            cluster_events(events)
            assert False, "expected ValueError above the unfiltered-fallback cap"
        except ValueError as exc:
            assert str(DEDUP_UNFILTERED_FALLBACK_MAX_EVENTS) in str(exc)


# ---------------------------------------------------------------------------
# apply_same_day_title_unions (Fix 1 — deterministic same-day session collapse)
# ---------------------------------------------------------------------------


def _parent_for(events: list) -> dict[int, int]:
    return {e.id: e.id for e in events}


class TestApplySameDayTitleUnions:
    def test_same_title_same_day_unioned(self):
        a = _event(1, "Van Gogh", _BASE, venue_name="Vaba Lava")
        b = _event(2, "Van Gogh", _BASE + timedelta(hours=3), venue_name="Vaba Lava")
        parent = _parent_for([a, b])
        apply_same_day_title_unions(parent, [a, b])
        assert same_group(parent, 1, 2)

    def test_same_title_far_apart_same_day_still_unioned(self):
        # 14h apart — outside the 12h candidate window, but same Tallinn calendar
        # day, so the deterministic same-day collapse still merges them.
        a = _event(1, "Van Gogh", _BASE.replace(hour=9), venue_name="Vaba Lava")
        b = _event(2, "Van Gogh", _BASE.replace(hour=23), venue_name="Vaba Lava")
        assert abs((a.starts_at - b.starts_at).total_seconds()) > TIME_WINDOW_HOURS * 3600
        parent = _parent_for([a, b])
        apply_same_day_title_unions(parent, [a, b])
        assert same_group(parent, 1, 2)

    def test_same_title_different_day_not_unioned(self):
        a = _event(1, "Van Gogh", _BASE, venue_name="Vaba Lava")
        b = _event(2, "Van Gogh", _BASE + timedelta(days=1), venue_name="Vaba Lava")
        parent = _parent_for([a, b])
        apply_same_day_title_unions(parent, [a, b])
        assert not same_group(parent, 1, 2)

    def test_different_title_same_day_not_unioned(self):
        a = _event(1, "Van Gogh", _BASE, venue_name="Vaba Lava")
        b = _event(2, "Monet", _BASE, venue_name="Vaba Lava")
        parent = _parent_for([a, b])
        apply_same_day_title_unions(parent, [a, b])
        assert not same_group(parent, 1, 2)

    def test_same_title_same_day_incompatible_venue_not_unioned(self):
        # Generic title shared across two different venues on the same day must NOT
        # collapse — the venue gate protects against over-merging distinct events.
        a = _event(1, "Jazz Night", _BASE, venue_name="Von Krahli")
        b = _event(2, "Jazz Night", _BASE, venue_name="Fotografiska")
        parent = _parent_for([a, b])
        apply_same_day_title_unions(parent, [a, b])
        assert not same_group(parent, 1, 2)

    def test_unknown_venue_treated_as_compatible(self):
        a = _event(1, "Jazz Night", _BASE, venue_name=None)
        b = _event(2, "Jazz Night", _BASE, venue_name="Von Krahli")
        parent = _parent_for([a, b])
        apply_same_day_title_unions(parent, [a, b])
        assert same_group(parent, 1, 2)

    def test_normalized_title_whitespace_and_case(self):
        a = _event(1, "  Van   GOGH ", _BASE, venue_name="Vaba Lava")
        b = _event(2, "van gogh", _BASE, venue_name="Vaba Lava")
        parent = _parent_for([a, b])
        apply_same_day_title_unions(parent, [a, b])
        assert same_group(parent, 1, 2)

    def test_three_same_day_slots_all_collapse(self):
        slots = [
            _event(i, "Miiamilla", _BASE.replace(hour=10) + timedelta(hours=i),
                   venue_name="Miiamilla")
            for i in range(1, 4)
        ]
        parent = _parent_for(slots)
        apply_same_day_title_unions(parent, slots)
        assert same_group(parent, 1, 2)
        assert same_group(parent, 2, 3)

    def test_tz_boundary_uses_tallinn_date(self):
        # Two UTC instants on different UTC calendar days (07-01 and 07-02) that
        # both fall on 2026-07-02 in Europe/Tallinn (UTC+3 in July). Bucketing on
        # the Tallinn date unions them; a naive UTC date would not.
        a = _event(1, "Night Show", datetime(2026, 7, 1, 22, 0, tzinfo=timezone.utc),
                   venue_name="Club")
        b = _event(2, "Night Show", datetime(2026, 7, 2, 0, 30, tzinfo=timezone.utc),
                   venue_name="Club")
        assert a.starts_at.date() != b.starts_at.date()  # differ in UTC
        parent = _parent_for([a, b])
        apply_same_day_title_unions(parent, [a, b])
        assert same_group(parent, 1, 2)

    def test_fuzzy_compatible_distinct_venue_strings_still_unioned(self):
        """The O(d^2) group-representative pass must still catch two DIFFERENT (not
        exact-string-equal) venue names that clear the fuzzy threshold — not just
        exact matches. Regression test for the linearized _union_by_venue_group
        rewrite (must not accidentally reduce to an exact-only comparison)."""
        a = _event(1, "Jazz Night", _BASE, venue_name="Von Krahli Teater")
        b = _event(2, "Jazz Night", _BASE, venue_name="von krahli teater")
        assert token_set_ratio(a.venue_name.lower(), b.venue_name.lower()) >= 70
        assert a.venue_name != b.venue_name  # distinct strings, not an exact match
        parent = _parent_for([a, b])
        apply_same_day_title_unions(parent, [a, b])
        assert same_group(parent, 1, 2)

    def test_mixed_bucket_identical_fuzzy_distinct_and_none_venues(self):
        """One bucket exercising every group kind at once: two members with an
        identical venue string (exact-group chaining), one with a fuzzy-compatible
        variant of that string (cross-group fuzzy union), one with a wholly
        incompatible venue (must stay isolated from the rest), and one with an
        unknown (None) venue (must bridge everything else together, including the
        otherwise-incompatible one — matching _venue_compatible's "None is always
        compatible" rule)."""
        exact_1 = _event(1, "Miiamilla", _BASE, venue_name="Kanuti Gildi SAAL")
        exact_2 = _event(2, "Miiamilla", _BASE, venue_name="Kanuti Gildi SAAL")
        fuzzy = _event(3, "Miiamilla", _BASE, venue_name="kanuti gildi saal")
        incompatible = _event(4, "Miiamilla", _BASE, venue_name="Fotografiska")
        unknown = _event(5, "Miiamilla", _BASE, venue_name=None)
        members = [exact_1, exact_2, fuzzy, incompatible, unknown]
        assert not _venue_compatible(exact_1.venue_name, incompatible.venue_name)

        parent = _parent_for(members)
        apply_same_day_title_unions(parent, members)

        # Exact + fuzzy variants of the same venue collapse together.
        assert same_group(parent, 1, 2)
        assert same_group(parent, 1, 3)
        # The None-venue member bridges everything, including the otherwise-
        # incompatible venue — reproducing the old O(k^2) loop's behavior, where any
        # pair involving a None venue was unioned directly.
        assert same_group(parent, 1, 5)
        assert same_group(parent, 4, 5)
        assert same_group(parent, 1, 4)  # transitively, via the None hub

    def test_incompatible_venues_stay_isolated_with_no_none_bridge(self):
        """Without a None-venue member to bridge them, two mutually-incompatible
        named venues in the same bucket must NOT be unioned — the isolation the
        venue gate exists to preserve must survive the grouped-comparison rewrite."""
        a = _event(1, "Jazz Night", _BASE, venue_name="Von Krahli")
        b = _event(2, "Jazz Night", _BASE, venue_name="Fotografiska")
        c = _event(3, "Jazz Night", _BASE, venue_name="Kellerteater")
        parent = _parent_for([a, b, c])
        apply_same_day_title_unions(parent, [a, b, c])
        assert not same_group(parent, 1, 2)
        assert not same_group(parent, 1, 3)
        assert not same_group(parent, 2, 3)


# ---------------------------------------------------------------------------
# same_group
# ---------------------------------------------------------------------------


class TestSameGroup:
    def test_disjoint_false(self):
        assert same_group({1: 1, 2: 2}, 1, 2) is False

    def test_after_union_true(self):
        from app.dedup.rules import union

        parent = {1: 1, 2: 2}
        union(parent, 1, 2)
        assert same_group(parent, 1, 2) is True

    def test_reflexive(self):
        assert same_group({1: 1}, 1, 1) is True


# ---------------------------------------------------------------------------
# build_cluster_assignments (Fix 3 — quality-based representative)
# ---------------------------------------------------------------------------


class TestBuildClusterAssignments:
    def _cluster(self, events: list) -> dict[int, int]:
        from app.dedup.rules import union

        parent = _parent_for(events)
        for e in events[1:]:
            union(parent, events[0].id, e.id)
        ids = [e.id for e in events]
        events_by_id = {e.id: e for e in events}
        return build_cluster_assignments(parent, ids, events_by_id)

    def test_high_quality_member_becomes_representative(self):
        # Member 3 has price + address + coords + description; the others are bare
        # → group_id resolves to 3, not min(id).
        a = _event(1, "Show", _BASE)
        b = _event(2, "Show", _BASE)
        c = _event(
            3, "Show", _BASE,
            price_min=10.0, venue_address="Main St 1",
            lat=59.4, lng=24.7, description_orig="full description",
        )
        assert self._cluster([a, b, c]) == {1: 3, 2: 3, 3: 3}

    def test_equal_quality_falls_back_to_min_id(self):
        # No distinguishing data on any member → historical min(id) root wins.
        a = _event(10, "Show", _BASE)
        b = _event(5, "Show", _BASE)
        c = _event(7, "Show", _BASE)
        assert all(gid == 5 for gid in self._cluster([a, b, c]).values())

    def test_description_length_breaks_remaining_tie(self):
        # Equal price/address/coords presence (all absent) → longer description wins.
        a = _event(1, "Show", _BASE, description_orig="short")
        b = _event(2, "Show", _BASE, description_orig="a considerably longer blurb")
        assert self._cluster([a, b]) == {1: 2, 2: 2}

    def test_singleton_excluded(self):
        a = _event(1, "Solo", _BASE)
        assert build_cluster_assignments({1: 1}, [1], {1: a}) == {}

    def test_published_member_pins_representative_over_richer_draft(self):
        # A published but data-poor member stays representative even when a draft
        # sibling has richer data — flipping would orphan the published row as a
        # duplicate (classifier skips non-canonical; publish gate is dedup-unaware).
        published = _event(1, "Show", _BASE, status="published")
        rich_draft = _event(
            2, "Show", _BASE, status="draft",
            price_min=10.0, venue_address="Main St 1",
            lat=59.4, lng=24.7, description_orig="full description",
        )
        assert self._cluster([published, rich_draft]) == {1: 1, 2: 1}

    def test_published_outranks_classified_regardless_of_quality(self):
        # published (2) outranks classified (1) even when the classified member has
        # richer data — the published row must remain canonical.
        classified = _event(
            1, "Show", _BASE, status="classified",
            price_min=10.0, venue_address="A", lat=59.4, lng=24.7,
            description_orig="rich",
        )
        published = _event(2, "Show", _BASE, status="published")
        assert self._cluster([classified, published]) == {1: 2, 2: 2}

    def test_organizer_submission_merges_with_scraped_duplicate_no_special_casing(self):
        # An organizer-submitted event (source=user_submission) dedup-merges with
        # a scraped copy of the same real-world event exactly like any other pair
        # — representative selection (status pin, then data-quality rank) has no
        # source-awareness ("no special-casing").
        submitted = _event(1, "Show", _BASE, status="published")
        submitted.submitted_by_organizer_id = 7
        scraped = _event(
            2, "Show", _BASE, status="draft",
            price_min=10.0, venue_address="Main St 1",
            lat=59.4, lng=24.7, description_orig="full description",
        )
        scraped.submitted_by_organizer_id = None
        # Published pin wins regardless of source or the richer scraped data.
        assert self._cluster([submitted, scraped]) == {1: 1, 2: 1}


# ---------------------------------------------------------------------------
# build_cluster_assignments — claimed tiebreak (#418)
# ---------------------------------------------------------------------------


class TestBuildClusterAssignmentsClaimedTiebreak:
    def _cluster(self, events: list, claimed_event_ids: frozenset[int]) -> dict[int, int]:
        from app.dedup.rules import union

        parent = _parent_for(events)
        for e in events[1:]:
            union(parent, events[0].id, e.id)
        ids = [e.id for e in events]
        events_by_id = {e.id: e for e in events}
        return build_cluster_assignments(
            parent, ids, events_by_id, claimed_event_ids=claimed_event_ids
        )

    def test_claimed_beats_unclaimed_at_equal_status_and_quality(self):
        claimed = _event(1, "Show", _BASE)
        unclaimed = _event(2, "Show", _BASE)
        assert self._cluster([claimed, unclaimed], frozenset({1})) == {1: 1, 2: 1}
        # Order flips when the claim sits on the other member — not just min(id).
        assert self._cluster([claimed, unclaimed], frozenset({2})) == {1: 2, 2: 2}

    def test_claimed_beats_richer_unclaimed_quality(self):
        # Ranked between status-rank and quality-rank —
        # claimed outranks quality-completeness outright: a data-poor claimed
        # member still wins over a richer unclaimed one.
        claimed = _event(1, "Show", _BASE)
        richer_unclaimed = _event(
            2, "Show", _BASE,
            price_min=10.0, venue_address="Main St 1",
            lat=59.4, lng=24.7, description_orig="full description",
        )
        assert self._cluster([claimed, richer_unclaimed], frozenset({1})) == {1: 1, 2: 1}

    def test_published_status_pin_outranks_claimed_draft(self):
        # Status-rank still dominates the claimed tiebreak — an already-
        # published unclaimed member is never demoted below a claimed draft.
        published_unclaimed = _event(1, "Show", _BASE, status="published")
        claimed_draft = _event(2, "Show", _BASE, status="draft")
        assert self._cluster([published_unclaimed, claimed_draft], frozenset({2})) == {
            1: 1,
            2: 1,
        }

    def test_claimed_vs_claimed_falls_back_to_quality_rank(self):
        # Both claimed → the tiebreak is a wash, quality-rank decides same as
        # an unclaimed cluster would.
        a = _event(1, "Show", _BASE)
        b = _event(
            2, "Show", _BASE,
            price_min=10.0, venue_address="Main St 1",
            lat=59.4, lng=24.7, description_orig="full description",
        )
        assert self._cluster([a, b], frozenset({1, 2})) == {1: 2, 2: 2}

    def test_no_claims_behaves_like_before(self):
        a = _event(10, "Show", _BASE)
        b = _event(5, "Show", _BASE)
        assert self._cluster([a, b], frozenset()) == {10: 5, 5: 5}


# ---------------------------------------------------------------------------
# cluster_events — candidate_pair_ids path
# ---------------------------------------------------------------------------


def test_cluster_events_candidate_pairs_unions_and_skips_missing_ids():
    # Titles differ in normalized form so apply_same_day_title_unions (which runs
    # first inside cluster_events and unions same-normalized-title/same-day events)
    # can NOT pre-union them — the grouping must come from the candidate-pair loop
    # under test. token_set_ratio stays ~100 (one title is a token-subset of the
    # other) so is_candidate_pair still matches.
    a = _event(1, "Jazz Night", _BASE, venue_name="Club X")
    b = _event(2, "Jazz Night Live Session", _BASE, venue_name="Club X")
    events = [a, b]

    # sanity: the same-day title union alone does NOT group these differing titles
    parent = {1: 1, 2: 2}
    apply_same_day_title_unions(parent, events)
    assert _find(parent, 1) != _find(parent, 2)

    # (1, 99): id 99 is absent -> the `b is None: continue` branch.
    # (1, 2): a real duplicate pair -> union into one group via the candidate loop.
    result = cluster_events(events, candidate_pair_ids=[(1, 99), (1, 2)])

    assert result[1] == result[2]


def test_cluster_events_candidate_pairs_non_duplicate_not_grouped():
    a = _event(1, "Jazz Night", _BASE, venue_name="Club X")
    b = _event(2, "Opera Gala", _BASE, venue_name="Opera House")

    result = cluster_events([a, b], candidate_pair_ids=[(1, 2)])

    # unrelated titles/venues -> is_candidate_pair False -> no group
    assert result == {}
