"""Magic-link email delivery via Resend API.

Falls back to log-only when RESEND_API_KEY is unset (dev / CI).
"""

import logging

import httpx

from app.config import settings
from app.constants import (
    DEFAULT_USER_LOCALE,
    LOG_EVENT_EMAIL_SEND_FAILED,
    RESEND_ERROR_SNIPPET_LEN,
    RESEND_SEND_URL,
    RESEND_TIMEOUT_SECONDS,
)
from app.email.magic_link import build_magic_link_html, build_magic_link_text
from app.i18n import t
from app.routers.utils import mask_email

log = logging.getLogger(__name__)


async def send_magic_link(
    to_email: str,
    magic_token: str,
    locale: str = DEFAULT_USER_LOCALE,
    verify_path: str = "/auth/verify",
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
        log.debug("Dev-only magic link URL: %s", verify_url)
        return

    subject = t("email.magic_link.subject", locale)
    html = build_magic_link_html(verify_url, settings.MAGIC_LINK_TTL_MINUTES, locale)
    text = build_magic_link_text(verify_url, settings.MAGIC_LINK_TTL_MINUTES, locale)

    # Not routed through the shared retrying http_post: this call is awaited
    # synchronously inside the rate-limited, user-facing POST /auth/request-link
    # endpoint — a 5-attempt exponential backoff on a Resend hiccup would stall
    # that request up to ~150s instead of failing fast (errors are already
    # swallowed by the caller, which always returns 200 regardless).
    async with httpx.AsyncClient(timeout=RESEND_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            RESEND_SEND_URL,
            headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
            json={
                "from": settings.RESEND_FROM_ADDRESS,
                "to": [to_email],
                "subject": subject,
                "html": html,
                "text": text,
            },
        )

    if resp.status_code not in (httpx.codes.OK, httpx.codes.CREATED):
        log.error(
            "Resend API error sending to %s: %s %s",
            mask_email(to_email),
            resp.status_code,
            resp.text[:RESEND_ERROR_SNIPPET_LEN],
            extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
        )
    else:
        log.info("Magic link sent to %s", mask_email(to_email))
