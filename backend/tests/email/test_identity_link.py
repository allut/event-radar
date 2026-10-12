"""Google-link confirmation + identity-linked notice emails (OWASP audit #3)."""

from unittest.mock import MagicMock

import httpx
import pytest

from app.auth import email
from app.email import resend
from app.email.identity_link import (
    build_google_link_confirmation_html,
    build_google_link_confirmation_text,
    build_identity_linked_html,
    build_identity_linked_text,
)

VERIFY_URL = "https://app.example.com/auth/verify?token=abc&x=1"


@pytest.mark.parametrize("locale", ["en", "et", "ru"])
def test_confirmation_names_the_address_and_carries_the_link(locale):
    html = build_google_link_confirmation_html(VERIFY_URL, 15, "person@yahoo.com", locale)
    text = build_google_link_confirmation_text(VERIFY_URL, 15, "person@yahoo.com", locale)

    assert "person@yahoo.com" in html
    assert "person@yahoo.com" in text
    assert "https://app.example.com/auth/verify?token=abc&amp;x=1" in html
    assert VERIFY_URL in text
    # No unformatted placeholders left behind in any locale.
    assert "{" not in text


def test_confirmation_is_distinct_from_the_plain_sign_in_email():
    from app.email.magic_link import build_magic_link_text

    google = build_google_link_confirmation_text(VERIFY_URL, 15, "p@yahoo.com", "en")
    plain = build_magic_link_text(VERIFY_URL, 15, "en")
    assert "Google" in google
    assert "Google" not in plain


def test_confirmation_escapes_the_address():
    html = build_google_link_confirmation_html(VERIFY_URL, 15, "a<b>@x.com", "en")
    assert "a<b>@x.com" not in html
    assert "a&lt;b&gt;@x.com" in html


@pytest.mark.parametrize("locale", ["en", "et", "ru"])
def test_identity_linked_notice_names_the_account(locale):
    html = build_identity_linked_html("owner@gmail.com", locale)
    text = build_identity_linked_text("owner@gmail.com", locale)
    assert "owner@gmail.com" in html
    assert "owner@gmail.com" in text
    assert "{" not in text


@pytest.mark.asyncio
async def test_send_google_link_confirmation_posts_own_subject_and_link(
    patch_client, monkeypatch
):
    monkeypatch.setattr(email.settings, "RESEND_API_KEY", "re_key")
    monkeypatch.setattr(email.settings, "FRONTEND_URL", "https://app.radar.ee")
    post = patch_client(resend, MagicMock(status_code=httpx.codes.OK, text="ok"))

    await email.send_google_link_confirmation(
        "person@yahoo.com", "tok123", locale="en", verify_path="/organizer/verify"
    )

    body = post.call_args.kwargs["json"]
    assert body["to"] == ["person@yahoo.com"]
    assert body["subject"] == "Confirm Google sign-in for Event Radar"
    assert "https://app.radar.ee/en/organizer/verify?token=tok123" in body["text"]


@pytest.mark.asyncio
async def test_send_google_link_confirmation_never_logs_token_without_api_key(
    patch_client, monkeypatch, caplog
):
    monkeypatch.setattr(email.settings, "RESEND_API_KEY", "")
    post = patch_client(resend, MagicMock(status_code=200))

    await email.send_google_link_confirmation("person@yahoo.com", "tok123")

    post.assert_not_awaited()
    assert all("tok123" not in r.getMessage() for r in caplog.records if r.levelno >= 30)


@pytest.mark.asyncio
async def test_send_identity_linked_notice_posts_expected_payload(
    patch_client, monkeypatch
):
    monkeypatch.setattr(email.settings, "RESEND_API_KEY", "re_key")
    post = patch_client(resend, MagicMock(status_code=httpx.codes.OK, text="ok"))

    await email.send_identity_linked_notice("owner@gmail.com", "et")

    body = post.call_args.kwargs["json"]
    assert body["to"] == ["owner@gmail.com"]
    assert body["subject"] == "Google'iga sisselogimine seoti sinu Event Radari kontoga"


@pytest.mark.asyncio
async def test_send_identity_linked_notice_skips_without_api_key(
    patch_client, monkeypatch
):
    monkeypatch.setattr(email.settings, "RESEND_API_KEY", "")
    post = patch_client(resend, MagicMock(status_code=200))

    await email.send_identity_linked_notice("owner@gmail.com")

    post.assert_not_awaited()


def test_notice_headers_carry_brand_mark():
    confirmation = build_google_link_confirmation_html(VERIFY_URL, 15, "a@b.com", "en")
    notice = build_identity_linked_html("a@b.com", "en")

    assert "cid:event-radar-mark" in confirmation
    assert "cid:event-radar-mark" in notice
