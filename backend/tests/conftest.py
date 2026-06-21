import os

# Must be set before any app module import so pydantic-settings can validate Settings.
os.environ.setdefault("SECRET_KEY", "test-secret-not-for-production")

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.requests import Request

from app.constants import (
    DEFAULT_CURRENCY,
    DEFAULT_USER_CITY,
    DEFAULT_USER_LOCALE,
    TALLINN_CENTER_LAT,
    TALLINN_CENTER_LNG,
)


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.get = AsyncMock()
    db.scalar = AsyncMock()
    db.scalars = AsyncMock()
    db.execute = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()
    return db


@pytest.fixture
def make_user():
    def _factory(
        user_id: int = 1,
        locale: str = DEFAULT_USER_LOCALE,
        opt_in: bool = True,
    ) -> MagicMock:
        u = MagicMock()
        u.id = user_id
        u.email = "test@example.com"
        u.locale = locale
        u.home_city = DEFAULT_USER_CITY
        u.email_digest_opt_in = opt_in
        u.created_at = MagicMock()
        u.created_at.isoformat.return_value = "2026-05-13T06:00:00+00:00"
        return u
    return _factory


@pytest.fixture
def make_event():
    def _factory(event_id: int = 10) -> MagicMock:
        e = MagicMock()
        e.id = event_id
        e.slug = f"test-event-{event_id}"
        e.title_orig = "Test Event"
        e.description_orig = "A test event"
        e.important_info = None
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
        e.price_hint = None
        e.status = "published"
        e.is_explicit = False
        e.is_out_of_area = False
        e.dedup_group_id = None

        cl = MagicMock()
        cl.categories = ["music"]
        cl.vibes = ["underground"]
        cl.quality_score = 0.8
        cl.why_go_bullets = ["Great DJs", "Intimate venue", "All night long"]
        cl.why_go_localized = None
        cl.language_detected = DEFAULT_USER_LOCALE
        e.classification = cl
        return e
    return _factory


@pytest.fixture
def make_request():
    """Factory for a real starlette Request — slowapi's @limiter.limit requires an
    actual Request instance (isinstance check), not a MagicMock. Shared across
    router tests that call a rate-limited endpoint function directly."""
    def _factory(
        accept_language: str = "",
        method: str = "GET",
        path: str = "/",
    ) -> Request:
        headers = (
            [(b"accept-language", accept_language.encode())] if accept_language else []
        )
        return Request(
            {
                "type": "http",
                "method": method,
                "path": path,
                "query_string": b"",
                "headers": headers,
                "client": ("127.0.0.1", 9999),
            }
        )
    return _factory
