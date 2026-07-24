"""Tests for app.email.contact.send_contact_message — no-key, success, and error paths."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.email import contact


def _patch_client(monkeypatch, resp):
    """Patch httpx.AsyncClient so the ``async with ... as client`` yields a mock
    whose ``.post`` is an AsyncMock returning ``resp``. Returns that post mock."""
    post = AsyncMock(return_value=resp)

    @asynccontextmanager
    async def _ctx(*args, **kwargs):
        client = MagicMock()
        client.post = post
        yield client

    monkeypatch.setattr(contact.httpx, "AsyncClient", MagicMock(side_effect=_ctx))
    return post


@pytest.mark.asyncio
async def test_no_api_key_logs_and_skips_send(monkeypatch):
    monkeypatch.setattr(contact.settings, "RESEND_API_KEY", "")
    post = _patch_client(monkeypatch, MagicMock(status_code=200))

    await contact.send_contact_message("Jane", "jane@example.com", "hello there")

    post.assert_not_awaited()


@pytest.mark.asyncio
async def test_success_posts_expected_payload(monkeypatch):
    monkeypatch.setattr(contact.settings, "RESEND_API_KEY", "re_key")
    monkeypatch.setattr(contact.settings, "RESEND_FROM_ADDRESS", "noreply@radar.ee")
    monkeypatch.setattr(contact.settings, "CONTACT_TO_ADDRESS", "owner@radar.ee")

    resp = MagicMock(status_code=httpx.codes.OK, text="ok")
    post = _patch_client(monkeypatch, resp)

    await contact.send_contact_message("Jane", "jane@example.com", "Hello <there>")

    post.assert_awaited_once()
    _args, kwargs = post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer re_key"
    body = kwargs["json"]
    assert body["from"] == "noreply@radar.ee"
    assert body["to"] == ["owner@radar.ee"]
    assert body["reply_to"] == "jane@example.com"
    assert "Jane" in body["subject"]
    # user-supplied HTML must be escaped in the html body
    assert "&lt;there&gt;" in body["html"]
    assert "Hello <there>" in body["text"]


@pytest.mark.asyncio
async def test_multiline_name_collapsed_in_subject(monkeypatch):
    monkeypatch.setattr(contact.settings, "RESEND_API_KEY", "re_key")
    resp = MagicMock(status_code=httpx.codes.OK, text="ok")
    post = _patch_client(monkeypatch, resp)

    await contact.send_contact_message("Jane\nSubject: hijacked", "jane@example.com", "hi")

    body = post.call_args.kwargs["json"]
    assert "\n" not in body["subject"]


@pytest.mark.asyncio
async def test_non_2xx_logs_error(monkeypatch, caplog):
    import logging

    monkeypatch.setattr(contact.settings, "RESEND_API_KEY", "re_key")
    resp = MagicMock(status_code=422, text="bad payload")
    _patch_client(monkeypatch, resp)

    with caplog.at_level(logging.ERROR):
        await contact.send_contact_message("Jane", "jane@example.com", "hi")

    assert any("Resend API error" in r.getMessage() for r in caplog.records)
