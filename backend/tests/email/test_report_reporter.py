"""Tests for app.email.report_reporter — rendered content per locale,
fallback-note behavior, and no-key/error paths, mirroring
tests/email/test_report_notify.py."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.email import report_reporter


def _patch_client(monkeypatch, resp):
    post = AsyncMock(return_value=resp)

    @asynccontextmanager
    async def _ctx(*args, **kwargs):
        client = MagicMock()
        client.post = post
        yield client

    monkeypatch.setattr(
        report_reporter.httpx, "AsyncClient", MagicMock(side_effect=_ctx)
    )
    return post


@pytest.mark.asyncio
async def test_no_api_key_logs_and_skips_send(monkeypatch, make_event):
    monkeypatch.setattr(report_reporter.settings, "RESEND_API_KEY", "")
    post = _patch_client(monkeypatch, MagicMock(status_code=200))

    await report_reporter.send_report_outcome_email(
        "reporter@example.com", make_event(10), "Looked into it.", "en"
    )

    post.assert_not_awaited()


@pytest.mark.asyncio
async def test_success_posts_expected_content(monkeypatch, make_event):
    monkeypatch.setattr(report_reporter.settings, "RESEND_API_KEY", "re_key")
    monkeypatch.setattr(
        report_reporter.settings, "RESEND_FROM_ADDRESS", "noreply@radar.ee"
    )
    monkeypatch.setattr(
        report_reporter.settings, "CONTACT_TO_ADDRESS", "owner@radar.ee"
    )
    monkeypatch.setattr(report_reporter.settings, "FRONTEND_URL", "https://radar.ee")

    resp = MagicMock(status_code=httpx.codes.OK, text="ok")
    post = _patch_client(monkeypatch, resp)

    event = make_event(42, title="Rave <night>")
    await report_reporter.send_report_outcome_email(
        "reporter@example.com", event, "Looked into it, event is fine.", "en"
    )

    post.assert_awaited_once()
    _args, kwargs = post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer re_key"
    body = kwargs["json"]
    assert body["from"] == "noreply@radar.ee"
    assert body["to"] == ["reporter@example.com"]
    assert body["reply_to"] == "owner@radar.ee"

    html_body = body["html"]
    assert "&lt;night&gt;" in html_body
    assert "Looked into it, event is fine." in html_body
    assert "https://radar.ee/events/42" in html_body
    # no "automated means" disclosure
    assert "automated" not in html_body.lower()

    text_body = body["text"]
    assert "Looked into it, event is fine." in text_body
    assert "https://radar.ee/events/42" in text_body


@pytest.mark.asyncio
async def test_blank_note_uses_fallback(monkeypatch, make_event):
    monkeypatch.setattr(report_reporter.settings, "RESEND_API_KEY", "re_key")
    monkeypatch.setattr(report_reporter.settings, "FRONTEND_URL", "https://radar.ee")
    resp = MagicMock(status_code=httpx.codes.OK, text="ok")
    post = _patch_client(monkeypatch, resp)

    await report_reporter.send_report_outcome_email(
        "reporter@example.com", make_event(10), "   ", "en"
    )

    body = post.call_args.kwargs["json"]
    assert "reviewed your report and made a decision" in body["html"]
    assert "We've reviewed your report and made a decision." in body["text"]


@pytest.mark.asyncio
async def test_renders_per_locale(monkeypatch, make_event):
    monkeypatch.setattr(report_reporter.settings, "FRONTEND_URL", "https://radar.ee")
    event = make_event(10, title="Concert")

    et_html = report_reporter.build_report_outcome_html(event, "Fine.", "et")
    ru_html = report_reporter.build_report_outcome_html(event, "Fine.", "ru")
    en_html = report_reporter.build_report_outcome_html(event, "Fine.", "en")

    assert "Teade vaadatud" in et_html
    assert "Жалоба рассмотрена" in ru_html
    assert "Report reviewed" in en_html


@pytest.mark.asyncio
async def test_non_2xx_logs_error(monkeypatch, caplog, make_event):
    import logging

    monkeypatch.setattr(report_reporter.settings, "RESEND_API_KEY", "re_key")
    resp = MagicMock(status_code=422, text="bad payload")
    _patch_client(monkeypatch, resp)

    with caplog.at_level(logging.ERROR):
        await report_reporter.send_report_outcome_email(
            "reporter@example.com", make_event(10), "note", "en"
        )

    assert any("Resend API error" in r.getMessage() for r in caplog.records)
