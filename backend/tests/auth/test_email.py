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


# Email links point at the recipient's locale prefix — the verify pages take
# their language from the URL alone (#499). ET stays bare.
_LOCALE_PREFIXES = [("et", ""), ("en", "/en"), ("ru", "/ru")]


@pytest.mark.asyncio
@pytest.mark.parametrize(("locale", "prefix"), _LOCALE_PREFIXES)
@pytest.mark.parametrize(
    "verify_path",
    ["/auth/verify", "/organizer/verify", "/organizer/claims/verify"],
)
async def test_magic_link_url_carries_locale_prefix(
    patch_client, monkeypatch, locale, prefix, verify_path
):
    monkeypatch.setattr(email.settings, "RESEND_API_KEY", "re_key")
    monkeypatch.setattr(email.settings, "FRONTEND_URL", "https://app.radar.ee")
    post = patch_client(resend, MagicMock(status_code=httpx.codes.OK, text="ok"))

    await email.send_magic_link(
        "user@example.com", "tok123", locale=locale, verify_path=verify_path
    )

    body = post.call_args.kwargs["json"]
    expected = f"https://app.radar.ee{prefix}{verify_path}?token=tok123"
    assert expected in body["text"]
    assert expected in body["html"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("locale", "prefix"), _LOCALE_PREFIXES)
async def test_google_link_confirmation_url_carries_locale_prefix(
    patch_client, monkeypatch, locale, prefix
):
    monkeypatch.setattr(email.settings, "RESEND_API_KEY", "re_key")
    monkeypatch.setattr(email.settings, "FRONTEND_URL", "https://app.radar.ee")
    post = patch_client(resend, MagicMock(status_code=httpx.codes.OK, text="ok"))

    await email.send_google_link_confirmation(
        "user@example.com", "tok123", locale=locale, verify_path="/organizer/verify"
    )

    body = post.call_args.kwargs["json"]
    expected = f"https://app.radar.ee{prefix}/organizer/verify?token=tok123"
    assert expected in body["text"]
    assert expected in body["html"]
