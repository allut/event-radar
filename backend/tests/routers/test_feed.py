"""Tests for GET /feed and GET /events/{id} endpoints."""
import http
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# GET /feed
# ---------------------------------------------------------------------------


class TestGetFeed:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_feed_built(self, mock_db, make_user):
        from app.routers.feed import get_feed

        mock_db.scalar.return_value = None  # no DailyFeed row
        user = make_user()

        result = await get_feed(current_user=user, db=mock_db)

        assert result["events"] == []
        assert result["built_at"] is None
        assert "feed_date" in result

    @pytest.mark.asyncio
    async def test_returns_events_in_feed_order(self, mock_db, make_user, make_event):
        from app.routers.feed import get_feed

        feed = MagicMock()
        feed.event_ids = [10, 20]
        feed.built_at = datetime(2026, 5, 10, 6, 0, 0, tzinfo=timezone.utc)
        mock_db.scalar.return_value = feed

        event10 = make_event(10)
        event20 = make_event(20)
        scalars_result = MagicMock()
        scalars_result.all.return_value = [event10, event20]
        mock_db.scalars.return_value = scalars_result

        user = make_user()
        result = await get_feed(current_user=user, db=mock_db)

        assert len(result["events"]) == 2
        assert result["events"][0]["id"] == 10
        assert result["events"][1]["id"] == 20
        assert result["built_at"] is not None

    @pytest.mark.asyncio
    async def test_empty_event_ids_returns_empty(self, mock_db, make_user):
        from app.routers.feed import get_feed

        feed = MagicMock()
        feed.event_ids = []
        mock_db.scalar.return_value = feed

        user = make_user()
        result = await get_feed(current_user=user, db=mock_db)

        assert result["events"] == []

    @pytest.mark.asyncio
    async def test_event_without_classification(self, mock_db, make_user, make_event):
        from app.routers.feed import get_feed

        feed = MagicMock()
        feed.event_ids = [10]
        feed.built_at = datetime(2026, 5, 10, 6, 0, 0, tzinfo=timezone.utc)
        mock_db.scalar.return_value = feed

        event = make_event(10)
        event.classification = None
        scalars_result = MagicMock()
        scalars_result.all.return_value = [event]
        mock_db.scalars.return_value = scalars_result

        user = make_user()
        result = await get_feed(current_user=user, db=mock_db)

        assert result["events"][0]["categories"] == []
        assert result["events"][0]["why_go"] == []


# ---------------------------------------------------------------------------
# GET /events/{event_id}
# ---------------------------------------------------------------------------


class TestGetEvent:
    @pytest.mark.asyncio
    async def test_returns_event_detail(self, mock_db, make_event, make_request):
        from app.routers.events import get_event

        event = make_event(42)
        mock_db.scalar.return_value = event

        result = await get_event(event_id=42, request=make_request(), db=mock_db)

        assert result["id"] == 42
        assert result["title"] == "Test Event"
        assert result["categories"] == ["music"]
        assert result["why_go"] == ["Great DJs", "Intimate venue", "All night long"]

    @pytest.mark.asyncio
    async def test_returns_404_when_not_found(self, mock_db, make_request):
        from fastapi import HTTPException
        from app.routers.events import get_event

        mock_db.scalar.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await get_event(event_id=999, request=make_request(), db=mock_db)
        assert exc_info.value.status_code == http.HTTPStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_event_no_classification(self, mock_db, make_event, make_request):
        from app.routers.events import get_event

        event = make_event(1)
        event.classification = None
        mock_db.scalar.return_value = event

        result = await get_event(event_id=1, request=make_request(), db=mock_db)

        assert result["categories"] == []
        assert result["quality_score"] is None
