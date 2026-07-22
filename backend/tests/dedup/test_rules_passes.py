"""Tests for app.dedup.rules DB-level pass helpers and the candidate_pair_ids
path of cluster_events (missing-id skip + union)."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.constants import TALLINN_TZ
from app.dedup import rules
from app.dedup.rules import (
    candidate_pair_ids_in_window,
    clear_stale_dedup_groups,
    cluster_events,
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
# cluster_events — candidate_pair_ids path
# ---------------------------------------------------------------------------


def test_cluster_events_candidate_pairs_unions_and_skips_missing_ids():
    # Titles differ in normalized form so apply_same_day_title_unions (which runs
    # first inside cluster_events and unions same-normalized-title/same-day events)
    # can NOT pre-union them — the grouping must come from the candidate-pair loop
    # under test. token_set_ratio stays ~100 (one title is a token-subset of the
    # other) so is_candidate_pair still matches.
    a = _event(1, "Jazz Night", venue="Club X")
    b = _event(2, "Jazz Night Live Session", venue="Club X")
    events = [a, b]

    # sanity: the same-day title union alone does NOT group these differing titles
    from app.dedup.rules import _find, apply_same_day_title_unions

    parent = {1: 1, 2: 2}
    apply_same_day_title_unions(parent, events)
    assert _find(parent, 1) != _find(parent, 2)

    # (1, 99): id 99 is absent -> the `b is None: continue` branch.
    # (1, 2): a real duplicate pair -> union into one group via the candidate loop.
    result = cluster_events(events, candidate_pair_ids=[(1, 99), (1, 2)])

    assert result[1] == result[2]


def test_cluster_events_candidate_pairs_non_duplicate_not_grouped():
    a = _event(1, "Jazz Night", venue="Club X")
    b = _event(2, "Opera Gala", venue="Opera House")

    result = cluster_events([a, b], candidate_pair_ids=[(1, 2)])

    # unrelated titles/venues -> is_candidate_pair False -> no group
    assert result == {}


# ---------------------------------------------------------------------------
# run_dedup_pass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_dedup_pass_empty_returns_zeroes(mock_db, monkeypatch):
    monkeypatch.setattr(rules, "load_dedup_candidate_events", AsyncMock(return_value=[]))

    result = await run_dedup_pass(mock_db)

    assert result == {"total": 0, "grouped": 0, "groups": 0, "updated": 0}


@pytest.mark.asyncio
async def test_run_dedup_pass_assigns_and_counts_updates(mock_db, monkeypatch):
    a = _event(1, "Jazz Night", venue="Club X")
    b = _event(2, "Jazz Night", venue="Club X")

    monkeypatch.setattr(
        rules, "load_dedup_candidate_events", AsyncMock(return_value=[a, b])
    )
    monkeypatch.setattr(
        rules, "candidate_pair_ids_in_window", AsyncMock(return_value=[(1, 2)])
    )
    monkeypatch.setattr(rules, "clear_stale_dedup_groups", AsyncMock())

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
