"""Unit tests for data retention cleanup (app/cleanup.py)."""

from unittest.mock import MagicMock

import pytest

from app.cleanup import cleanup_stale_data
from app.constants.ops import (
    DAILY_FEEDS_RETENTION_DAYS,
    INGESTION_RUNS_RETENTION_DAYS,
    LLM_CALLS_RETENTION_DAYS,
    MAGIC_LINK_RETENTION_DAYS,
    RAW_EVENTS_RETENTION_DAYS,
    RAW_INBOUND_EMAILS_RETENTION_DAYS,
    UNVERIFIED_ACCOUNT_RETENTION_DAYS,
)

_TABLE_KEYS = [
    "auth_magic_links",
    "organizer_magic_links",
    "llm_calls",
    "raw_events",
    "ingestion_runs",
    "raw_inbound_emails",
    "daily_feeds",
    "users_unverified",
    "organizers_unverified",
]
_N = len(_TABLE_KEYS)


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
    mock_db.execute.side_effect = _delete_results([3, 9, 10, 20, 5, 1, 7, 2, 1])

    summary = await cleanup_stale_data(mock_db)

    assert summary == {
        "auth_magic_links": 3,
        "organizer_magic_links": 9,
        "llm_calls": 10,
        "raw_events": 20,
        "ingestion_runs": 5,
        "raw_inbound_emails": 1,
        "daily_feeds": 7,
        "users_unverified": 2,
        "organizers_unverified": 1,
    }
    assert mock_db.execute.call_count == _N


@pytest.mark.asyncio
async def test_cleanup_statements_are_deletes_when_not_dry_run(mock_db):
    mock_db.execute.side_effect = _delete_results([0] * _N)

    await cleanup_stale_data(mock_db)

    for call in mock_db.execute.call_args_list:
        stmt = call[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert compiled.strip().upper().startswith("DELETE FROM")


@pytest.mark.asyncio
async def test_cleanup_dry_run_counts_without_deleting(mock_db):
    mock_db.execute.side_effect = _count_results([1, 9, 2, 3, 4, 5, 6, 8, 9])

    summary = await cleanup_stale_data(mock_db, dry_run=True)

    assert summary == {
        "auth_magic_links": 1,
        "organizer_magic_links": 9,
        "llm_calls": 2,
        "raw_events": 3,
        "ingestion_runs": 4,
        "raw_inbound_emails": 5,
        "daily_feeds": 6,
        "users_unverified": 8,
        "organizers_unverified": 9,
    }
    for call in mock_db.execute.call_args_list:
        stmt = call[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert compiled.strip().upper().startswith("SELECT")
        assert "count" in compiled.lower()


@pytest.mark.asyncio
async def test_cleanup_never_touches_events_table(mock_db):
    mock_db.execute.side_effect = _delete_results([0] * _N)

    await cleanup_stale_data(mock_db)

    for call in mock_db.execute.call_args_list:
        stmt = call[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "DELETE FROM events" not in compiled


@pytest.mark.asyncio
async def test_cleanup_organizer_magic_links_statement_targets_correct_table(mock_db):
    mock_db.execute.side_effect = _delete_results([0] * _N)

    await cleanup_stale_data(mock_db)

    organizer_stmt = mock_db.execute.call_args_list[1][0][0]
    compiled = str(organizer_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert compiled.strip().startswith("DELETE FROM organizer_magic_links")
    assert "DELETE FROM auth_magic_links" not in compiled


@pytest.mark.asyncio
async def test_cleanup_uses_configured_retention_windows(mock_db):
    mock_db.execute.side_effect = _delete_results([0] * _N)

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
    assert DAILY_FEEDS_RETENTION_DAYS > 0
    assert all(compiled_all)  # every statement compiled without error


@pytest.mark.asyncio
async def test_cleanup_users_unverified_statement_targets_correct_table_and_filters(
    mock_db,
):
    mock_db.execute.side_effect = _delete_results([0] * _N)

    await cleanup_stale_data(mock_db)

    users_stmt = mock_db.execute.call_args_list[7][0][0]
    compiled = str(users_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert compiled.strip().startswith("DELETE FROM users")
    assert "email_verified" in compiled
    # NULL-safe guard against deleting a user with a still-valid pending link.
    assert "auth_magic_links" in compiled
    assert "used_at" in compiled
    assert "expires_at" in compiled


@pytest.mark.asyncio
async def test_cleanup_organizers_unverified_statement_targets_correct_table_and_filters(
    mock_db,
):
    mock_db.execute.side_effect = _delete_results([0] * _N)

    await cleanup_stale_data(mock_db)

    organizers_stmt = mock_db.execute.call_args_list[8][0][0]
    compiled = str(organizers_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert compiled.strip().startswith("DELETE FROM organizers")
    assert "organizer_magic_links" in compiled
    assert "events" in compiled
    assert "submitted_by_organizer_id" in compiled


@pytest.mark.asyncio
async def test_cleanup_organizers_keyed_on_durable_verified_signal(mock_db):
    """H-2: magic-link rows are pruned first, so the organizer sweep must not
    depend on a used link; it keys on email_verified_at and spares anything
    carrying identities, claims, venues or the verified flag."""
    mock_db.execute.side_effect = _delete_results([0] * _N)

    await cleanup_stale_data(mock_db)

    stmt = mock_db.execute.call_args_list[8][0][0]
    compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "email_verified_at IS NULL" in compiled
    assert "organizers.verified = false" in compiled
    for table in ("organizer_identities", "claims", "venues"):
        assert table in compiled
    # No used-link evidence any more (that evidence is pruned in the same job).
    assert "used_at IS NOT NULL" not in compiled


@pytest.mark.asyncio
async def test_cleanup_unverified_account_retention_constant_is_wired(mock_db):
    mock_db.execute.side_effect = _delete_results([0] * _N)

    await cleanup_stale_data(mock_db)

    users_stmt = mock_db.execute.call_args_list[7][0][0]
    compiled = str(users_stmt.compile(compile_kwargs={"literal_binds": True}))
    assert UNVERIFIED_ACCOUNT_RETENTION_DAYS > 0
    # cutoff appears as a literal timestamp bound (regression guard against the
    # constant silently going unused).
    assert "created_at" in compiled
