"""Tests for M5 (MaxBodySizeMiddleware), the M1 dev-database-host sanity
check (_check_dev_database_host), and HostCheckMiddleware, all in
app/main.py."""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.constants import (
    APP_ENV_DEVELOPMENT,
    HOST_CHECK_EXEMPT_PATHS,
    LOG_EVENT_HOST_REJECTED,
)
from app.main import (
    HostCheckMiddleware,
    MaxBodySizeMiddleware,
    _check_dev_database_host,
    _resolve_allowed_hosts,
)


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


async def _bad_request(request):
    """Simulates an ordinary endpoint 400 (bad token, malformed input, ...)
    unrelated to the Host header — must never be mistaken for a Host reject."""
    return PlainTextResponse("bad token", status_code=400)


def _build_host_check_app() -> Starlette:
    app = Starlette(
        routes=[
            Route("/echo", _echo, methods=["POST", "GET"]),
            Route("/health", _echo, methods=["GET"]),
            Route("/bad-request", _bad_request, methods=["GET"]),
        ]
    )
    app.add_middleware(
        HostCheckMiddleware,
        allowed_hosts=["event-radar-api-r7l6.onrender.com"],
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
            headers={"Host": "event-radar-api-r7l6.onrender.com"},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_rejected_request_logs_host_rejected_event(caplog):
    """A 400 from the guarded TrustedHostMiddleware must surface as a
    LOG_EVENT_HOST_REJECTED warning naming the offending Host — otherwise a
    misconfigured allowlist is invisible in the logs (the 0.1.6 outage had no
    signal beyond a bare access-log 400)."""
    app = _build_host_check_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        with caplog.at_level("WARNING", logger="app.main"):
            resp = await client.post(
                "/echo", content=b"x", headers={"Host": "10.238.24.247"}
            )
    assert resp.status_code == 400
    matching = [
        r for r in caplog.records if getattr(r, "event", None) == LOG_EVENT_HOST_REJECTED
    ]
    assert len(matching) == 1
    assert "10.238.24.247" in matching[0].getMessage()


@pytest.mark.asyncio
async def test_downstream_400_with_allowed_host_not_logged_as_host_rejected(caplog):
    """Regression guard: an ordinary endpoint 400 (bad token, malformed
    input, ...) with a valid Host must never emit LOG_EVENT_HOST_REJECTED —
    the wrapper distinguishes TrustedHostMiddleware's own reject body from a
    downstream handler's unrelated 400, not just the status code."""
    app = _build_host_check_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        with caplog.at_level("WARNING", logger="app.main"):
            resp = await client.get(
                "/bad-request",
                headers={"Host": "event-radar-api-r7l6.onrender.com"},
            )
    assert resp.status_code == 400
    matching = [
        r for r in caplog.records if getattr(r, "event", None) == LOG_EVENT_HOST_REJECTED
    ]
    assert matching == []


# ---------------------------------------------------------------------------
# _resolve_allowed_hosts
# ---------------------------------------------------------------------------


def test_resolve_allowed_hosts_local_default_yields_empty_allowlist():
    """Regression guard for the 0.1.6 outage: an unset BACKEND_URL (falls
    back to its local-default config value) with no RENDER_EXTERNAL_HOSTNAME
    must yield *no* allowlist, not one that rejects every request."""
    with patch("app.main.settings") as mock_settings:
        mock_settings.RENDER_EXTERNAL_HOSTNAME = ""
        mock_settings.BACKEND_URL = "http://localhost:8000"
        with patch("app.main.log") as mock_log:
            result = _resolve_allowed_hosts()
    assert result == []
    mock_log.error.assert_called_once()


def test_resolve_allowed_hosts_render_hostname_alone():
    """RENDER_EXTERNAL_HOSTNAME must resolve the allowlist even when
    BACKEND_URL is still a local/dev default."""
    with patch("app.main.settings") as mock_settings:
        mock_settings.RENDER_EXTERNAL_HOSTNAME = "event-radar-api-r7l6.onrender.com"
        mock_settings.BACKEND_URL = "http://localhost:8000"
        with patch("app.main.log") as mock_log:
            result = _resolve_allowed_hosts()
    assert result == ["event-radar-api-r7l6.onrender.com"]
    mock_log.error.assert_not_called()


def test_resolve_allowed_hosts_both_set_and_different():
    with patch("app.main.settings") as mock_settings:
        mock_settings.RENDER_EXTERNAL_HOSTNAME = "srv-abc123.onrender.com"
        mock_settings.BACKEND_URL = "https://event-radar-api-r7l6.onrender.com"
        with patch("app.main.log") as mock_log:
            result = _resolve_allowed_hosts()
    assert result == ["srv-abc123.onrender.com", "event-radar-api-r7l6.onrender.com"]
    mock_log.error.assert_not_called()


def test_resolve_allowed_hosts_both_set_and_equal_dedupes():
    with patch("app.main.settings") as mock_settings:
        mock_settings.RENDER_EXTERNAL_HOSTNAME = "event-radar-api-r7l6.onrender.com"
        mock_settings.BACKEND_URL = "https://event-radar-api-r7l6.onrender.com"
        with patch("app.main.log") as mock_log:
            result = _resolve_allowed_hosts()
    assert result == ["event-radar-api-r7l6.onrender.com"]
    mock_log.error.assert_not_called()
