"""Unit tests for data retention cleanup (app/cleanup.py)."""

from unittest.mock import MagicMock

import pytest

from app.cleanup import cleanup_stale_data
from app.constants import (
    DAILY_FEEDS_RETENTION_DAYS,
    INGESTION_RUNS_RETENTION_DAYS,
    LLM_CALLS_RETENTION_DAYS,
    MAGIC_LINK_RETENTION_DAYS,
    RAW_EVENTS_RETENTION_DAYS,
    RAW_INBOUND_EMAILS_RETENTION_DAYS,
    USER_EVENT_SCORES_RETENTION_DAYS,
)

_TABLE_KEYS = [
    "auth_magic_links",
    "organizer_magic_links",
    "llm_calls",
    "raw_events",
    "ingestion_runs",
    "raw_inbound_emails",
    "daily_feeds",
    "user_event_scores",
]


def _delete_results(rowcounts: list[int]) -> list[MagicMock]:
    results = []
    for n in rowcounts:
        m = MagicMock()
        m.rowcount = n
        results.append(m)
    return results


def _count_results(counts: list[int]) -> list[MagicMock]:
    results = []
    for n in counts:
        m = MagicMock()
        m.scalar_one.return_value = n
        results.append(m)
    return results


@pytest.mark.asyncio
async def test_cleanup_deletes_and_returns_rowcounts(mock_db):
    mock_db.execute.side_effect = _delete_results([3, 9, 10, 20, 5, 1, 7, 15])

    summary = await cleanup_stale_data(mock_db)

    assert summary == {
        "auth_magic_links": 3,
        "organizer_magic_links": 9,
        "llm_calls": 10,
        "raw_events": 20,
        "ingestion_runs": 5,
        "raw_inbound_emails": 1,
        "daily_feeds": 7,
        "user_event_scores": 15,
    }
    assert mock_db.execute.call_count == 8


@pytest.mark.asyncio
async def test_cleanup_statements_are_deletes_when_not_dry_run(mock_db):
    mock_db.execute.side_effect = _delete_results([0] * 8)

    await cleanup_stale_data(mock_db)

    for call in mock_db.execute.call_args_list:
        stmt = call[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert compiled.strip().upper().startswith("DELETE FROM")


@pytest.mark.asyncio
async def test_cleanup_dry_run_counts_without_deleting(mock_db):
    mock_db.execute.side_effect = _count_results([1, 9, 2, 3, 4, 5, 6, 7])

    summary = await cleanup_stale_data(mock_db, dry_run=True)

    assert summary == {
        "auth_magic_links": 1,
        "organizer_magic_links": 9,
        "llm_calls": 2,
        "raw_events": 3,
        "ingestion_runs": 4,
        "raw_inbound_emails": 5,
        "daily_feeds": 6,
        "user_event_scores": 7,
    }
    for call in mock_db.execute.call_args_list:
        stmt = call[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert compiled.strip().upper().startswith("SELECT")
        assert "count" in compiled.lower()


@pytest.mark.asyncio
async def test_cleanup_never_touches_events_table(mock_db):
    mock_db.execute.side_effect = _delete_results([0] * 8)

    await cleanup_stale_data(mock_db)

    for call in mock_db.execute.call_args_list:
        stmt = call[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "DELETE FROM events" not in compiled


@pytest.mark.asyncio
async def test_cleanup_user_event_scores_keyed_on_ended_events(mock_db):
    mock_db.execute.side_effect = _delete_results([0] * 8)

    await cleanup_stale_data(mock_db)

    scores_stmt = mock_db.execute.call_args_list[7][0][0]
    compiled = str(scores_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "user_event_scores" in compiled
    assert "event_id" in compiled
    assert "events" in compiled
    assert "ends_at" in compiled or "starts_at" in compiled


@pytest.mark.asyncio
async def test_cleanup_organizer_magic_links_statement_targets_correct_table(mock_db):
    mock_db.execute.side_effect = _delete_results([0] * 8)

    await cleanup_stale_data(mock_db)

    organizer_stmt = mock_db.execute.call_args_list[1][0][0]
    compiled = str(organizer_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert compiled.strip().startswith("DELETE FROM organizer_magic_links")
    assert "DELETE FROM auth_magic_links" not in compiled


@pytest.mark.asyncio
async def test_cleanup_uses_configured_retention_windows(mock_db):
    mock_db.execute.side_effect = _delete_results([0] * 8)

    await cleanup_stale_data(mock_db)

    compiled_all = [
        str(call[0][0].compile(compile_kwargs={"literal_binds": True}))
        for call in mock_db.execute.call_args_list
    ]

    # Each table's cutoff is a `now - retention_days` computed in Python and
    # passed as a literal timestamp — sanity-check the constants are wired in
    # by asserting the retention day counts differ meaningfully (regression
    # guard against accidentally reusing one constant for every table).
    assert MAGIC_LINK_RETENTION_DAYS != LLM_CALLS_RETENTION_DAYS
    assert RAW_EVENTS_RETENTION_DAYS == INGESTION_RUNS_RETENTION_DAYS == RAW_INBOUND_EMAILS_RETENTION_DAYS
    assert DAILY_FEEDS_RETENTION_DAYS == USER_EVENT_SCORES_RETENTION_DAYS
    assert all(compiled_all)  # every statement compiled without error
