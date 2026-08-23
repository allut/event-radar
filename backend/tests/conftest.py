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
    # Default no-op result for load_user_signals()'s `(await db.execute(...)).all()` —
    # an explicit MagicMock (not the auto-AsyncMock child unittest.mock would give an
    # AsyncMock's attributes) so `.all()` returns a plain list, not an unawaited
    # coroutine. Tests that care about hydrated my_signal override this return value.
    _execute_result = MagicMock()
    _execute_result.all.return_value = []
    db.execute.return_value = _execute_result
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
        email_verified: bool = True,
    ) -> MagicMock:
        u = MagicMock()
        u.id = user_id
        u.email = "test@example.com"
        u.locale = locale
        u.home_city = DEFAULT_USER_CITY
        u.email_digest_opt_in = opt_in
        u.email_verified = email_verified
        u.created_at = MagicMock()
        u.created_at.isoformat.return_value = "2026-05-13T06:00:00+00:00"
        return u
    return _factory


@pytest.fixture
def make_organizer():
    def _factory(
        organizer_id: int = 1,
        locale: str = DEFAULT_USER_LOCALE,
        session_token_version: int = 1,
    ) -> MagicMock:
        o = MagicMock()
        o.id = organizer_id
        o.email = "organizer@example.com"
        o.locale = locale
        o.session_token_version = session_token_version
        o.created_at = MagicMock()
        o.created_at.isoformat.return_value = "2026-05-13T06:00:00+00:00"
        return o
    return _factory


@pytest.fixture
def make_event():
    def _factory(
        event_id: int = 10,
        title: str = "Test Event",
        starts_at: datetime | None = None,
        venue_name: str | None = "Test Venue",
        venue_address: str | None = "Test Street 1",
        lat: float | None = TALLINN_CENTER_LAT,
        lng: float | None = TALLINN_CENTER_LNG,
        price_min: float | None = None,
        status: str = "published",
        description_orig: str = "A test event",
        why_go: list[str] | None = None,
        why_go_localized: dict | None = None,
        image_url: str | None = None,
    ) -> MagicMock:
        if starts_at is None:
            starts_at = datetime(2026, 5, 15, 18, 0, 0, tzinfo=timezone.utc)
        e = MagicMock()
        e.id = event_id
        e.slug = f"test-event-{event_id}"
        e.title_orig = title
        e.description_orig = description_orig
        e.title_localized = None
        e.description_localized = None
        e.important_info = None
        e.starts_at = starts_at
        e.ends_at = None
        e.venue_name = venue_name
        e.venue_address = venue_address
        e.lat = lat
        e.lng = lng
        e.url = "https://example.com"
        e.image_url = image_url
        e.price_min = price_min
        e.price_max = None
        e.currency = DEFAULT_CURRENCY
        e.price_hint = None
        e.status = status
        e.is_explicit = False
        e.is_non_event = False
        e.is_out_of_area = False
        e.has_free_tier = False
        e.dedup_group_id = None

        if why_go is not None or why_go_localized is not None:
            cl = MagicMock()
            cl.categories = ["music"]
            cl.vibes = ["underground"]
            cl.quality_score = 0.8
            cl.why_go_bullets = why_go or []
            cl.why_go_localized = why_go_localized
            cl.language_detected = DEFAULT_USER_LOCALE
            e.classification = cl
        else:
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
def make_report():
    def _factory(
        report_id: int = 1,
        user_id: int = 1,
        event_id: int = 10,
        reason: str = "spam_or_scam",
        is_illegal_allegation: bool = False,
        detail: str | None = None,
        status: str = "open",
    ) -> MagicMock:
        r = MagicMock()
        r.id = report_id
        r.user_id = user_id
        r.event_id = event_id
        r.reason = reason
        r.is_illegal_allegation = is_illegal_allegation
        r.detail = detail
        r.status = status
        r.resolution_note = None
        r.created_at = datetime(2026, 5, 13, 6, 0, 0, tzinfo=timezone.utc)
        r.resolved_at = None
        return r
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


def assert_hardened_cookie(
    set_cookie: str, *, name: str, path: str, cleared: bool = False
) -> None:
    """Assert a Set-Cookie header carries the full hardened attribute set
    (HttpOnly, Secure, SameSite=strict, Path) — shared by every auth-router
    test asserting a session/organizer_session cookie (set or cleared)."""
    assert f"{name}=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=strict" in set_cookie
    assert f"Path={path}" in set_cookie
    if cleared:
        assert "Max-Age=0" in set_cookie
