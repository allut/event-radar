"""Contact-form email delivery via Resend.

Falls back to log-only when RESEND_API_KEY is unset (dev / CI). Internal-only
mail (owner inbox, not user-facing branding) — plain markup (CONTACT_* in
templates.py), no EMAIL_DOCUMENT shell needed.
"""

import html

from app.config import settings
from app.email.resend import send_resend_email
from app.email.templates import CONTACT_HTML_BODY, CONTACT_TEXT_BODY
from app.routers.utils import mask_email


async def send_contact_message(name: str, email: str, message: str) -> None:
    # Collapse embedded newlines so a multi-line name can't split the subject.
    subject = f"Contact form — {' '.join(name.split())}"
    html_body = CONTACT_HTML_BODY.format(
        name=html.escape(name),
        email=html.escape(email),
        message=html.escape(message).replace("\n", "<br>"),
    )
    text_body = CONTACT_TEXT_BODY.format(name=name, email=email, message=message)

    await send_resend_email(
        {
            "to": [settings.CONTACT_TO_ADDRESS],
            "reply_to": email,
            "subject": subject,
            "html": html_body,
            "text": text_body,
        },
        log_label="contact message",
        log_ref=f"from {mask_email(email)}",
    )
