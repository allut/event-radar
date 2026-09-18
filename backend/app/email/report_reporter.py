"""Reporter-outcome email — fires once a reporter's report is resolved
(manual admin resolve/takedown, or the auto-resolve-on-cancellation cascade).
Branded/i18n pattern (EMAIL_DOCUMENT shell + styles.py/templates.py, t()/ti()),
unlike contact.py's internal-only exemption — this goes to an external user.
Sent by app.routers.utils.resolve_open_reports, the single shared helper
every resolve/takedown/cascade path funnels through (see issue #125), so the
send is centralized there rather than duplicated per caller.
"""

from __future__ import annotations

import html as html_lib
import logging

import httpx

from app.config import settings
from app.constants import (
    AUTHORIZATION_HEADER,
    BEARER_PREFIX,
    EVENTS_PATH,
    LOG_EVENT_EMAIL_SEND_FAILED,
    RESEND_ERROR_SNIPPET_LEN,
    RESEND_SEND_URL,
    RESEND_TIMEOUT_SECONDS,
)
from app.email.styles import get_email_styles
from app.email.templates import (
    EMAIL_DOCUMENT,
    EMAIL_FOOTER_BRAND,
    REPORT_OUTCOME_BODY,
    REPORT_OUTCOME_HEADER,
)
from app.i18n import t, ti
from app.models.models import Event

log = logging.getLogger(__name__)


def build_report_outcome_html(
    event: Event,
    resolution_note: str,
    locale: str,
) -> str:
    s = get_email_styles()
    safe_event_url = html_lib.escape(
        f"{settings.FRONTEND_URL}{EVENTS_PATH}/{event.id}", quote=True
    )
    note = resolution_note.strip() or t("email.report_outcome.fallback_note", locale)

    header_html = REPORT_OUTCOME_HEADER.format(
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
    event_url = f"{settings.FRONTEND_URL}{EVENTS_PATH}/{event.id}"
    return f"{intro}\n\n{note}\n\n{event_url}"


def report_outcome_http_client() -> httpx.AsyncClient:
    """Build an ``httpx.AsyncClient`` for ``send_report_resolution_emails`` to
    open once and reuse across its whole REPORT_EMAIL_SEND_CONCURRENCY-bounded
    fan-out, instead of a fresh connection pool + TLS handshake per reporter
    (Big-O audit #5, item 2.7 — mirrors ``digest_http_client()``)."""
    return httpx.AsyncClient(timeout=RESEND_TIMEOUT_SECONDS)


async def send_report_outcome_email(
    to_email: str,
    event: Event,
    resolution_note: str,
    locale: str,
    http_client: httpx.AsyncClient | None = None,
) -> None:
    if not settings.RESEND_API_KEY:
        log.warning(
            "RESEND_API_KEY not set — report outcome email NOT sent (event_id=%s)",
            event.id,
        )
        return

    subject = t("email.report_outcome.subject", locale)
    html_body = build_report_outcome_html(event, resolution_note, locale)
    text_body = build_report_outcome_text(event, resolution_note, locale)

    payload = {
        "from": settings.RESEND_FROM_ADDRESS,
        "to": [to_email],
        "reply_to": settings.CONTACT_TO_ADDRESS,
        "subject": subject,
        "html": html_body,
        "text": text_body,
    }
    headers = {AUTHORIZATION_HEADER: f"{BEARER_PREFIX}{settings.RESEND_API_KEY}"}
    if http_client is not None:
        resp = await http_client.post(RESEND_SEND_URL, headers=headers, json=payload)
    else:
        async with httpx.AsyncClient(timeout=RESEND_TIMEOUT_SECONDS) as client:
            resp = await client.post(RESEND_SEND_URL, headers=headers, json=payload)

    if resp.status_code not in (httpx.codes.OK, httpx.codes.CREATED):
        log.error(
            "Resend API error sending report outcome email (event_id=%s): %s %s",
            event.id,
            resp.status_code,
            resp.text[:RESEND_ERROR_SNIPPET_LEN],
            extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
        )
    else:
        log.info("Report outcome email sent (event_id=%s)", event.id)
