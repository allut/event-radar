import base64
import logging
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.email import resend
from app.email.brand import BRAND_MARK_SRC


@pytest.mark.asyncio
async def test_no_api_key_warns_and_skips_send(patch_client, monkeypatch, caplog):
    monkeypatch.setattr(resend.settings, "RESEND_API_KEY", "")
    post = patch_client(resend, MagicMock(status_code=200))
    with caplog.at_level(logging.WARNING):
        await resend.send_resend_email({}, log_label="x", log_ref="ref")
    post.assert_not_awaited()
    assert any("RESEND_API_KEY not set" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_success_adds_from_and_bearer_header(patch_client, monkeypatch):
    monkeypatch.setattr(resend.settings, "RESEND_API_KEY", "re_key")
    monkeypatch.setattr(resend.settings, "RESEND_FROM_ADDRESS", "noreply@radar.ee")
    post = patch_client(resend, MagicMock(status_code=httpx.codes.OK, text="ok"))
    await resend.send_resend_email({"to": ["a@b.ee"]}, log_label="x", log_ref="ref")
    post.assert_awaited_once()
    _, kwargs = post.await_args
    assert kwargs["headers"]["Authorization"] == "Bearer re_key"
    assert kwargs["json"] == {"from": "noreply@radar.ee", "to": ["a@b.ee"]}


@pytest.mark.asyncio
async def test_non_2xx_logs_error_without_raising(patch_client, monkeypatch, caplog):
    monkeypatch.setattr(resend.settings, "RESEND_API_KEY", "re_key")
    patch_client(resend, MagicMock(status_code=500, text="boom"))
    with caplog.at_level(logging.ERROR):
        await resend.send_resend_email({}, log_label="x", log_ref="ref")
    assert any("Resend API error" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_passed_client_is_reused(patch_client, monkeypatch):
    monkeypatch.setattr(resend.settings, "RESEND_API_KEY", "re_key")
    opener = patch_client(resend, MagicMock(status_code=200, text="ok"))
    client = MagicMock()
    client.post = AsyncMock(return_value=MagicMock(status_code=200, text="ok"))
    await resend.send_resend_email(
        {}, http_client=client, log_label="x", log_ref="ref"
    )
    client.post.assert_awaited_once()
    opener.assert_not_awaited()


@pytest.mark.asyncio
async def test_branded_html_gets_inline_mark_attachment(patch_client, monkeypatch):
    monkeypatch.setattr(resend.settings, "RESEND_API_KEY", "re_key")
    post = patch_client(resend, MagicMock(status_code=httpx.codes.OK, text="ok"))
    html = f'<img src="{BRAND_MARK_SRC}">'
    await resend.send_resend_email({"html": html}, log_label="x", log_ref="ref")
    [mark] = post.await_args.kwargs["json"]["attachments"]
    assert mark["content_id"] == "event-radar-mark"
    assert mark["filename"] == "email-mark.png"
    assert base64.b64decode(mark["content"]).startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_unbranded_html_gets_no_attachment(patch_client, monkeypatch):
    monkeypatch.setattr(resend.settings, "RESEND_API_KEY", "re_key")
    post = patch_client(resend, MagicMock(status_code=httpx.codes.OK, text="ok"))
    await resend.send_resend_email({"html": "<p>hi</p>"}, log_label="x", log_ref="ref")
    assert "attachments" not in post.await_args.kwargs["json"]
