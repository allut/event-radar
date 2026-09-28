"""Tests for app.email.claim_resolution (#421) — rendered content per
outcome/locale, fallback-note behavior, target-title fallback, and
no-key/error paths, mirroring tests/email/test_report_reporter.py."""

from unittest.mock import MagicMock

import httpx
import pytest

from app.email import resend
from app.email import claim_resolution


@pytest.mark.asyncio
async def test_no_api_key_logs_and_skips_send(patch_client, monkeypatch):
    monkeypatch.setattr(claim_resolution.settings, "RESEND_API_KEY", "")
    post = patch_client(resend, MagicMock(status_code=200))

    await claim_resolution.send_claim_granted_email(
        "organizer@example.com", "Jazz Night", "note", "en"
    )

    post.assert_not_awaited()


@pytest.mark.asyncio
async def test_granted_email_posts_expected_content(patch_client, monkeypatch):
    monkeypatch.setattr(claim_resolution.settings, "RESEND_API_KEY", "re_key")
    monkeypatch.setattr(claim_resolution.settings, "RESEND_FROM_ADDRESS", "noreply@radar.ee")
    monkeypatch.setattr(claim_resolution.settings, "CONTACT_TO_ADDRESS", "owner@radar.ee")
    monkeypatch.setattr(claim_resolution.settings, "FRONTEND_URL", "https://radar.ee")

    resp = MagicMock(status_code=httpx.codes.OK, text="ok")
    post = patch_client(resend, resp)

    await claim_resolution.send_claim_granted_email(
        "organizer@example.com", "Rave <night>", "Verified manually.", "en"
    )

    post.assert_awaited_once()
    _args, kwargs = post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer re_key"
    body = kwargs["json"]
    assert body["from"] == "noreply@radar.ee"
    assert body["to"] == ["organizer@example.com"]
    assert body["reply_to"] == "owner@radar.ee"
    assert body["subject"] == "Your claim was approved"

    html_body = body["html"]
    assert "&lt;night&gt;" in html_body
    assert "Verified manually." in html_body
    assert "https://radar.ee/organizer/dashboard" in html_body

    text_body = body["text"]
    assert "Verified manually." in text_body


@pytest.mark.asyncio
async def test_granted_blank_note_uses_fallback(patch_client, monkeypatch):
    monkeypatch.setattr(claim_resolution.settings, "RESEND_API_KEY", "re_key")
    monkeypatch.setattr(claim_resolution.settings, "FRONTEND_URL", "https://radar.ee")
    resp = MagicMock(status_code=httpx.codes.OK, text="ok")
    post = patch_client(resend, resp)

    await claim_resolution.send_claim_granted_email(
        "organizer@example.com", "Jazz Night", "   ", "en"
    )

    body = post.call_args.kwargs["json"]
    assert "You can now edit this listing" in body["html"]


@pytest.mark.asyncio
async def test_declined_email_uses_admin_note_and_own_subject(patch_client, monkeypatch):
    monkeypatch.setattr(claim_resolution.settings, "RESEND_API_KEY", "re_key")
    monkeypatch.setattr(claim_resolution.settings, "FRONTEND_URL", "https://radar.ee")
    resp = MagicMock(status_code=httpx.codes.OK, text="ok")
    post = patch_client(resend, resp)

    await claim_resolution.send_claim_declined_email(
        "organizer@example.com", "Jazz Night", "Domain mismatch.", "en"
    )

    body = post.call_args.kwargs["json"]
    assert body["subject"] == "Your claim was declined"
    assert "Domain mismatch." in body["html"]


@pytest.mark.asyncio
async def test_expired_email_includes_expiry_window(patch_client, monkeypatch):
    monkeypatch.setattr(claim_resolution.settings, "RESEND_API_KEY", "re_key")
    monkeypatch.setattr(claim_resolution.settings, "FRONTEND_URL", "https://radar.ee")
    resp = MagicMock(status_code=httpx.codes.OK, text="ok")
    post = patch_client(resend, resp)

    await claim_resolution.send_claim_expired_email("organizer@example.com", "Jazz Night", "en")

    body = post.call_args.kwargs["json"]
    assert body["subject"] == "Your claim has expired"
    assert "7 days" in body["html"]


@pytest.mark.asyncio
async def test_self_cancelled_email_own_subject(patch_client, monkeypatch):
    monkeypatch.setattr(claim_resolution.settings, "RESEND_API_KEY", "re_key")
    monkeypatch.setattr(claim_resolution.settings, "FRONTEND_URL", "https://radar.ee")
    resp = MagicMock(status_code=httpx.codes.OK, text="ok")
    post = patch_client(resend, resp)

    await claim_resolution.send_claim_self_cancelled_email(
        "organizer@example.com", "Jazz Night", "en"
    )

    body = post.call_args.kwargs["json"]
    assert body["subject"] == "Claim cancelled"


def test_no_event_title_falls_back_to_generic_wording():
    html = claim_resolution.build_claim_granted_html(None, "note", "en")
    assert "this listing" in html


@pytest.mark.asyncio
async def test_renders_per_locale():
    et_html = claim_resolution.build_claim_declined_html("Jazz Night", "note", "et")
    ru_html = claim_resolution.build_claim_declined_html("Jazz Night", "note", "ru")
    en_html = claim_resolution.build_claim_declined_html("Jazz Night", "note", "en")

    assert "Nõue tagasi lükatud" in et_html
    assert "Заявка отклонена" in ru_html
    assert "Claim declined" in en_html


def test_uses_the_one_light_base_client_adaptive_bundle():
    html = claim_resolution.build_claim_granted_html("Jazz Night", "note", "en")

    assert "#fdfcfa" in html
    assert 'content="light dark"' in html


@pytest.mark.asyncio
async def test_non_2xx_logs_error(patch_client, monkeypatch, caplog):
    import logging

    monkeypatch.setattr(claim_resolution.settings, "RESEND_API_KEY", "re_key")
    resp = MagicMock(status_code=422, text="bad payload")
    patch_client(resend, resp)

    with caplog.at_level(logging.ERROR):
        await claim_resolution.send_claim_granted_email(
            "organizer@example.com", "Jazz Night", "note", "en"
        )

    assert any("Resend API error" in r.getMessage() for r in caplog.records)
