"""Contact-form email delivery via Resend.

Falls back to log-only when RESEND_API_KEY is unset (dev / CI). Internal-only
mail (owner inbox, not user-facing branding) — plain markup, no EMAIL_DOCUMENT
shell needed.
"""

import html
import logging

import httpx

from app.config import settings
from app.constants import (
    AUTHORIZATION_HEADER,
    BEARER_PREFIX,
    LOG_EVENT_EMAIL_SEND_FAILED,
    RESEND_ERROR_SNIPPET_LEN,
    RESEND_SEND_URL,
    RESEND_TIMEOUT_SECONDS,
)
from app.routers.utils import mask_email

log = logging.getLogger(__name__)


async def send_contact_message(name: str, email: str, message: str) -> None:
    if not settings.RESEND_API_KEY:
        log.warning(
            "RESEND_API_KEY not set — contact message NOT sent (from %s)",
            mask_email(email),
        )
        return

    # Collapse embedded newlines so a multi-line name can't split the subject.
    subject = f"Contact form — {' '.join(name.split())}"
    safe_name = html.escape(name)
    safe_email = html.escape(email)
    safe_message = html.escape(message).replace("\n", "<br>")
    html_body = (
        f"<p><strong>From:</strong> {safe_name} ({safe_email})</p><p>{safe_message}</p>"
    )
    text_body = f"From: {name} ({email})\n\n{message}"

    # Not routed through the shared retrying http_post: like
    # app/auth/email.py::send_magic_link, this call is awaited synchronously
    # inside the rate-limited, user-facing POST /contact request — a 5-attempt
    # exponential backoff on a Resend hiccup would stall that request up to
    # ~150s instead of failing fast (the caller, routers/contact.py, already
    # swallows the error and always returns 200 regardless).
    async with httpx.AsyncClient(timeout=RESEND_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            RESEND_SEND_URL,
            headers={AUTHORIZATION_HEADER: f"{BEARER_PREFIX}{settings.RESEND_API_KEY}"},
            json={
                "from": settings.RESEND_FROM_ADDRESS,
                "to": [settings.CONTACT_TO_ADDRESS],
                "reply_to": email,
                "subject": subject,
                "html": html_body,
                "text": text_body,
            },
        )

    if resp.status_code not in (httpx.codes.OK, httpx.codes.CREATED):
        log.error(
            "Resend API error sending contact message from %s: %s %s",
            mask_email(email),
            resp.status_code,
            resp.text[:RESEND_ERROR_SNIPPET_LEN],
            extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
        )
    else:
        log.info("Contact message sent from %s", mask_email(email))
