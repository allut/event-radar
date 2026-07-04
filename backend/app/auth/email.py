"""Magic-link email delivery via Resend API.

Falls back to log-only when RESEND_API_KEY is unset (dev / CI).
"""

import logging

import httpx

from app.config import settings
from app.constants import (
    DEFAULT_USER_LOCALE,
    RESEND_ERROR_SNIPPET_LEN,
    RESEND_SEND_URL,
    RESEND_TIMEOUT_SECONDS,
)
from app.i18n import t, ti
from app.routers.utils import mask_email

log = logging.getLogger(__name__)


async def send_magic_link(
    to_email: str, magic_token: str, locale: str = DEFAULT_USER_LOCALE
) -> None:
    verify_url = f"{settings.FRONTEND_URL}/auth/verify?token={magic_token}"

    if not settings.RESEND_API_KEY:
        # Signed token is an auth credential — never log it at WARNING or above.
        log.warning(
            "RESEND_API_KEY not set — magic link NOT sent to %s", mask_email(to_email)
        )
        log.debug("Dev-only magic link URL: %s", verify_url)
        return

    subject = t("email.magic_link.subject", locale)
    html = ti(
        "email.magic_link.body",
        locale,
        ttl_minutes=settings.MAGIC_LINK_TTL_MINUTES,
        verify_url=verify_url,
    )

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
            },
        )

    if resp.status_code not in (httpx.codes.OK, httpx.codes.CREATED):
        log.error(
            "Resend API error sending to %s: %s %s",
            mask_email(to_email),
            resp.status_code,
            resp.text[:RESEND_ERROR_SNIPPET_LEN],
        )
    else:
        log.info("Magic link sent to %s", mask_email(to_email))
