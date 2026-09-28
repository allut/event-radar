"""Magic-link email delivery via Resend API.

Falls back to log-only when RESEND_API_KEY is unset (dev / CI).
"""

import logging

from app.config import settings
from app.constants import (
    APP_ENV_DEVELOPMENT,
    AUTH_VERIFY_PATH,
    DEFAULT_USER_LOCALE,
)
from app.email.magic_link import build_magic_link_html, build_magic_link_text
from app.email.resend import send_resend_email
from app.i18n import t
from app.routers.utils import mask_email

log = logging.getLogger(__name__)


async def send_magic_link(
    to_email: str,
    magic_token: str,
    locale: str = DEFAULT_USER_LOCALE,
    verify_path: str = AUTH_VERIFY_PATH,
) -> None:
    """Send a magic-link sign-in email. ``verify_path`` lets the organizer auth
    flow (routers/organizer_auth.py) point the link at ``/organizer/verify``
    instead of the consumer ``/auth/verify`` route — the email wording/HTML is
    otherwise identical for v1 (see app/email/magic_link.py)."""
    verify_url = f"{settings.FRONTEND_URL}{verify_path}?token={magic_token}"

    if not settings.RESEND_API_KEY:
        # Signed token is an auth credential — never log it at WARNING or above.
        log.warning(
            "RESEND_API_KEY not set — magic link NOT sent to %s", mask_email(to_email)
        )
        # Gated on APP_ENV, not just log level — a production deployment with
        # RESEND_API_KEY unset/rotated out plus LOG_LEVEL=DEBUG would otherwise
        # ship this live auth credential to the Axiom drain (configure_logging
        # attaches the shipping QueueHandler with no level floor).
        if settings.APP_ENV == APP_ENV_DEVELOPMENT:
            log.debug("Dev-only magic link URL: %s", verify_url)
        return

    subject = t("email.magic_link.subject", locale)
    html = build_magic_link_html(
        verify_url, settings.MAGIC_LINK_TTL_MINUTES, locale
    )
    text = build_magic_link_text(verify_url, settings.MAGIC_LINK_TTL_MINUTES, locale)

    await send_resend_email(
        {
            "reply_to": settings.CONTACT_TO_ADDRESS,
            "to": [to_email],
            "subject": subject,
            "html": html,
            "text": text,
        },
        log_label="magic link",
        log_ref=mask_email(to_email),
    )
