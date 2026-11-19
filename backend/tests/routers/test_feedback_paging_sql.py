"""Tie-breaker stability for Saved events (spec #551), against real Postgres.

Seeds signals that share one ``created_at`` and walks GET /feedback/events
page by page: nothing may repeat or go missing. Needs a migrated Postgres
(a local Postgres); skipped when DATABASE_URL is unset or unreachable.
Everything runs inside one transaction that is rolled back.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest

asyncpg = pytest.importorskip("asyncpg")

from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import DBAPIError, OperationalError  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

SEEDED = 5
PAGE = 2


@pytest.mark.asyncio
async def test_equal_created_at_walks_every_row_once(make_request) -> None:
    from app.routers.feedback import list_feedback_events

    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("DATABASE_URL not set to Postgres")
    engine = create_async_engine(url)
    try:
        try:
            conn = await asyncio.wait_for(engine.connect(), timeout=3)
        except (OSError, asyncio.TimeoutError, OperationalError, DBAPIError):
            pytest.skip("Postgres unreachable")
        tx = await conn.begin()
        try:
            session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
            try:
                user_id = (
                    await session.execute(
                        text(
                            "INSERT INTO users (email) VALUES ('paging-559@example.com') "
                            "RETURNING id"
                        )
                    )
                ).scalar_one()
                same_instant = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)
                feedback_ids: dict[int, int] = {}
                for i in range(SEEDED):
                    event_id = (
                        await session.execute(
                            text(
                                "INSERT INTO events (slug, title_orig, starts_at, status) "
                                "VALUES (:slug, :title, :starts, 'published') RETURNING id"
                            ),
                            {
                                "slug": f"paging-559-{i}",
                                "title": f"Paging {i}",
                                "starts": same_instant + timedelta(days=30 + i),
                            },
                        )
                    ).scalar_one()
                    feedback_ids[event_id] = (
                        await session.execute(
                            text(
                                "INSERT INTO user_event_feedback "
                                "(user_id, event_id, signal, created_at) "
                                "VALUES (:u, :e, 'bookmark', :at) RETURNING id"
                            ),
                            {"u": user_id, "e": event_id, "at": same_instant},
                        )
                    ).scalar_one()
            except DBAPIError as exc:
                pytest.skip(f"schema not insertable with minimal columns: {exc}")

            user = (
                await session.execute(
                    text("SELECT id, locale FROM users WHERE id = :u"), {"u": user_id}
                )
            ).one()

            walked: list[int] = []
            offset = 0
            while True:
                page = await list_feedback_events(
                    request=make_request(method="GET", path="/feedback/events"),
                    signal="bookmark",
                    limit=PAGE,
                    offset=offset,
                    locale=None,
                    current_user=user,
                    db=session,
                )
                assert page["total"] == SEEDED
                walked += [e["id"] for e in page["events"]]
                if not page["has_more"]:
                    break
                offset += PAGE

            # Every row exactly once, newest feedback id first on the tie.
            expected = sorted(feedback_ids, key=feedback_ids.__getitem__, reverse=True)
            assert walked == expected
            await session.close()
        finally:
            await tx.rollback()
            await conn.close()
    finally:
        await engine.dispose()
