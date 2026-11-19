"""The Organizer email for an ended or voided Promotion (the P2B statement of
reasons): the admin's reason, in the Organizer's locale."""

from datetime import date
from unittest.mock import MagicMock

import httpx
import pytest

from app.config import settings
from app.email import promotion_notice, resend


def configure(monkeypatch) -> None:
    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_key")
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://radar.example")


async def send_ended(locale: str, reason: str = "Event <moved>") -> None:
    await promotion_notice.send_promotion_ended_email(
        "org@example.com", "Jazz Night", date(2090, 1, 10), date(2090, 1, 14), reason, locale
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("locale", "subject", "phrase"),
    [
        ("en", "Your Promotion ended early", "was ended early"),
        ("et", "Sinu reklaamiperiood lõpetati enneaegselt", "lõpetati enneaegselt"),
        ("ru", "Ваше продвижение завершено досрочно", "завершено досрочно"),
    ],
)
async def test_ended_email_carries_the_reason_in_the_locale(
    patch_client, monkeypatch, locale, subject, phrase
) -> None:
    configure(monkeypatch)
    post = patch_client(resend, MagicMock(status_code=httpx.codes.OK, text="ok"))

    await send_ended(locale)

    body = post.call_args.kwargs["json"]
    assert body["to"] == ["org@example.com"]
    assert body["subject"] == subject
    assert phrase in body["html"]
    assert "Jazz Night" in body["html"]
    assert "2090-01-10" in body["html"] and "2090-01-14" in body["html"]
    assert "Event &lt;moved&gt;" in body["html"]
    assert "Event <moved>" in body["text"]


@pytest.mark.asyncio
async def test_void_email_has_its_own_subject_and_the_reason(patch_client, monkeypatch) -> None:
    configure(monkeypatch)
    post = patch_client(resend, MagicMock(status_code=httpx.codes.OK, text="ok"))

    await promotion_notice.send_promotion_void_email(
        "org@example.com", "Jazz Night", date(2090, 1, 10), date(2090, 1, 14), "Not paid in time", "en"
    )

    body = post.call_args.kwargs["json"]
    assert body["subject"] == "Your Promotion was cancelled"
    assert "Not paid in time" in body["html"]


@pytest.mark.asyncio
async def test_no_api_key_skips_the_send(patch_client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "RESEND_API_KEY", "")
    post = patch_client(resend, MagicMock(status_code=httpx.codes.OK))

    await send_ended("en")

    post.assert_not_awaited()
