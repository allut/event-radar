"""Migration 0070's indexes stay usable by the queries they were built for.

With sequential scans priced out, the planner picks an index whenever one
matches, so a plan naming the index proves the predicate and order line up
(a partial index whose WHERE the query doesn't imply never appears)."""

import pytest
from sqlalchemy import text


async def _plan(db, sql: str) -> str:
    await db.execute(text("SET LOCAL enable_seqscan = off"))
    rows = (await db.execute(text(f"EXPLAIN {sql}"))).scalars().all()
    return "\n".join(rows)


@pytest.mark.asyncio
async def test_publish_gate_reads_live_classified_rows_by_index(db) -> None:
    plan = await _plan(
        db,
        "UPDATE events SET status = 'published' "
        "WHERE status = 'classified' AND coalesce(ends_at, starts_at) >= now()",
    )
    assert "ix_events_classified_live_until" in plan


@pytest.mark.asyncio
async def test_fienta_stamp_reads_unstamped_sources_by_index(db) -> None:
    plan = await _plan(
        db, "SELECT event_id FROM event_sources WHERE publisher_id IS NULL AND source_id = 1"
    )
    assert "ix_event_sources_unstamped" in plan


@pytest.mark.asyncio
async def test_quality_sort_walks_the_index_without_a_sort(db) -> None:
    plan = await _plan(
        db,
        "SELECT event_id FROM event_classifications "
        "ORDER BY quality_score DESC NULLS LAST LIMIT 10",
    )
    assert "ix_event_classifications_quality_score" in plan
    assert "Sort" not in plan
