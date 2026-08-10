"""Tests for CsrfOriginCheckMiddleware in app/main.py."""

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.main import CsrfOriginCheckMiddleware

TRUSTED_ORIGINS = frozenset({"https://trusted.example.com"})


async def _ok(request):
    return PlainTextResponse("ok")


def _build_app() -> Starlette:
    app = Starlette(
        routes=[
            Route("/thing", _ok, methods=["GET", "POST", "PATCH", "DELETE", "PUT"]),
        ]
    )
    app.add_middleware(CsrfOriginCheckMiddleware, trusted_origins=TRUSTED_ORIGINS)
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE", "PUT"])
async def test_mutating_request_with_trusted_origin_passes_through(method):
    app = _build_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.request(
            method, "/thing", headers={"Origin": "https://trusted.example.com"}
        )
    assert resp.status_code == 200
    assert resp.text == "ok"


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE", "PUT"])
async def test_mutating_request_with_mismatched_origin_rejected_403(method):
    app = _build_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.request(
            method, "/thing", headers={"Origin": "https://evil.example.com"}
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["POST", "PATCH", "DELETE", "PUT"])
async def test_mutating_request_with_no_origin_passes_through(method):
    """Covers server-to-server callers: the Resend inbound-mail webhook and
    the RFC 8058 one-click unsubscribe POST from mail clients, neither of
    which sends an Origin header."""
    app = _build_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.request(method, "/thing")
    assert resp.status_code == 200
    assert resp.text == "ok"


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "HEAD"])
async def test_non_mutating_methods_never_checked(method):
    """Even a mismatched Origin must not affect GET/HEAD."""
    app = _build_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.request(
            method, "/thing", headers={"Origin": "https://evil.example.com"}
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_options_never_gets_the_middlewares_403():
    """The route has no OPTIONS handler (405 from Starlette's router), but a
    mismatched Origin must never turn that into the middleware's 403."""
    app = _build_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.request(
            "OPTIONS", "/thing", headers={"Origin": "https://evil.example.com"}
        )
    assert resp.status_code == 405


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

    middleware = CsrfOriginCheckMiddleware(inner_app, trusted_origins=TRUSTED_ORIGINS)

    events = iter([{"type": "lifespan.startup"}])

    async def receive():
        return next(events)

    sent = []

    async def send(message):
        sent.append(message)

    await middleware({"type": "lifespan"}, receive, send)
    assert received["type"] == "lifespan"
    assert sent == [{"type": "lifespan.startup.complete"}]
