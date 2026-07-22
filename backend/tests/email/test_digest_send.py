"""Tests for app.email.digest.send_digest_email — no-key, success, error paths."""

from contextlib import asynccontextmanager
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.email import digest
from app.email.digest import send_digest_email


def _patch_client(monkeypatch):
    @asynccontextmanager
    async def _ctx(*args, **kwargs):
        yield MagicMock()

    monkeypatch.setattr(digest.httpx, "AsyncClient", MagicMock(side_effect=_ctx))


@pytest.mark.asyncio
async def test_no_api_key_skips_send(monkeypatch, make_event):
    monkeypatch.setattr(digest.settings, "RESEND_API_KEY", "")
    post = AsyncMock()
    monkeypatch.setattr(digest, "http_post", post)

    await send_digest_email("u@example.com", "en", [make_event()], date(2026, 7, 21))

    post.assert_not_awaited()


@pytest.mark.asyncio
async def test_success_calls_http_post(monkeypatch, make_event):
    monkeypatch.setattr(digest.settings, "RESEND_API_KEY", "re_key")
    monkeypatch.setattr(digest.settings, "RESEND_FROM_ADDRESS", "d@radar.ee")
    monkeypatch.setattr(digest.settings, "FRONTEND_URL", "https://app.radar.ee")
    _patch_client(monkeypatch)
    post = AsyncMock()
    monkeypatch.setattr(digest, "http_post", post)

    await send_digest_email(
        "u@example.com", "en", [make_event(why_go=["a", "b", "c"])], date(2026, 7, 21)
    )

    post.assert_awaited_once()
    _args, kwargs = post.call_args
    body = kwargs["json_body"]
    assert body["from"] == "d@radar.ee"
    assert body["to"] == ["u@example.com"]
    assert body["subject"]
    assert body["html"]


@pytest.mark.asyncio
async def test_http_error_raises_runtime_error(monkeypatch, make_event):
    monkeypatch.setattr(digest.settings, "RESEND_API_KEY", "re_key")
    _patch_client(monkeypatch)

    resp = MagicMock(status_code=422, text="bad")
    err = httpx.HTTPStatusError("boom", request=MagicMock(), response=resp)
    monkeypatch.setattr(digest, "http_post", AsyncMock(side_effect=err))

    with pytest.raises(RuntimeError, match="Resend returned 422"):
        await send_digest_email(
            "u@example.com", "en", [make_event()], date(2026, 7, 21)
        )
