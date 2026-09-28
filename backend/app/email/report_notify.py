"""Admin notification email on first open report — mirrors contact.py's
internal-only mail pattern (sent via send_resend_email to
CONTACT_TO_ADDRESS). Markup lives in templates.py (REPORT_NOTIFY_* constants);
this module only assembles it. Sent only when a report transitions an event
from zero to one open report — see routers/reports.py.
"""

import html

from app.config import settings
from app.constants import (
    ADMIN_REPORTS_PATH,
    EVENTS_PATH,
)
from app.email.resend import send_resend_email
from app.email.templates import (
    REPORT_NOTIFY_COUNT_LINE,
    REPORT_NOTIFY_DETAIL_LINE,
    REPORT_NOTIFY_EVENT_LINE,
    REPORT_NOTIFY_ILLEGAL_LINE,
    REPORT_NOTIFY_REASON_LINE,
    REPORT_NOTIFY_REPORTER_LINE,
    REPORT_NOTIFY_REVIEW_LINE,
    REPORT_NOTIFY_SOURCE_LINE,
)
from app.models.models import Event


async def send_report_notification(
    event: Event,
    reason: str,
    detail: str | None,
    is_illegal_allegation: bool,
    report_count: int,
    reporter_email: str,
) -> None:
    event_href = f"{settings.FRONTEND_URL}{EVENTS_PATH}/{event.id}"
    console_href = f"{settings.FRONTEND_URL}{ADMIN_REPORTS_PATH}?report={event.id}"

    safe_title = html.escape(event.title_orig)
    safe_reason = html.escape(reason)
    safe_detail = html.escape(detail) if detail else None
    safe_reporter_email = html.escape(reporter_email)
    safe_source_url = html.escape(event.url) if event.url else None

    subject = f"New report — {' '.join(event.title_orig.split())}"

    html_lines = [
        REPORT_NOTIFY_EVENT_LINE.format(title=safe_title, href=event_href),
    ]
    if safe_source_url:
        html_lines.append(REPORT_NOTIFY_SOURCE_LINE.format(url=safe_source_url))
    html_lines.append(REPORT_NOTIFY_REASON_LINE.format(reason=safe_reason))
    if safe_detail:
        html_lines.append(REPORT_NOTIFY_DETAIL_LINE.format(detail=safe_detail))
    html_lines.append(REPORT_NOTIFY_COUNT_LINE.format(count=report_count))
    html_lines.append(
        REPORT_NOTIFY_ILLEGAL_LINE.format(is_illegal=is_illegal_allegation)
    )
    html_lines.append(REPORT_NOTIFY_REPORTER_LINE.format(email=safe_reporter_email))
    html_lines.append(REPORT_NOTIFY_REVIEW_LINE.format(href=console_href))
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

    await send_resend_email(
        {
            "to": [settings.CONTACT_TO_ADDRESS],
            "subject": subject,
            "html": html_body,
            "text": text_body,
        },
        log_label="report notification",
        log_ref=f"event_id={event.id}",
    )
