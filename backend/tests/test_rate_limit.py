"""Integration test: per-IP rate limiting on /auth/request-link via slowapi.

Builds a minimal app wiring up the same limiter/middleware/exception-handler
trio as app.main, then fires requests past the configured burst and asserts
the limiter cuts in with 429 (plan verification: "rate-limiter returns 429
after the configured burst on /auth/request-link").
"""
import http
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.requests import Request

from app.constants import RATE_LIMIT_AUTH_REQUEST_LINK
from app.rate_limit import client_key, limiter, rate_limit_exceeded_handler


def _request(headers: list[tuple[bytes, bytes]], client: tuple[str, int] | None = ("203.0.113.9", 12345)) -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "query_string": b"", "headers": headers, "client": client})


# ---------------------------------------------------------------------------
# H1: client_key must derive from the rightmost X-Forwarded-For entry, not
# request.client (which ProxyHeadersMiddleware rewrites from the leftmost,
# attacker-controlled, XFF hop) and not the naive leftmost XFF entry.
# ---------------------------------------------------------------------------


def test_client_key_uses_rightmost_xff_entry_when_present():
    req = _request([(b"x-forwarded-for", b"1.2.3.4, 9.9.9.9, 5.5.5.5")])
    assert client_key(req) == "5.5.5.5"


def test_client_key_strips_whitespace_around_rightmost_entry():
    req = _request([(b"x-forwarded-for", b"1.2.3.4,  9.9.9.9 ")])
    assert client_key(req) == "9.9.9.9"


def test_client_key_single_xff_entry():
    req = _request([(b"x-forwarded-for", b"9.9.9.9")])
    assert client_key(req) == "9.9.9.9"


def test_client_key_falls_back_to_remote_address_without_xff():
    req = _request([], client=("203.0.113.9", 12345))
    assert client_key(req) == "203.0.113.9"


def test_client_key_attacker_prepended_leftmost_entry_does_not_win():
    """An attacker prepending their own X-Forwarded-For value must not be
    able to control the rate-limit/audit-log key — only the rightmost entry
    (appended by the trusted proxy hop) is trusted."""
    attacker_supplied = "9.9.9.9"
    real_client_as_seen_by_proxy = "203.0.113.9"
    req = _request(
        [(b"x-forwarded-for", f"{attacker_supplied}, {real_client_as_seen_by_proxy}".encode())]
    )
    assert client_key(req) != attacker_supplied
    assert client_key(req) == real_client_as_seen_by_proxy


def _build_app() -> FastAPI:
    """Minimal app wiring the auth router behind the same limiter setup as app.main."""
    from app.routers.auth import router

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.include_router(router)
    return app


@pytest.mark.asyncio
async def test_request_link_returns_429_after_burst(mock_db):
    """The configured burst (RATE_LIMIT_AUTH_REQUEST_LINK = "10/minute") must be
    enforced per-IP — the 11th request within the window gets 429, not a DB hit."""
    burst = int(RATE_LIMIT_AUTH_REQUEST_LINK.split("/")[0])
    limiter.reset()

    app = _build_app()

    async def override_db():
        yield mock_db

    from app.db import get_db
    app.dependency_overrides[get_db] = override_db

    mock_db.scalar = AsyncMock(side_effect=lambda *a, **kw: None)

    statuses: list[int] = []
    try:
        with patch("app.routers.auth.send_magic_link", new_callable=AsyncMock):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                for _ in range(burst + 1):
                    resp = await client.post(
                        "/auth/request-link",
                        json={"email": "burst@example.com"},
                    )
                    statuses.append(resp.status_code)
    finally:
        limiter.reset()

    assert statuses[:burst] == [http.HTTPStatus.OK] * burst
    assert statuses[burst] == http.HTTPStatus.TOO_MANY_REQUESTS


def _build_organizer_auth_app() -> FastAPI:
    from app.routers.organizer_auth import router

    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.include_router(router)
    return app


@pytest.mark.asyncio
async def test_google_signin_start_returns_429_after_burst(monkeypatch):
    """RATE_LIMIT_GOOGLE_SIGNIN_START ("20/minute") enforced per-IP."""
    from app.config import settings
    from app.constants import RATE_LIMIT_GOOGLE_SIGNIN_START

    monkeypatch.setattr(settings, "GOOGLE_SIGNIN_ORGANIZER_ENABLED", True)
    monkeypatch.setattr(settings, "GOOGLE_OAUTH_CLIENT_ID", "cid")

    burst = int(RATE_LIMIT_GOOGLE_SIGNIN_START.split("/")[0])
    limiter.reset()

    app = _build_organizer_auth_app()

    statuses: list[int] = []
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
        ) as client:
            for _ in range(burst + 1):
                resp = await client.get("/organizer/auth/google/start")
                statuses.append(resp.status_code)
    finally:
        limiter.reset()

    assert statuses[:burst] == [http.HTTPStatus.FOUND] * burst
    assert statuses[burst] == http.HTTPStatus.TOO_MANY_REQUESTS


@pytest.mark.asyncio
async def test_google_signin_callback_returns_429_after_burst(monkeypatch, mock_db):
    """RATE_LIMIT_GOOGLE_SIGNIN_CALLBACK ("30/minute") enforced per-IP — even
    a malformed callback (no code/state) still counts against the bucket."""
    from app.config import settings
    from app.constants import RATE_LIMIT_GOOGLE_SIGNIN_CALLBACK
    from app.db import get_db

    monkeypatch.setattr(settings, "GOOGLE_SIGNIN_ORGANIZER_ENABLED", True)

    burst = int(RATE_LIMIT_GOOGLE_SIGNIN_CALLBACK.split("/")[0])
    limiter.reset()

    app = _build_organizer_auth_app()

    async def override_db():
        yield mock_db

    app.dependency_overrides[get_db] = override_db

    statuses: list[int] = []
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", follow_redirects=False
        ) as client:
            for _ in range(burst + 1):
                resp = await client.get("/organizer/auth/google/callback")
                statuses.append(resp.status_code)
    finally:
        limiter.reset()

    assert statuses[:burst] == [http.HTTPStatus.FOUND] * burst
    assert statuses[burst] == http.HTTPStatus.TOO_MANY_REQUESTS
