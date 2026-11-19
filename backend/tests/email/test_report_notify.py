"""Tests for app.email.report_notify.send_report_notification — no-key,
success, and error paths, mirroring tests/email/test_contact.py."""

from unittest.mock import MagicMock

import httpx
import pytest

from app.email import resend
from app.email import report_notify


@pytest.mark.asyncio
async def test_no_api_key_logs_and_skips_send(patch_client, monkeypatch, make_event):
    monkeypatch.setattr(report_notify.settings, "RESEND_API_KEY", "")
    post = patch_client(resend, MagicMock(status_code=200))

    await report_notify.send_report_notification(
        make_event(10), "spam_or_scam", None, False, 1, "reporter@example.com"
    )

    post.assert_not_awaited()


@pytest.mark.asyncio
async def test_success_posts_expected_content(patch_client, monkeypatch, make_event):
    monkeypatch.setattr(report_notify.settings, "RESEND_API_KEY", "re_key")
    monkeypatch.setattr(report_notify.settings, "RESEND_FROM_ADDRESS", "noreply@radar.example")
    monkeypatch.setattr(report_notify.settings, "CONTACT_TO_ADDRESS", "owner@radar.example")
    monkeypatch.setattr(report_notify.settings, "FRONTEND_URL", "https://radar.example")
    monkeypatch.setattr(report_notify.settings, "BACKEND_URL", "https://api.radar.example")

    resp = MagicMock(status_code=httpx.codes.OK, text="ok")
    post = patch_client(resend, resp)

    event = make_event(42, title="Rave <night>")
    await report_notify.send_report_notification(
        event,
        "sexual_or_explicit",
        "explicit <content>",
        True,
        1,
        "reporter@example.com",
    )

    post.assert_awaited_once()
    _args, kwargs = post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer re_key"
    body = kwargs["json"]
    assert body["from"] == "noreply@radar.example"
    assert body["to"] == ["owner@radar.example"]
    assert "Rave" in body["subject"]

    html_body = body["html"]
    # user-supplied fields escaped
    assert "&lt;night&gt;" in html_body
    assert "&lt;content&gt;" in html_body
    assert "https://radar.example/events/42" in html_body
    assert event.url in html_body
    assert "sexual_or_explicit" in html_body
    assert "reporter@example.com" in html_body
    assert "Report count:</strong> 1" in html_body
    assert "Illegal allegation:</strong> True" in html_body
    # unmasked reporter email — no @-masking applied
    assert "r***@example.com" not in html_body
    # single console deep link, no curl snippets
    assert "curl" not in html_body
    assert "https://radar.example/admin/reports?report=42" in html_body

    text_body = body["text"]
    assert "reporter@example.com" in text_body
    assert "curl" not in text_body
    assert "https://radar.example/admin/reports?report=42" in text_body


@pytest.mark.asyncio
async def test_non_2xx_logs_error(patch_client, monkeypatch, caplog, make_event):
    import logging

    monkeypatch.setattr(report_notify.settings, "RESEND_API_KEY", "re_key")
    resp = MagicMock(status_code=422, text="bad payload")
    patch_client(resend, resp)

    with caplog.at_level(logging.ERROR):
        await report_notify.send_report_notification(
            make_event(10), "other", "detail", False, 1, "reporter@example.com"
        )

    assert any("Resend API error" in r.getMessage() for r in caplog.records)
