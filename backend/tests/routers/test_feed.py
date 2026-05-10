"""Tests for GET /feed and GET /events/{id} endpoints."""
import http
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from app.constants import DEFAULT_CURRENCY, DEFAULT_USER_LOCALE, DEFAULT_USER_CITY, TALLINN_CENTER_LAT, TALLINN_CENTER_LNG

import pytest


def _mock_db():
    db = AsyncMock()
    db.get = AsyncMock()
    db.scalar = AsyncMock()
    db.scalars = AsyncMock()
    db.execute = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


def _make_user(user_id: int = 1):
    u = MagicMock()
    u.id = user_id
    u.email = "test@example.com"
    u.locale = DEFAULT_USER_LOCALE
    u.home_city = DEFAULT_USER_CITY
    u.created_at = datetime.now(timezone.utc)
    return u


def _make_event(event_id: int = 10):
    e = MagicMock()
    e.id = event_id
    e.slug = f"test-event-{event_id}"
    e.title_orig = "Test Event"
    e.description_orig = "A test event"
    e.starts_at = datetime(2026, 5, 15, 18, 0, 0, tzinfo=timezone.utc)
    e.ends_at = None
    e.venue_name = "Test Venue"
    e.venue_address = "Test Street 1"
    e.lat = TALLINN_CENTER_LAT
    e.lng = TALLINN_CENTER_LNG
    e.url = "https://example.com"
    e.image_url = None
    e.price_min = None
    e.price_max = None
    e.currency = DEFAULT_CURRENCY
    e.status = "published"
    e.dedup_group_id = None

    cl = MagicMock()
    cl.categories = ["music"]
    cl.vibes = ["underground"]
    cl.quality_score = 0.8
    cl.why_go_bullets = ["Great DJs", "Intimate venue", "All night long"]
    cl.language_detected = DEFAULT_USER_LOCALE
    e.classification = cl
    return e


# ---------------------------------------------------------------------------
# GET /feed
# ---------------------------------------------------------------------------


class TestGetFeed:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_feed_built(self):
        from app.routers.feed import get_feed

        db = _mock_db()
        db.scalar.return_value = None  # no DailyFeed row
        user = _make_user()

        result = await get_feed(current_user=user, db=db)

        assert result["events"] == []
        assert result["built_at"] is None
        assert "feed_date" in result

    @pytest.mark.asyncio
    async def test_returns_events_in_feed_order(self):
        from app.routers.feed import get_feed

        db = _mock_db()
        feed = MagicMock()
        feed.event_ids = [10, 20]
        feed.built_at = datetime(2026, 5, 10, 6, 0, 0, tzinfo=timezone.utc)
        db.scalar.return_value = feed

        event10 = _make_event(10)
        event20 = _make_event(20)
        scalars_result = MagicMock()
        scalars_result.all.return_value = [event10, event20]
        db.scalars.return_value = scalars_result

        user = _make_user()
        result = await get_feed(current_user=user, db=db)

        assert len(result["events"]) == 2
        assert result["events"][0]["id"] == 10
        assert result["events"][1]["id"] == 20
        assert result["built_at"] is not None

    @pytest.mark.asyncio
    async def test_empty_event_ids_returns_empty(self):
        from app.routers.feed import get_feed

        db = _mock_db()
        feed = MagicMock()
        feed.event_ids = []
        db.scalar.return_value = feed

        user = _make_user()
        result = await get_feed(current_user=user, db=db)

        assert result["events"] == []

    @pytest.mark.asyncio
    async def test_event_without_classification(self):
        from app.routers.feed import get_feed

        db = _mock_db()
        feed = MagicMock()
        feed.event_ids = [10]
        feed.built_at = datetime(2026, 5, 10, 6, 0, 0, tzinfo=timezone.utc)
        db.scalar.return_value = feed

        event = _make_event(10)
        event.classification = None
        scalars_result = MagicMock()
        scalars_result.all.return_value = [event]
        db.scalars.return_value = scalars_result

        user = _make_user()
        result = await get_feed(current_user=user, db=db)

        assert result["events"][0]["categories"] == []
        assert result["events"][0]["why_go"] == []


# ---------------------------------------------------------------------------
# GET /events/{event_id}
# ---------------------------------------------------------------------------


class TestGetEvent:
    @pytest.mark.asyncio
    async def test_returns_event_detail(self):
        from app.routers.events import get_event

        db = _mock_db()
        scalars_result = MagicMock()
        scalars_result.one_or_none = MagicMock()
        event = _make_event(42)
        db.scalar.return_value = event

        result = await get_event(event_id=42, db=db)

        assert result["id"] == 42
        assert result["title"] == "Test Event"
        assert result["categories"] == ["music"]
        assert result["why_go"] == ["Great DJs", "Intimate venue", "All night long"]

    @pytest.mark.asyncio
    async def test_returns_404_when_not_found(self):
        from fastapi import HTTPException
        from app.routers.events import get_event

        db = _mock_db()
        db.scalar.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await get_event(event_id=999, db=db)
        assert exc_info.value.status_code == http.HTTPStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_event_no_classification(self):
        from app.routers.events import get_event

        db = _mock_db()
        event = _make_event(1)
        event.classification = None
        db.scalar.return_value = event

        result = await get_event(event_id=1, db=db)

        assert result["categories"] == []
        assert result["quality_score"] is None
