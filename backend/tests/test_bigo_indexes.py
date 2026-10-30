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
    # On an empty, analyzed events table this index and ix_events_status cost
    # the same, so the planner's pick flips with whatever stats earlier tests
    # or autovacuum left behind. Seed the production shape (ended rejects
    # piling up in 'classified') and analyze, so the partial index wins on cost.
    await db.execute(
        text(
            "INSERT INTO events (slug, title_orig, starts_at, status) "
            "SELECT 'bigo-' || g, 'e', now() - interval '30 days' + (g % 20) * interval '1 day', "
            "CASE WHEN g % 20 = 0 THEN 'published' ELSE 'classified' END "
            "FROM generate_series(1, 2000) g"
        )
    )
    await db.execute(text("ANALYZE events"))
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
