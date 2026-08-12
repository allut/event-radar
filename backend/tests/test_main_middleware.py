"""Tests for M5 (MaxBodySizeMiddleware), the M1 dev-database-host sanity
check (_check_dev_database_host), and HostCheckMiddleware, all in
app/main.py."""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.constants import APP_ENV_DEVELOPMENT, HOST_CHECK_EXEMPT_PATHS
from app.main import HostCheckMiddleware, MaxBodySizeMiddleware, _check_dev_database_host


async def _echo(request):
    body = await request.body()
    return PlainTextResponse(f"len={len(body)}")


def _build_app(max_bytes: int) -> Starlette:
    app = Starlette(routes=[Route("/echo", _echo, methods=["POST"])])
    app.add_middleware(MaxBodySizeMiddleware, max_bytes=max_bytes)
    return app


@pytest.mark.asyncio
async def test_body_within_limit_passes_through():
    app = _build_app(max_bytes=100)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/echo", content=b"x" * 50)
    assert resp.status_code == 200
    assert resp.text == "len=50"


@pytest.mark.asyncio
async def test_content_length_over_limit_rejected_413_before_handler_runs():
    app = _build_app(max_bytes=10)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/echo", content=b"x" * 50)
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_chunked_request_over_limit_rejected_mid_stream():
    """No Content-Length header (streamed body) — must still be bounded, via
    the wrapped receive() callable rather than the upfront header check."""

    async def _gen():
        for _ in range(5):
            yield b"x" * 30  # 150 bytes total, over the 100-byte cap

    app = _build_app(max_bytes=100)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/echo", content=_gen())
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_413_response_is_well_formed_not_a_crash():
    """Regression guard: raising HTTPException from user-added middleware
    would surface as a bare 500 (Starlette's ExceptionMiddleware sits inside
    every add_middleware entry) — the fix sends the response itself."""
    app = _build_app(max_bytes=10)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/echo", content=b"x" * 50)
    assert resp.status_code == 413
    assert resp.json()["detail"]


@pytest.mark.asyncio
async def test_non_http_scope_bypasses_middleware():
    """A lifespan/websocket scope must pass straight through untouched."""
    received = {}

    async def inner_app(scope, receive, send):
        received["type"] = scope["type"]
        if scope["type"] == "lifespan":
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})

    middleware = MaxBodySizeMiddleware(inner_app, max_bytes=10)

    events = iter([{"type": "lifespan.startup"}])

    async def receive():
        return next(events)

    sent = []

    async def send(message):
        sent.append(message)

    await middleware({"type": "lifespan"}, receive, send)
    assert received["type"] == "lifespan"
    assert sent == [{"type": "lifespan.startup.complete"}]


# ---------------------------------------------------------------------------
# _check_dev_database_host (M1)
# ---------------------------------------------------------------------------


def test_dev_database_host_check_skips_outside_development():
    with patch("app.main.settings") as mock_settings:
        mock_settings.APP_ENV = "production"
        mock_settings.DATABASE_URL = "postgresql+asyncpg://user:pass@real-host.example.com/db"
        with patch("app.main.log") as mock_log:
            _check_dev_database_host()
    mock_log.error.assert_not_called()


def test_dev_database_host_check_silent_for_localhost():
    with patch("app.main.settings") as mock_settings:
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT
        mock_settings.DATABASE_URL = "postgresql+asyncpg://eventradar:eventradar@localhost:5432/eventradar"
        with patch("app.main.log") as mock_log:
            _check_dev_database_host()
    mock_log.error.assert_not_called()


def test_dev_database_host_check_logs_error_for_non_local_host():
    with patch("app.main.settings") as mock_settings:
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT
        mock_settings.DATABASE_URL = (
            "postgresql+asyncpg://user:pass@ep-xxx.eu-central-1.aws.neon.tech/neondb?ssl=require"
        )
        with patch("app.main.log") as mock_log:
            _check_dev_database_host()
    mock_log.error.assert_called_once()


# ---------------------------------------------------------------------------
# HostCheckMiddleware
# ---------------------------------------------------------------------------


def _build_host_check_app() -> Starlette:
    app = Starlette(
        routes=[
            Route("/echo", _echo, methods=["POST", "GET"]),
            Route("/health", _echo, methods=["GET"]),
        ]
    )
    app.add_middleware(
        HostCheckMiddleware,
        allowed_hosts=["event-radar-api.onrender.com"],
        exempt_paths=HOST_CHECK_EXEMPT_PATHS,
    )
    return app


@pytest.mark.asyncio
async def test_exempt_path_with_foreign_host_passes_through():
    """Regression guard for the 0.1.6 deploy failure: Render's health probe
    hits /health with the instance's private-network Host, not BACKEND_URL's
    hostname — it must not be rejected."""
    app = _build_host_check_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            "/health", headers={"Host": "10.238.24.247"}
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_guarded_path_with_foreign_host_rejected():
    app = _build_host_check_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/echo", content=b"x", headers={"Host": "10.238.24.247"}
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_guarded_path_with_allowed_host_passes_through():
    app = _build_host_check_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/echo",
            content=b"x",
            headers={"Host": "event-radar-api.onrender.com"},
        )
    assert resp.status_code == 200
