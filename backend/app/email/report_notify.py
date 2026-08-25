"""Admin notification email on first open report — mirrors contact.py's
Resend-with-log-fallback pattern (internal-only mail, no styles/templates/
assembly split, sent to CONTACT_TO_ADDRESS). Sent only when a report
transitions an event from zero to one open report — see routers/reports.py.
"""

import html
import logging

import httpx

from app.config import settings
from app.constants import (
    LOG_EVENT_EMAIL_SEND_FAILED,
    RESEND_ERROR_SNIPPET_LEN,
    RESEND_SEND_URL,
    RESEND_TIMEOUT_SECONDS,
)
from app.models.models import Event

log = logging.getLogger(__name__)


async def send_report_notification(
    event: Event,
    reason: str,
    detail: str | None,
    is_illegal_allegation: bool,
    report_count: int,
    reporter_email: str,
) -> None:
    if not settings.RESEND_API_KEY:
        log.warning(
            "RESEND_API_KEY not set — report notification NOT sent (event_id=%s)",
            event.id,
        )
        return

    event_href = f"{settings.FRONTEND_URL}/events/{event.id}"
    console_href = f"{settings.FRONTEND_URL}/admin/reports?report={event.id}"

    safe_title = html.escape(event.title_orig)
    safe_reason = html.escape(reason)
    safe_detail = html.escape(detail) if detail else None
    safe_reporter_email = html.escape(reporter_email)
    safe_source_url = html.escape(event.url) if event.url else None

    subject = f"New report — {' '.join(event.title_orig.split())}"

    html_lines = [
        f"<p><strong>Event:</strong> {safe_title} (<a href='{event_href}'>{event_href}</a>)</p>",
    ]
    if safe_source_url:
        html_lines.append(
            f"<p><strong>Source:</strong> <a href='{safe_source_url}'>{safe_source_url}</a></p>"
        )
    html_lines.append(f"<p><strong>Reason(s):</strong> {safe_reason}</p>")
    if safe_detail:
        html_lines.append(f"<p><strong>Detail:</strong> {safe_detail}</p>")
    html_lines.append(f"<p><strong>Report count:</strong> {report_count}</p>")
    html_lines.append(
        f"<p><strong>Illegal allegation:</strong> {is_illegal_allegation}</p>"
    )
    html_lines.append(f"<p><strong>Reporter:</strong> {safe_reporter_email}</p>")
    html_lines.append(
        f"<p><a href='{console_href}'>Review in the admin console</a></p>"
    )
    html_body = "".join(html_lines)

    text_body = (
        f"Event: {event.title_orig} ({event_href})\n"
        f"Source: {event.url or '-'}\n"
        f"Reason(s): {reason}\n"
        f"Detail: {detail or '-'}\n"
        f"Report count: {report_count}\n"
        f"Illegal allegation: {is_illegal_allegation}\n"
        f"Reporter: {reporter_email}\n\n"
        f"Review in the admin console:\n{console_href}\n"
    )

    async with httpx.AsyncClient(timeout=RESEND_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            RESEND_SEND_URL,
            headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
            json={
                "from": settings.RESEND_FROM_ADDRESS,
                "to": [settings.CONTACT_TO_ADDRESS],
                "subject": subject,
                "html": html_body,
                "text": text_body,
            },
        )

    if resp.status_code not in (httpx.codes.OK, httpx.codes.CREATED):
        log.error(
            "Resend API error sending report notification (event_id=%s): %s %s",
            event.id,
            resp.status_code,
            resp.text[:RESEND_ERROR_SNIPPET_LEN],
            extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
        )
    else:
        log.info("Report notification sent (event_id=%s)", event.id)
