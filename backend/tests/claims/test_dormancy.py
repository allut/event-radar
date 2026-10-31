"""Tests for app.claims.dormancy: claimed-vs-claimed dormancy (#418)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app._generated.shared_constants import CLAIM_STATUS_APPROVED
from app.claims.dormancy import (
    apply_claim_dormancy,
    load_claims_for_events,
    resolve_claim_dormancy,
)
from app.events.queries import event_series_key, serialize_event_series_key
from tests.conftest import build_event



def _claim(claim_id: int, *, publisher_id=None, event_series_key=None, status=CLAIM_STATUS_APPROVED):
    return SimpleNamespace(
        id=claim_id, publisher_id=publisher_id, event_series_key=event_series_key, status=status
    )


class TestResolveClaimDormancy:
    def test_claimed_vs_claimed_collision_loser_goes_dormant(self):
        # Cluster {1, 2} collapses onto representative 2; both are claimed
        # by different claims — claim on the losing member (1) goes dormant,
        # the representative's own claim (on 2) reactivates.
        claim_a, claim_b = _claim(101), _claim(102)
        dormant, reactivate = resolve_claim_dormancy(
            {1: 2, 2: 2}, {1: claim_a, 2: claim_b}
        )
        assert dormant == {101}
        assert reactivate == {102}

    def test_unclaimed_loser_produces_no_dormancy(self):
        dormant, reactivate = resolve_claim_dormancy({1: 2, 2: 2}, {2: _claim(102)})
        assert dormant == set()
        assert reactivate == {102}

    def test_same_claim_on_both_sides_is_not_dormant(self):
        # One Claim (e.g. a Series claim) can legitimately match more than
        # one clustered event's series key — it never marks itself dormant.
        claim = _claim(101, event_series_key="k")
        dormant, reactivate = resolve_claim_dormancy({1: 2, 2: 2}, {1: claim, 2: claim})
        assert dormant == set()
        assert reactivate == {101}

    def test_singleton_claimed_event_reactivates(self):
        # build_cluster_assignments excludes singleton events entirely — a
        # claimed event with no colliding duplicate this pass is trivially
        # its own canonical representative and must reactivate.
        dormant, reactivate = resolve_claim_dormancy({}, {1: _claim(101)})
        assert dormant == set()
        assert reactivate == {101}

    def test_decollision_reactivates_a_previously_dormant_claim(self):
        # Claim 101 went dormant in a prior pass because event 1 lost to
        # event 2. This pass, event 2 is gone (cancelled/aged out) — event 1
        # is now a singleton, absent from `assignments` entirely — its claim
        # must reactivate, not stay dormant forever.
        dormant, reactivate = resolve_claim_dormancy({}, {1: _claim(101)})
        assert 101 not in dormant
        assert 101 in reactivate


class TestApplyClaimDormancy:
    @pytest.mark.asyncio
    async def test_dormant_wins_over_reactivate_for_same_claim(self, mock_db):
        # The same claim id colliding in one cluster and winning in another
        # within one pass (see resolve_claim_dormancy docstring) must end up
        # dormant, not reactivated.
        await apply_claim_dormancy(mock_db, {101}, {101, 102})

        assert mock_db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_no_op_when_both_sets_empty(self, mock_db):
        await apply_claim_dormancy(mock_db, set(), set())

        mock_db.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# load_claims_for_events — durable-key re-matching (#418)
# ---------------------------------------------------------------------------


class TestLoadClaimsForEvents:
    def _mock_db(self, publisher_rows: list[tuple[int, int]], claims: list) -> MagicMock:
        db = MagicMock()
        exec_result = MagicMock()
        exec_result.all = MagicMock(return_value=publisher_rows)
        db.execute = AsyncMock(return_value=exec_result)
        scalars_result = MagicMock()
        scalars_result.all = MagicMock(return_value=claims)
        db.scalars = AsyncMock(return_value=scalars_result)
        return db

    @pytest.mark.asyncio
    async def test_publisher_matched_event_resolves_fienta_claim(self):
        # Mirrors a Fienta organizer_id claim: the event's EventSource row
        # carries the durable Publisher id (itself keyed on organizer_id),
        # never the event's own id.
        event = build_event(event_id=501, title="Show", venue_name=None)
        claim = _claim(9, publisher_id=55)
        db = self._mock_db(publisher_rows=[(501, 55)], claims=[claim])

        result = await load_claims_for_events(db, [event])

        assert result == {501: claim}

    @pytest.mark.asyncio
    async def test_in_lists_are_chunked(self):
        # Big-O audit M4: every IN list is split at SQL_IN_CHUNK_SIZE so
        # a large window can't exceed Postgres's bind-parameter cap.
        events = [
            build_event(event_id=i, title=f"Show {i}", venue_name=None) for i in range(1, 6)
        ]
        db = self._mock_db(publisher_rows=[], claims=[])

        with patch("app.claims.dormancy.SQL_IN_CHUNK_SIZE", 2):
            await load_claims_for_events(db, events)

        # 5 events / chunk 2 -> 3 EventSource queries + 3 Venue-name queries.
        assert db.execute.await_count == 6
        # 5 distinct series keys / chunk 2 -> 3 Claim queries.
        assert db.scalars.await_count == 3

    @pytest.mark.asyncio
    async def test_kumu_ech_style_constant_publisher_matches_too(self):
        # KUMU/ECH Publishers carry no external_id (whole-source constant) —
        # matching is identical, just a different-sourced publisher_id.
        event = build_event(event_id=777, title="Exhibit", venue_name=None)
        claim = _claim(9, publisher_id=3)
        db = self._mock_db(publisher_rows=[(777, 3)], claims=[claim])

        result = await load_claims_for_events(db, [event])

        assert result == {777: claim}

    @pytest.mark.asyncio
    async def test_piletilevi_series_key_recomputed_from_this_rows_own_fields(self):
        # No Publisher (unresolved promoter) → falls back to the Piletilevi
        # Series claim key, recomputed fresh from *this* event row's own
        # title_orig/venue_name — never the event's primary key.
        event = build_event(event_id=9001, title="Jazz Night", venue_name="Club X")
        key = serialize_event_series_key(event_series_key("Jazz Night", "Club X"))
        claim = _claim(9, event_series_key=key)
        db = self._mock_db(publisher_rows=[], claims=[claim])

        result = await load_claims_for_events(db, [event])

        assert result == {9001: claim}

    @pytest.mark.asyncio
    async def test_new_reingested_occurrence_rematches_series_claim_by_key(self):
        # A freshly re-ingested occurrence is a BRAND NEW Event row (never
        # seen before, distinct id from whatever row the claim was first
        # granted against) — re-matching must still succeed purely from its
        # own source-provided title/venue.
        original_grant_event_id = 1
        new_occurrence = build_event(event_id=99999, title="Jazz Night", venue_name="Club X")
        key = serialize_event_series_key(event_series_key("Jazz Night", "Club X"))
        claim = _claim(9, event_series_key=key)
        db = self._mock_db(publisher_rows=[], claims=[claim])

        result = await load_claims_for_events(db, [new_occurrence])

        assert result == {new_occurrence.id: claim}
        assert new_occurrence.id != original_grant_event_id

    @pytest.mark.asyncio
    async def test_no_matching_claim_leaves_event_out_of_result(self):
        event = build_event(event_id=1, title="Unclaimed Show", venue_name="Nowhere")
        db = self._mock_db(publisher_rows=[], claims=[])

        result = await load_claims_for_events(db, [event])

        assert result == {}

    @pytest.mark.asyncio
    async def test_empty_events_short_circuits_with_no_queries(self):
        db = self._mock_db(publisher_rows=[], claims=[])

        result = await load_claims_for_events(db, [])

        assert result == {}
        db.execute.assert_not_awaited()
        db.scalars.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_publisher_match_takes_precedence_over_series_key(self):
        # An event with a resolved Publisher never falls back to the
        # series-key path, even if its title/venue would also collide with
        # an unrelated Series claim's key.
        event = build_event(event_id=501, title="Jazz Night", venue_name="Club X")
        publisher_claim = _claim(9, publisher_id=55)
        stray_series_claim = _claim(
            10, event_series_key=serialize_event_series_key(
                event_series_key("Jazz Night", "Club X")
            )
        )
        db = self._mock_db(
            publisher_rows=[(501, 55)], claims=[publisher_claim, stray_series_claim]
        )

        result = await load_claims_for_events(db, [event])

        assert result == {501: publisher_claim}

    @pytest.mark.asyncio
    async def test_venue_linked_event_matches_via_resolved_venue_name(self):
        # A venue-linked event (Event.venue_id set) has its bare venue_name
        # left NULL at write time (#176) — the series-key fallback must
        # resolve the linked Venue's name (as resolve_claim_target() did at
        # claim-creation time), not read the NULL column directly.
        event = build_event(event_id=501, title="Jazz Night", venue_name=None)
        key = serialize_event_series_key(event_series_key("Jazz Night", "Club X"))
        claim = _claim(9, event_series_key=key)

        db = MagicMock()
        publisher_exec_result = MagicMock(all=MagicMock(return_value=[]))
        venue_exec_result = MagicMock(
            all=MagicMock(return_value=[(501, None, "Club X", None)])
        )
        db.execute = AsyncMock(side_effect=[publisher_exec_result, venue_exec_result])
        scalars_result = MagicMock(all=MagicMock(return_value=[claim]))
        db.scalars = AsyncMock(return_value=scalars_result)

        result = await load_claims_for_events(db, [event])

        assert result == {501: claim}
