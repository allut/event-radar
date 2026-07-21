"""Tests for app.auth.email.send_magic_link — no-key, success, and error paths."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.auth import email


def _patch_client(monkeypatch, resp):
    """Patch httpx.AsyncClient so the ``async with ... as client`` yields a mock
    whose ``.post`` is an AsyncMock returning ``resp``. Returns that post mock."""
    post = AsyncMock(return_value=resp)

    @asynccontextmanager
    async def _ctx(*args, **kwargs):
        client = MagicMock()
        client.post = post
        yield client

    monkeypatch.setattr(email.httpx, "AsyncClient", MagicMock(side_effect=_ctx))
    return post


@pytest.mark.asyncio
async def test_no_api_key_logs_and_skips_send(monkeypatch, caplog):
    monkeypatch.setattr(email.settings, "RESEND_API_KEY", "")
    post = _patch_client(monkeypatch, MagicMock(status_code=200))

    await email.send_magic_link("user@example.com", "tok123")

    post.assert_not_awaited()
    # the signed token must never appear at WARNING or above
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= 30]
    assert all("tok123" not in m for m in warnings)


@pytest.mark.asyncio
async def test_success_posts_expected_payload(monkeypatch):
    monkeypatch.setattr(email.settings, "RESEND_API_KEY", "re_key")
    monkeypatch.setattr(email.settings, "RESEND_FROM_ADDRESS", "noreply@radar.ee")
    monkeypatch.setattr(email.settings, "FRONTEND_URL", "https://app.radar.ee")

    resp = MagicMock(status_code=httpx.codes.OK, text="ok")
    post = _patch_client(monkeypatch, resp)

    await email.send_magic_link("user@example.com", "tok123", locale="en")

    post.assert_awaited_once()
    _args, kwargs = post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer re_key"
    body = kwargs["json"]
    assert body["from"] == "noreply@radar.ee"
    assert body["to"] == ["user@example.com"]
    assert body["subject"]
    assert body["html"]
    assert body["text"]
    # verify URL carries the token
    assert "tok123" in body["html"] or "tok123" in body["text"]


@pytest.mark.asyncio
async def test_non_2xx_logs_error(monkeypatch, caplog):
    import logging

    monkeypatch.setattr(email.settings, "RESEND_API_KEY", "re_key")
    resp = MagicMock(status_code=422, text="bad payload")
    _patch_client(monkeypatch, resp)

    with caplog.at_level(logging.ERROR):
        await email.send_magic_link("user@example.com", "tok123")

    assert any("Resend API error" in r.getMessage() for r in caplog.records)
