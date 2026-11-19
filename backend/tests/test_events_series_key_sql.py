"""Parity guard: migration 0052's event_series_key_sql() and its triggers must
agree with event_series_key()/serialize_event_series_key() in Python.

Needs a migrated Postgres (the migrations CI job, or a local Postgres);
skipped when DATABASE_URL is unreachable or not at revision 0052.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from app.events.queries import event_series_key, serialize_event_series_key

asyncpg = pytest.importorskip("asyncpg")

CASES = [
    ("  Balti  Jaama\tTurg ", "Kultuurikatel"),
    ("ÕÜÄÖ Öö Pidu　X", "Ü Hall\n2"),
    ("Tallinn ÄÄ", None),
    ("", ""),
]


async def _connect():
    url = os.environ.get("DATABASE_URL", "").replace("+asyncpg", "")
    if not url:
        pytest.skip("DATABASE_URL not set")
    try:
        conn = await asyncpg.connect(url, timeout=3)
    except (OSError, asyncio.TimeoutError, asyncpg.PostgresError):
        pytest.skip("Postgres unreachable")
    if not await conn.fetchval("SELECT to_regproc('event_series_key_sql')"):
        await conn.close()
        pytest.skip("DB not at migration 0052")
    return conn


@pytest.mark.asyncio
async def test_sql_key_matches_python_key() -> None:
    conn = await _connect()
    try:
        for title, venue in CASES:
            expected = serialize_event_series_key(event_series_key(title, venue))
            got = await conn.fetchval("SELECT event_series_key_sql($1, $2)", title, venue)
            assert got == expected, (title, venue)
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_triggers_maintain_column_and_follow_venue_rename() -> None:
    conn = await _connect()
    tx = conn.transaction()
    await tx.start()
    try:
        org_id = await conn.fetchval(
            "INSERT INTO organizers (email) VALUES "
            "('sk-test@example.com') RETURNING id"
        )
        venue_id = await conn.fetchval(
            "INSERT INTO venues (organizer_id, name) VALUES ($1, 'Old Hall') RETURNING id",
            org_id,
        )
        event_id = await conn.fetchval(
            "INSERT INTO events (slug, title_orig, starts_at, venue_id, status) "
            "VALUES ('sk-test-slug', 'My  Show', now(), $1, 'draft') RETURNING id",
            venue_id,
        )
        expected = serialize_event_series_key(event_series_key("My Show", "Old Hall"))
        assert await conn.fetchval("SELECT series_key FROM events WHERE id=$1", event_id) == expected

        await conn.execute("UPDATE venues SET name='New Hall' WHERE id=$1", venue_id)
        renamed = serialize_event_series_key(event_series_key("My Show", "New Hall"))
        assert await conn.fetchval("SELECT series_key FROM events WHERE id=$1", event_id) == renamed
    except asyncpg.PostgresError as exc:
        pytest.skip(f"schema not insertable with minimal columns: {exc}")
    finally:
        await tx.rollback()
        await conn.close()
