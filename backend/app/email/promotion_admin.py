"""Admin notices for Promotions (#612), sent to the contact address with a
deep link. Mirrors report_notify.py: a single attempt via send_resend_email."""

import html

from app.config import settings
from app.constants.promotions import ADMIN_PROMOTIONS_PATH
from app.email.resend import send_resend_email
from app.email.templates import (
    PROMOTION_RESTRICTION_NOTIFY_HTML,
    PROMOTION_RESTRICTION_NOTIFY_SUBJECT,
    PROMOTION_RESTRICTION_NOTIFY_TEXT,
)
from app.models.models import Event, Promotion


async def send_restriction_flagged_notice(
    promotion: Promotion, event: Event, restriction: str
) -> None:
    title = " ".join(event.title_orig.split())
    href = f"{settings.FRONTEND_URL}{ADMIN_PROMOTIONS_PATH}/{promotion.id}"
    fields = {
        "title": title,
        "restriction": restriction,
        "promotion_id": promotion.id,
        "start": promotion.start_date.isoformat(),
        "end": promotion.end_date.isoformat(),
        "href": href,
    }
    await send_resend_email(
        {
            "to": [settings.CONTACT_TO_ADDRESS],
            "subject": PROMOTION_RESTRICTION_NOTIFY_SUBJECT.format(
                restriction=restriction, title=title
            ),
            "html": PROMOTION_RESTRICTION_NOTIFY_HTML.format(
                **{**fields, "title": html.escape(title)}
            ),
            "text": PROMOTION_RESTRICTION_NOTIFY_TEXT.format(**fields),
        },
        log_label="promotion restriction notice",
        log_ref=f"promotion_id={promotion.id}",
    )
