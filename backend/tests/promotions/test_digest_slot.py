"""The digest Sponsored slot (#611) against a real Postgres: who gets it, the
rendered block in the sent email, and the digest_sent count.

Everything rolls back with the test's outer transaction. The send itself is
mocked at ``http_post``; the Resend client never opens a connection.
"""

import os
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.config import settings
from app.constants.core import TALLINN_TZ
from app.email import digest
from app.models.models import DailyFeed, DailySponsoredSlot, User
from app.promotions import counters
from app.promotions.digest_slot import load_digest_slots
from tests.conftest import Factory
from tests.promotions.test_daily5_slot import _n, organic, promoted, today


@pytest.fixture(autouse=True)
def _flags(monkeypatch):
    monkeypatch.setattr(settings, "PROMOTIONS_SLOTS_ENABLED", True)
    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_key")
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://app.radar.ee")
    counters.reset()
    yield
    counters.reset()


def now():
    return datetime.now(TALLINN_TZ)


async def subscriber(db, *, consent: bool = True, locale: str = "en") -> User:
    u = User(
        email=f"dg-{next(_n)}-{os.getpid()}@example.com",
        email_verified=True,
        email_digest_opt_in=True,
        email_ad_consent=consent,
        email_ad_consent_version=1 if consent else None,
        locale=locale,
    )
    db.add(u)
    await db.flush()
    return u


async def with_feed(db, user: User, events: list) -> None:
    db.add(DailyFeed(user_id=user.id, feed_date=today(), event_ids=[e.id for e in events]))
    await db.flush()


async def store_slot(db, user: User, promo) -> None:
    db.add(DailySponsoredSlot(user_id=user.id, slot_date=today(), promotion_id=promo.id))
    await db.flush()


async def setup(db, make: Factory, *, consent: bool = True, locale: str = "en"):
    org = await make.organizer("Acme")
    five = (await organic(make))[:5]
    ev, promo = await promoted(make, org)
    user = await subscriber(db, consent=consent, locale=locale)
    await with_feed(db, user, five)
    await store_slot(db, user, promo)
    return user, five, ev, promo


def capture(monkeypatch) -> dict[str, dict]:
    """Map recipient email -> posted JSON body."""
    sent: dict[str, dict] = {}

    async def fake_post(client, url, *, headers, json_body):
        sent[json_body["to"][0]] = json_body

    monkeypatch.setattr(digest, "http_post", fake_post)
    return sent


@pytest.mark.asyncio
async def test_loader_returns_stored_slot_with_advertiser(db, make) -> None:
    user, _five, ev, promo = await setup(db, make)

    out = await load_digest_slots(db, [user.id], now())

    assert out[user.id].promotion_id == promo.id
    assert out[user.id].event.id == ev.id
    assert out[user.id].advertiser == "Acme OÜ"


@pytest.mark.asyncio
async def test_loader_empty_when_flag_off(db, make, monkeypatch) -> None:
    user, *_ = await setup(db, make)
    monkeypatch.setattr(settings, "PROMOTIONS_SLOTS_ENABLED", False)

    assert await load_digest_slots(db, [user.id], now()) == {}


@pytest.mark.asyncio
async def test_loader_skips_user_without_stored_slot(db, make) -> None:
    user, *_ = await setup(db, make)
    other = await subscriber(db)

    out = await load_digest_slots(db, [user.id, other.id], now())

    assert set(out) == {user.id}


@pytest.mark.asyncio
async def test_loader_drops_slot_whose_promotion_fails_the_gate(db, make) -> None:
    user, _five, _ev, promo = await setup(db, make)
    promo.status = "void"
    await db.flush()

    assert await load_digest_slots(db, [user.id], now()) == {}


@pytest.mark.asyncio
async def test_consenting_user_with_full_five_and_slot_gets_block_and_count(
    db, make, monkeypatch
) -> None:
    user, five, ev, promo = await setup(db, make)
    sent = capture(monkeypatch)

    await digest.send_daily_digests(db)

    body = sent[user.email]
    html = body["html"]
    assert "Paid for by Acme OÜ" in html
    assert f"/en/events/{ev.id}?ref=digest-ad" in html
    assert "/en/email-consent-off?token=" in html
    assert html.index("Paid for by") > html.rindex(f"/en/events/{five[-1].id}")
    assert "Acme" not in body["subject"] and "Ad" not in body["subject"].split()
    assert counters._pending[(promo.id, today(), "digest_sent")] == 1


@pytest.mark.asyncio
async def test_no_block_without_consent(db, make, monkeypatch) -> None:
    user, *_ = await setup(db, make, consent=False)
    sent = capture(monkeypatch)

    await digest.send_daily_digests(db)

    assert "ref=digest-ad" not in sent[user.email]["html"]
    assert not counters._pending


@pytest.mark.asyncio
async def test_no_block_when_flag_off(db, make, monkeypatch) -> None:
    user, *_ = await setup(db, make)
    monkeypatch.setattr(settings, "PROMOTIONS_SLOTS_ENABLED", False)
    sent = capture(monkeypatch)

    await digest.send_daily_digests(db)

    assert "ref=digest-ad" not in sent[user.email]["html"]


@pytest.mark.asyncio
async def test_no_block_without_full_five(db, make, monkeypatch) -> None:
    org = await make.organizer("Acme")
    four = (await organic(make))[:4]
    _ev, promo = await promoted(make, org)
    user = await subscriber(db)
    await with_feed(db, user, four)
    await store_slot(db, user, promo)
    sent = capture(monkeypatch)

    await digest.send_daily_digests(db)

    assert "ref=digest-ad" not in sent[user.email]["html"]


@pytest.mark.asyncio
async def test_no_block_without_stored_slot(db, make, monkeypatch) -> None:
    user, *_ = await setup(db, make)
    row = await db.scalar(
        select(DailySponsoredSlot).where(DailySponsoredSlot.user_id == user.id)
    )
    await db.delete(row)
    await db.flush()
    sent = capture(monkeypatch)

    await digest.send_daily_digests(db)

    assert "ref=digest-ad" not in sent[user.email]["html"]


@pytest.mark.asyncio
async def test_failed_send_is_not_counted(db, make, monkeypatch) -> None:
    await setup(db, make)
    monkeypatch.setattr(digest, "http_post", AsyncMock(side_effect=RuntimeError("boom")))

    await digest.send_daily_digests(db)

    assert not counters._pending


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("locale", "label", "advertiser", "stop"),
    [
        ("et", "Reklaam", "Reklaami tellija: Acme OÜ", "Ära näita reklaame e-kirjas"),
        ("en", "Ad", "Paid for by Acme OÜ", "Stop ads in this email"),
        ("ru", "Реклама", "Рекламодатель: Acme OÜ", "Не показывать рекламу в письмах"),
    ],
)
async def test_block_copy_in_each_locale(
    db, make, monkeypatch, locale, label, advertiser, stop
) -> None:
    user, *_ = await setup(db, make, locale=locale)
    sent = capture(monkeypatch)

    await digest.send_daily_digests(db)

    html = sent[user.email]["html"]
    assert f">{label}</p>" in html
    assert advertiser in html
    assert stop in html

