"""Email ad consent against real Postgres: wording reset and cascade delete."""

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.constants.email import EMAIL_AD_CONSENT_WORDING_VERSION
from app.email.consent import log_account_deletion, reset_consent_for_wording_change
from app.models.promotions import EmailAdConsentLog
from app.models.users import User


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set")
    eng = create_async_engine(url)
    try:
        async with eng.connect() as conn:
            ok = await conn.scalar(text("SELECT to_regclass('public.email_ad_consent_log')"))
    except Exception:
        await eng.dispose()
        pytest.skip("Postgres unreachable")
    if ok is None:
        await eng.dispose()
        pytest.skip("migrations not applied")
    async with async_sessionmaker(eng, expire_on_commit=False)() as s:
        yield s
        await s.rollback()
    await eng.dispose()


def _user(email: str, version: int | None, consent: bool = True) -> User:
    return User(
        email=email,
        locale="ru",
        email_digest_opt_in=True,
        email_ad_consent=consent,
        email_ad_consent_version=version,
    )


@pytest.mark.asyncio
async def test_wording_reset_only_touches_stale_consenters(session) -> None:
    stale = _user("stale-610@example.test", EMAIL_AD_CONSENT_WORDING_VERSION + 1)
    current = _user("current-610@example.test", EMAIL_AD_CONSENT_WORDING_VERSION)
    off = _user("off-610@example.test", None, consent=False)
    session.add_all([stale, current, off])
    await session.flush()
    stale_id, current_id = stale.id, current.id

    assert await reset_consent_for_wording_change(session) >= 1
    await session.refresh(stale)
    await session.refresh(current)
    assert stale.email_ad_consent is False
    assert current.email_ad_consent is True
    rows = (
        await session.scalars(
            select(EmailAdConsentLog).where(EmailAdConsentLog.user_id == stale_id)
        )
    ).all()
    assert [(r.granted, r.source, r.locale) for r in rows] == [(False, "wording_change", "ru")]
    assert rows[0].wording_version == EMAIL_AD_CONSENT_WORDING_VERSION + 1
    assert (
        await session.scalar(
            select(EmailAdConsentLog).where(EmailAdConsentLog.user_id == current_id)
        )
        is None
    )


@pytest.mark.asyncio
async def test_account_deletion_logs_then_log_goes_with_the_account(session) -> None:
    user = _user("gone-610@example.test", EMAIL_AD_CONSENT_WORDING_VERSION)
    session.add(user)
    await session.flush()
    uid = user.id
    assert log_account_deletion(user, session) is True
    await session.flush()
    logged = await session.scalar(
        select(EmailAdConsentLog).where(EmailAdConsentLog.user_id == uid)
    )
    assert logged is not None and logged.source == "account_deletion"
    await session.delete(user)
    await session.flush()
    session.expunge_all()
    assert (
        await session.scalar(select(EmailAdConsentLog).where(EmailAdConsentLog.user_id == uid))
    ) is None
