"""Admin notices for Promotions (#612), sent to the contact address with a
deep link. Mirrors report_notify.py: a single attempt via send_resend_email."""

import html

import httpx

from app.config import settings
from app.constants.promotions import ADMIN_PROMOTIONS_PATH
from app.email.resend import send_resend_email
from app.email.templates import (
    PROMOTION_REQUEST_NOTIFY_HTML,
    PROMOTION_REQUEST_NOTIFY_SUBJECT,
    PROMOTION_REQUEST_NOTIFY_TEXT,
    PROMOTION_PAYMENT_NOTIFY_HTML,
    PROMOTION_PAYMENT_NOTIFY_SUBJECT,
    PROMOTION_PAYMENT_NOTIFY_TEXT,
    PROMOTION_RESTRICTION_NOTIFY_HTML,
    PROMOTION_RESTRICTION_NOTIFY_SUBJECT,
    PROMOTION_RESTRICTION_NOTIFY_TEXT,
)
from app.models.events import Event
from app.models.promotions import Promotion, PromotionRequest
from app.models.organizers import Organizer


async def send_restriction_flagged_notice(
    promotion: Promotion,
    event: Event,
    restriction: str,
    *,
    http_client: httpx.AsyncClient | None = None,
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
        http_client=http_client,
        log_label="promotion restriction notice",
        log_ref=f"promotion_id={promotion.id}",
    )


async def send_request_notice(
    request: PromotionRequest, event: Event, organizer: Organizer
) -> None:
    title = " ".join(event.title_orig.split())
    href = f"{settings.FRONTEND_URL}{ADMIN_PROMOTIONS_PATH}?request={request.id}"
    fields = {
        "title": title,
        "organizer": organizer.name or organizer.email,
        "advertiser": request.advertiser_legal_name,
        "start": request.start_date.isoformat(),
        "end": request.end_date.isoformat(),
        "href": href,
    }
    escaped = {k: html.escape(str(v)) for k, v in fields.items() if k != "href"}
    await send_resend_email(
        {
            "to": [settings.CONTACT_TO_ADDRESS],
            "subject": PROMOTION_REQUEST_NOTIFY_SUBJECT.format(title=title),
            "html": PROMOTION_REQUEST_NOTIFY_HTML.format(**escaped, href=href),
            "text": PROMOTION_REQUEST_NOTIFY_TEXT.format(**fields),
        },
        log_label="promotion request notice",
        log_ref=f"promotion_request_id={request.id}",
    )


async def send_payment_notice(headline: str, detail: str, promotion_id: int | None) -> None:
    """Admin notice for a paid checkout, a refunded late payment or a dispute.
    `promotion_id` is None when a dispute matches no Promotion."""
    path = f"{ADMIN_PROMOTIONS_PATH}/{promotion_id}" if promotion_id is not None else ADMIN_PROMOTIONS_PATH
    href = f"{settings.FRONTEND_URL}{path}"
    await send_resend_email(
        {
            "to": [settings.CONTACT_TO_ADDRESS],
            "subject": PROMOTION_PAYMENT_NOTIFY_SUBJECT.format(headline=headline),
            "html": PROMOTION_PAYMENT_NOTIFY_HTML.format(
                headline=html.escape(headline), detail=html.escape(detail), href=href
            ),
            "text": PROMOTION_PAYMENT_NOTIFY_TEXT.format(headline=headline, detail=detail, href=href),
        },
        log_label="promotion payment notice",
        log_ref=f"promotion_id={promotion_id}",
    )
