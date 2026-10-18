"""Daily Five digest subscription — the one place the opt-in is written."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.email import CONSENT_SOURCE_DIGEST_UNSUBSCRIBE
from app.email.consent import withdraw_ad_consent
from app.models.models import User


def set_digest_subscription(user: User, enabled: bool, db: AsyncSession) -> None:
    """Turn the user's Daily Five digest on or off (caller commits). Turning it
    off withdraws Email ad consent; turning it on never restores it."""
    user.email_digest_opt_in = enabled
    if not enabled:
        withdraw_ad_consent(user, db, CONSENT_SOURCE_DIGEST_UNSUBSCRIBE)
