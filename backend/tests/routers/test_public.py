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
