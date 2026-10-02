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
from app.email.identity_link import (
    build_google_link_confirmation_html,
    build_google_link_confirmation_text,
    build_identity_linked_html,
    build_identity_linked_text,
)
from app.email.magic_link import build_magic_link_html, build_magic_link_text
from app.email.resend import send_resend_email
from app.i18n import t
from app.auth.utils import mask_email

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


async def send_google_link_confirmation(
    to_email: str,
    magic_token: str,
    locale: str = DEFAULT_USER_LOCALE,
    verify_path: str = AUTH_VERIFY_PATH,
) -> None:
    """Send the Google-link confirmation email (ADR 0002's non-authoritative-
    address gate, OWASP audit #3). Its own subject/wording — it says a Google
    account is being linked to ``to_email`` — so it can't be mistaken for the
    plain sign-in link; the link itself is the same verify URL shape."""
    verify_url = f"{settings.FRONTEND_URL}{verify_path}?token={magic_token}"

    if not settings.RESEND_API_KEY:
        log.warning(
            "RESEND_API_KEY not set — Google-link confirmation NOT sent to %s",
            mask_email(to_email),
        )
        if settings.APP_ENV == APP_ENV_DEVELOPMENT:
            log.debug("Dev-only Google-link confirmation URL: %s", verify_url)
        return

    ttl = settings.MAGIC_LINK_TTL_MINUTES
    await send_resend_email(
        {
            "reply_to": settings.CONTACT_TO_ADDRESS,
            "to": [to_email],
            "subject": t("email.google_link.subject", locale),
            "html": build_google_link_confirmation_html(verify_url, ttl, to_email, locale),
            "text": build_google_link_confirmation_text(verify_url, ttl, to_email, locale),
        },
        log_label="Google-link confirmation",
        log_ref=mask_email(to_email),
    )


async def send_identity_linked_notice(
    to_email: str, locale: str = DEFAULT_USER_LOCALE
) -> None:
    """Tell the account owner a Google sign-in was just linked (OWASP audit
    #3) — sent after every successful link so an unexpected one is visible.
    Best-effort: callers swallow failures, the link already exists."""
    if not settings.RESEND_API_KEY:
        log.warning(
            "RESEND_API_KEY not set — identity-linked notice NOT sent to %s",
            mask_email(to_email),
        )
        return

    await send_resend_email(
        {
            "reply_to": settings.CONTACT_TO_ADDRESS,
            "to": [to_email],
            "subject": t("email.identity_linked.subject", locale),
            "html": build_identity_linked_html(to_email, locale),
            "text": build_identity_linked_text(to_email, locale),
        },
        log_label="identity-linked notice",
        log_ref=mask_email(to_email),
    )
