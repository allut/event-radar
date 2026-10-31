"""Reporter-outcome email — fires once a reporter's report is resolved
(manual admin resolve/takedown, or the auto-resolve-on-cancellation cascade).
Branded/i18n pattern (EMAIL_DOCUMENT shell + styles.py/templates.py, t()/ti()),
this goes to an external user.
Sent by app.events.cancellation.resolve_open_reports, the single shared helper
every resolve/takedown/cascade path funnels through (see issue #125), so the
send is centralized there rather than duplicated per caller.
"""

from __future__ import annotations

import html as html_lib

import httpx

from app.config import settings
from app.constants.core import EVENTS_PATH
from app.email.links import frontend_url
from app.email.resend import send_resend_email
from app.email.brand import brand_mark_html
from app.email.styles import get_email_styles
from app.email.templates import (
    EMAIL_DOCUMENT,
    EMAIL_FOOTER_BRAND,
    REPORT_OUTCOME_BODY,
    REPORT_OUTCOME_HEADER,
)
from app.i18n import t, ti
from app.models.events import Event


def build_report_outcome_html(
    event: Event,
    resolution_note: str,
    locale: str,
) -> str:
    s = get_email_styles()
    safe_event_url = html_lib.escape(
        frontend_url(f"{EVENTS_PATH}/{event.id}", locale), quote=True
    )
    note = resolution_note.strip() or t("email.report_outcome.fallback_note", locale)

    header_html = REPORT_OUTCOME_HEADER.format(
        brand_mark_html=brand_mark_html(s),
        s_eyebrow=s.s_eyebrow,
        s_h1=s.s_h1,
        heading=t("email.report_outcome.heading", locale),
    )
    content_html = REPORT_OUTCOME_BODY.format(
        s_body_text=s.s_body_text,
        intro=html_lib.escape(
            ti("email.report_outcome.intro", locale, event_title=event.title_orig)
        ),
        note=html_lib.escape(note),
        s_feed_btn_wrap=s.s_feed_btn_wrap,
        event_url=safe_event_url,
        s_feed_btn=s.s_feed_btn,
        cta_label=t("email.report_outcome.cta", locale),
    )

    return EMAIL_DOCUMENT.format(
        css=s.css,
        color_scheme=s.color_scheme,
        s_page=s.s_page,
        s_container=s.s_container,
        s_header_pad=s.s_header_pad,
        header_html=header_html,
        s_content_pad=s.s_content_pad,
        content_html=content_html,
        s_footer=s.s_footer,
        footer_html=EMAIL_FOOTER_BRAND,
    )


def build_report_outcome_text(event: Event, resolution_note: str, locale: str) -> str:
    note = resolution_note.strip() or t("email.report_outcome.fallback_note", locale)
    intro = ti("email.report_outcome.intro", locale, event_title=event.title_orig)
    event_url = frontend_url(f"{EVENTS_PATH}/{event.id}", locale)
    return f"{intro}\n\n{note}\n\n{event_url}"


async def send_report_outcome_email(
    to_email: str,
    event: Event,
    resolution_note: str,
    locale: str,
    http_client: httpx.AsyncClient | None = None,
) -> None:
    subject = t("email.report_outcome.subject", locale)
    html_body = build_report_outcome_html(event, resolution_note, locale)
    text_body = build_report_outcome_text(event, resolution_note, locale)

    await send_resend_email(
        {
            "to": [to_email],
            "reply_to": settings.CONTACT_TO_ADDRESS,
            "subject": subject,
            "html": html_body,
            "text": text_body,
        },
        http_client=http_client,
        log_label="report outcome email",
        log_ref=f"event_id={event.id}",
    )
