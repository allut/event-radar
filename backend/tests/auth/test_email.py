"""Tests for app.auth.email.send_magic_link — no-key, success, and error paths."""

from unittest.mock import MagicMock

import httpx
import pytest

from app.email import resend
from app.auth import email


@pytest.mark.asyncio
async def test_no_api_key_logs_and_skips_send(patch_client, monkeypatch, caplog):
    monkeypatch.setattr(email.settings, "RESEND_API_KEY", "")
    post = patch_client(resend, MagicMock(status_code=200))

    await email.send_magic_link("user@example.com", "tok123")

    post.assert_not_awaited()
    # the signed token must never appear at WARNING or above
    warnings = [r.getMessage() for r in caplog.records if r.levelno >= 30]
    assert all("tok123" not in m for m in warnings)


@pytest.mark.asyncio
async def test_success_posts_expected_payload(patch_client, monkeypatch):
    monkeypatch.setattr(email.settings, "RESEND_API_KEY", "re_key")
    monkeypatch.setattr(email.settings, "RESEND_FROM_ADDRESS", "noreply@radar.ee")
    monkeypatch.setattr(email.settings, "FRONTEND_URL", "https://app.radar.ee")

    resp = MagicMock(status_code=httpx.codes.OK, text="ok")
    post = patch_client(resend, resp)

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
async def test_non_2xx_logs_error(patch_client, monkeypatch, caplog):
    import logging

    monkeypatch.setattr(email.settings, "RESEND_API_KEY", "re_key")
    resp = MagicMock(status_code=422, text="bad payload")
    patch_client(resend, resp)

    with caplog.at_level(logging.ERROR):
        await email.send_magic_link("user@example.com", "tok123")

    assert any("Resend API error" in r.getMessage() for r in caplog.records)
