"""Admin notification email on first open report — mirrors contact.py's
internal-only mail pattern (sent via send_resend_email to
CONTACT_TO_ADDRESS). Markup lives in templates.py (REPORT_NOTIFY_* constants);
this module only assembles it. Sent only when a report transitions an event
from zero to one open report — see routers/reports.py.
"""

import html

from app.config import settings
from app.constants.core import ADMIN_REPORTS_PATH, EVENTS_PATH
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
    REPORT_NOTIFY_SUBJECT,
    REPORT_NOTIFY_TEXT_BODY,
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

    subject = REPORT_NOTIFY_SUBJECT.format(
        title=" ".join(event.title_orig.split())
    )

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

    text_body = REPORT_NOTIFY_TEXT_BODY.format(
        title=event.title_orig,
        event_href=event_href,
        source=event.url or "-",
        reason=reason,
        detail=detail or "-",
        count=report_count,
        is_illegal=is_illegal_allegation,
        reporter_email=reporter_email,
        console_href=console_href,
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
