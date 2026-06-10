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

from app.constants import RATE_LIMIT_AUTH_REQUEST_LINK
from app.rate_limit import limiter, rate_limit_exceeded_handler


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
