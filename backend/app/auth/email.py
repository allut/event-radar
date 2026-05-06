"""Magic-link email delivery via Resend API.

Falls back to log-only when RESEND_API_KEY is unset (dev / CI).
"""
import http
import logging

import httpx

from app.config import settings
from app.constants import (
    RESEND_ERROR_SNIPPET_LEN,
    RESEND_FROM_ADDRESS,
    RESEND_SEND_URL,
    RESEND_TIMEOUT_SECONDS,
)

log = logging.getLogger(__name__)


async def send_magic_link(to_email: str, magic_token: str) -> None:
    verify_url = f"{settings.FRONTEND_URL}/auth/verify?token={magic_token}"

    if not settings.RESEND_API_KEY:
        # Signed token is an auth credential — never log it at WARNING or above.
        log.warning("RESEND_API_KEY not set — magic link NOT sent to %s", to_email)
        log.debug("Dev-only magic link URL: %s", verify_url)
        return

    html = (
        "<p>Click the link below to sign in to Event Radar. "
        f"This link expires in {settings.MAGIC_LINK_TTL_MINUTES} minutes.</p>"
        f'<p><a href="{verify_url}">Sign in to Event Radar</a></p>'
        "<p>If you didn't request this, ignore this email.</p>"
    )

    async with httpx.AsyncClient(timeout=RESEND_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            RESEND_SEND_URL,
            headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
            json={
                "from": RESEND_FROM_ADDRESS,
                "to": [to_email],
                "subject": "Your Event Radar sign-in link",
                "html": html,
            },
        )

    if resp.status_code not in (http.HTTPStatus.OK, http.HTTPStatus.CREATED):
        log.error(
            "Resend API error sending to %s: %s %s",
            to_email,
            resp.status_code,
            resp.text[:RESEND_ERROR_SNIPPET_LEN],
        )
    else:
        log.info("Magic link sent to %s", to_email)
