"""Tests for GET /public/showcase (app/routers/public.py)."""
from unittest.mock import MagicMock

import pytest


def _scalars_result(items):
    m = MagicMock()
    m.all.return_value = items
    return m


class TestShowcase:
    @pytest.mark.asyncio
    async def test_returns_serialized_events(self, mock_db, make_event, make_request):
        from app.routers.public import showcase

        mock_db.scalars.return_value = _scalars_result([make_event(1), make_event(2)])

        result = await showcase(request=make_request(), locale="en", db=mock_db)

        assert [e["id"] for e in result["events"]] == [1, 2]

    @pytest.mark.asyncio
    async def test_no_user_signals_hydrated(self, mock_db, make_event, make_request):
        from app.routers.public import showcase

        mock_db.scalars.return_value = _scalars_result([make_event(1)])

        result = await showcase(request=make_request(), locale="en", db=mock_db)

        # Anonymous endpoint — serialize_event called without feedback context.
        assert result["events"][0]["my_signal"] is None

    @pytest.mark.asyncio
    async def test_empty_returns_empty_list(self, mock_db, make_request):
        from app.routers.public import showcase

        mock_db.scalars.return_value = _scalars_result([])

        result = await showcase(request=make_request(), locale="en", db=mock_db)

        assert result["events"] == []

    @pytest.mark.asyncio
    async def test_invalid_locale_falls_back(self, mock_db, make_event, make_request):
        from app.routers.public import showcase

        mock_db.scalars.return_value = _scalars_result([make_event(1)])

        # A bogus locale must not raise — it degrades to the default locale.
        result = await showcase(request=make_request(), locale="zz", db=mock_db)

        assert [e["id"] for e in result["events"]] == [1]

    @pytest.mark.asyncio
    async def test_thin_pool_is_single_query(
        self, mock_db, make_event, make_request
    ):
        """A thin pool (fewer than SHOWCASE_EVENT_COUNT candidates even across the
        full fallback window) no longer triggers a second query — one query over
        the wider window, ordered/limited by the DB, replaces the old two-query
        narrow-then-fallback shape."""
        from app.routers.public import showcase

        mock_db.scalars.return_value = _scalars_result([make_event(1), make_event(2)])

        result = await showcase(request=make_request(), locale="en", db=mock_db)

        assert len(result["events"]) == 2
        assert mock_db.scalars.await_count == 1

    @pytest.mark.asyncio
    async def test_full_week_is_single_query(
        self, mock_db, make_event, make_request
    ):
        from app.constants import SHOWCASE_EVENT_COUNT
        from app.routers.public import showcase

        mock_db.scalars.return_value = _scalars_result(
            [make_event(i) for i in range(1, SHOWCASE_EVENT_COUNT + 1)]
        )

        result = await showcase(request=make_request(), locale="en", db=mock_db)

        assert len(result["events"]) == SHOWCASE_EVENT_COUNT
        assert mock_db.scalars.await_count == 1

    def test_query_prefers_narrow_window_but_bounds_wide(self):
        from datetime import datetime, timezone

        from app.routers.public import _showcase_stmt

        now = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)
        sql = str(_showcase_stmt(now).compile(compile_kwargs={"literal_binds": True}))

        # Bounded on both sides at the wide (fallback) window — a single query,
        # not two.
        assert "starts_at <" in sql
        assert "starts_at >=" in sql
        # A CASE expression orders "this week" candidates ahead of wider-window
        # ones, so narrowing only changes results when the narrow week can't
        # fill the grid on its own (see _showcase_stmt docstring).
        assert "CASE" in sql.upper()
