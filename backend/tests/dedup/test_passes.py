"""Tests for app.dedup.passes: DB-level dedup pass helpers."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants.core import TALLINN_TZ
from app.constants.dedup import DEDUP_LOOKBACK_DAYS
from app.dedup import passes
from app.dedup.passes import (
    bulk_assign_dedup_groups,
    candidate_pair_ids_in_window,
    clear_stale_dedup_groups,
    dedup_window_cutoff,
    load_dedup_candidate_events,
    run_dedup_pass,
)

_BASE = datetime(2026, 7, 1, 20, 0, 0, tzinfo=TALLINN_TZ)


def _event(eid, title, venue=None, status="draft"):
    e = MagicMock()
    e.id = eid
    e.title_orig = title
    e.starts_at = _BASE
    e.venue_name = venue
    e.status = status
    e.price_min = None
    e.venue_address = None
    e.lat = None
    e.lng = None
    e.description_orig = ""
    e.dedup_group_id = None
    return e


# ---------------------------------------------------------------------------
# run_dedup_pass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_dedup_pass_empty_returns_zeroes(mock_db, monkeypatch):
    monkeypatch.setattr(passes, "load_dedup_candidate_events", AsyncMock(return_value=[]))

    result = await run_dedup_pass(mock_db)

    assert result == {"total": 0, "grouped": 0, "groups": 0, "updated": 0}


@pytest.mark.asyncio
async def test_run_dedup_pass_assigns_and_counts_updates(mock_db, monkeypatch):
    a = _event(1, "Jazz Night", venue="Club X")
    b = _event(2, "Jazz Night", venue="Club X")

    monkeypatch.setattr(
        passes, "load_dedup_candidate_events", AsyncMock(return_value=[a, b])
    )
    monkeypatch.setattr(
        passes, "candidate_pair_ids_in_window", AsyncMock(return_value=[(1, 2)])
    )
    monkeypatch.setattr(passes, "clear_stale_dedup_groups", AsyncMock())
    monkeypatch.setattr(passes, "load_claims_for_events", AsyncMock(return_value={}))

    result = await run_dedup_pass(mock_db)

    assert result["total"] == 2
    assert result["grouped"] == 2
    assert result["groups"] == 1
    assert result["updated"] == 2
    # group ids were written onto the events
    assert a.dedup_group_id == b.dedup_group_id is not None


# ---------------------------------------------------------------------------
# DB-level query helpers
# ---------------------------------------------------------------------------


def test_dedup_window_cutoff_is_in_the_past():
    assert dedup_window_cutoff() < datetime.now(tz=TALLINN_TZ)


@pytest.mark.asyncio
async def test_candidate_pair_ids_in_window_maps_rows_to_tuples(mock_db):
    exec_result = MagicMock()
    exec_result.all.return_value = [(1, 2), (3, 4)]
    mock_db.execute.return_value = exec_result

    pairs = await candidate_pair_ids_in_window(mock_db, dedup_window_cutoff())

    assert pairs == [(1, 2), (3, 4)]
    mock_db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_load_dedup_candidate_events_returns_list(mock_db):
    a, b = _event(1, "x"), _event(2, "y")
    scalars_result = MagicMock()
    scalars_result.all.return_value = [a, b]
    mock_db.scalars.return_value = scalars_result

    events = await load_dedup_candidate_events(mock_db, dedup_window_cutoff())

    assert events == [a, b]


@pytest.mark.asyncio
async def test_clear_stale_dedup_groups_executes_update(mock_db):
    await clear_stale_dedup_groups(mock_db, dedup_window_cutoff())

    mock_db.execute.assert_awaited_once()


class TestLookbackConstant:
    def test_lookback_days_reasonable(self):
        # Must be positive and not excessively large (>365 defeats the purpose)
        assert 7 <= DEDUP_LOOKBACK_DAYS <= 365


class TestBulkAssignDedupGroups:
    @pytest.mark.asyncio
    async def test_changed_rows_share_one_values_update_and_memory_is_synced(
        self, mock_db, make_event
    ):
        a, b, c = make_event(1), make_event(2), make_event(3)
        a.dedup_group_id = None
        b.dedup_group_id = None
        c.dedup_group_id = 3  # unchanged

        changed = await bulk_assign_dedup_groups(
            mock_db, [a, b, c], {1: 1, 2: 1, 3: 3}
        )

        assert changed == 2
        mock_db.execute.assert_awaited_once()  # one UPDATE, not one per group
        assert a.dedup_group_id == 1 and b.dedup_group_id == 1

    @pytest.mark.asyncio
    async def test_no_changes_issue_no_update(self, mock_db, make_event):
        a = make_event(1)
        a.dedup_group_id = 1

        assert await bulk_assign_dedup_groups(mock_db, [a], {1: 1}) == 0
        mock_db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_chunks_at_configured_size(self, mock_db, make_event):
        events = [make_event(i) for i in range(1, 6)]
        for e in events:
            e.dedup_group_id = None

        with patch("app.dedup.passes.DEDUP_BULK_UPDATE_CHUNK_SIZE", 2):
            await bulk_assign_dedup_groups(mock_db, events, {e.id: 1 for e in events})

        assert mock_db.execute.await_count == 3  # 2 + 2 + 1


# ---------------------------------------------------------------------------
# candidate_pair_ids_in_window — SQL bounds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pair_query_has_upper_date_bound(mock_db):
    result = MagicMock()
    result.all.return_value = []
    mock_db.execute.return_value = result

    await candidate_pair_ids_in_window(mock_db, datetime.now(TALLINN_TZ))

    compiled = str(mock_db.execute.call_args.args[0])
    assert compiled.count("starts_at <=") >= 3  # window upper bound + a/b lookahead
