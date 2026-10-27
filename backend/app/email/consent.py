"""Email ad consent: the only place the flag and its append-only log are written.

Subscribing to the digest is never this consent, and it starts off. Callers
commit; every state change appends one `email_ad_consent_log` row.
"""

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.email import (
    CONSENT_SOURCE_ACCOUNT_DELETION,
    CONSENT_SOURCE_WORDING_CHANGE,
    EMAIL_AD_CONSENT_WORDING_VERSION,
)
from app.models.models import EmailAdConsentLog, User


def grant_ad_consent(user: User, db: AsyncSession, source: str) -> bool:
    """Turn consent on at the current wording version. False when already on."""
    if (
        user.email_ad_consent
        and user.email_ad_consent_version == EMAIL_AD_CONSENT_WORDING_VERSION
    ):
        return False
    user.email_ad_consent = True
    user.email_ad_consent_version = EMAIL_AD_CONSENT_WORDING_VERSION
    db.add(
        EmailAdConsentLog(
            user_id=user.id,
            granted=True,
            wording_version=EMAIL_AD_CONSENT_WORDING_VERSION,
            source=source,
            locale=user.locale,
        )
    )
    return True


def withdraw_ad_consent(user: User, db: AsyncSession, source: str) -> bool:
    """Turn consent off, logging the version that was consented to. False when already off."""
    if not user.email_ad_consent:
        return False
    version = user.email_ad_consent_version or EMAIL_AD_CONSENT_WORDING_VERSION
    user.email_ad_consent = False
    user.email_ad_consent_version = None
    db.add(
        EmailAdConsentLog(
            user_id=user.id,
            granted=False,
            wording_version=version,
            source=source,
            locale=user.locale,
        )
    )
    return True


def log_account_deletion(user: User, db: AsyncSession) -> bool:
    """Log `account_deletion` before the user row (and its log) is deleted."""
    return withdraw_ad_consent(user, db, CONSENT_SOURCE_ACCOUNT_DELETION)


async def reset_consent_for_wording_change(db: AsyncSession) -> int:
    """Reset everyone consented to an older wording version to off, logging
    `wording_change` with the version they had agreed to. Two statements
    whatever the row count, and no id list bound as parameters: the UPDATE
    reads the stale rows through a CTE and returns their old version.
    Returns how many were reset (caller commits)."""
    stale = (
        select(User.id, User.email_ad_consent_version)
        .where(
            User.email_ad_consent.is_(True),
            User.email_ad_consent_version.is_distinct_from(EMAIL_AD_CONSENT_WORDING_VERSION),
        )
        .cte("stale_consent")
    )
    rows = (
        await db.execute(
            update(User)
            .where(User.id == stale.c.id)
            .values(email_ad_consent=False, email_ad_consent_version=None)
            .returning(User.id, User.locale, stale.c.email_ad_consent_version)
        )
    ).all()
    if not rows:
        return 0
    await db.execute(
        insert(EmailAdConsentLog),
        [
            {
                "user_id": user_id,
                "granted": False,
                "wording_version": version or EMAIL_AD_CONSENT_WORDING_VERSION,
                "source": CONSENT_SOURCE_WORDING_CHANGE,
                "locale": locale,
            }
            for user_id, locale, version in rows
        ],
    )
    return len(rows)
