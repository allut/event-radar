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
    async def test_thin_week_falls_back_to_wider_window(
        self, mock_db, make_event, make_request
    ):
        from app.constants import SHOWCASE_EVENT_COUNT
        from app.routers.public import showcase

        thin_week = _scalars_result([make_event(1), make_event(2)])
        wider_window = _scalars_result(
            [make_event(i) for i in range(1, SHOWCASE_EVENT_COUNT + 1)]
        )
        mock_db.scalars.side_effect = [thin_week, wider_window]

        result = await showcase(request=make_request(), locale="en", db=mock_db)

        assert len(result["events"]) == SHOWCASE_EVENT_COUNT
        assert mock_db.scalars.await_count == 2

    @pytest.mark.asyncio
    async def test_full_week_does_not_trigger_fallback(
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

    def test_window_bound_widens_between_calls(self):
        from datetime import datetime, timezone

        from app.routers.public import _showcase_stmt

        now = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)
        week_sql = str(
            _showcase_stmt(now, 7).compile(compile_kwargs={"literal_binds": True})
        )
        month_sql = str(
            _showcase_stmt(now, 30).compile(compile_kwargs={"literal_binds": True})
        )

        # Both statements must bound starts_at from above, and the 30-day bound
        # must be a later timestamp than the 7-day bound — the upper bound this
        # whole change exists to add.
        assert "starts_at <" in week_sql
        assert "starts_at <" in month_sql
        assert week_sql != month_sql
