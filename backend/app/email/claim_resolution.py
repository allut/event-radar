"""Claim resolution-outcome emails (#421) — one per lifecycle transition an
organizer's claim can land on: granted, declined (admin), expired
(automated-mechanism inactivity sweep), self-cancelled. Branded/i18n pattern
(EMAIL_DOCUMENT shell + styles.py/templates.py, t()/ti()), mirroring
app/email/report_reporter.py. Revoke is deliberately not covered here — see
app/routers/admin.py::admin_revoke_claim's docstring: it's a distinct action
from decline and the spec only calls for an email on grant/decline/expiry.
"""

from __future__ import annotations

import html as html_lib

import httpx

from app.config import settings
from app.constants import (
    CLAIM_EXPIRY_DAYS,
    ORGANIZER_DASHBOARD_PATH,
)
from app.email.links import frontend_url
from app.email.resend import send_resend_email
from app.email.styles import get_email_styles
from app.email.templates import (
    CLAIM_RESOLUTION_BODY,
    CLAIM_RESOLUTION_HEADER,
    EMAIL_DOCUMENT,
    EMAIL_FOOTER_BRAND,
)
from app.i18n import t, ti
from app.auth.utils import mask_email


def _target_label(event_title: str | None, locale: str) -> str:
    return event_title or t("email.claim_resolution.fallback_target", locale)


def _prepare_granted(event_title: str | None, note: str, locale: str) -> tuple[str, str]:
    label = _target_label(event_title, locale)
    intro = ti("email.claim_granted.intro", locale, event_title=label)
    return intro, note.strip() or t("email.claim_granted.fallback_note", locale)


def _prepare_declined(event_title: str | None, note: str, locale: str) -> tuple[str, str]:
    label = _target_label(event_title, locale)
    intro = ti("email.claim_declined.intro", locale, event_title=label)
    return intro, note.strip() or t("email.claim_declined.fallback_note", locale)


def _prepare_expired(event_title: str | None, locale: str, days: int) -> tuple[str, str]:
    label = _target_label(event_title, locale)
    intro = ti("email.claim_expired.intro", locale, event_title=label, days=days)
    return intro, t("email.claim_expired.fallback_note", locale)


def _prepare_self_cancelled(event_title: str | None, locale: str) -> tuple[str, str]:
    label = _target_label(event_title, locale)
    intro = ti("email.claim_self_cancelled.intro", locale, event_title=label)
    return intro, t("email.claim_self_cancelled.fallback_note", locale)


def _build_html(*, subject_key: str, intro: str, note: str, locale: str) -> str:
    s = get_email_styles()
    dashboard_url = html_lib.escape(
        frontend_url(ORGANIZER_DASHBOARD_PATH, locale), quote=True
    )
    header_html = CLAIM_RESOLUTION_HEADER.format(
        s_eyebrow=s.s_eyebrow,
        s_h1=s.s_h1,
        heading=t(f"{subject_key}.heading", locale),
    )
    content_html = CLAIM_RESOLUTION_BODY.format(
        s_body_text=s.s_body_text,
        intro=html_lib.escape(intro),
        note=html_lib.escape(note),
        s_feed_btn_wrap=s.s_feed_btn_wrap,
        dashboard_url=dashboard_url,
        s_feed_btn=s.s_feed_btn,
        cta_label=t(f"{subject_key}.cta", locale),
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


def _build_text(*, intro: str, note: str) -> str:
    return f"{intro}\n\n{note}"


def build_claim_granted_html(event_title: str | None, note: str, locale: str) -> str:
    intro, resolved_note = _prepare_granted(event_title, note, locale)
    return _build_html(
        subject_key="email.claim_granted", intro=intro, note=resolved_note, locale=locale
    )


def build_claim_declined_html(event_title: str | None, note: str, locale: str) -> str:
    intro, resolved_note = _prepare_declined(event_title, note, locale)
    return _build_html(
        subject_key="email.claim_declined", intro=intro, note=resolved_note, locale=locale
    )


def build_claim_expired_html(
    event_title: str | None, locale: str, days: int = CLAIM_EXPIRY_DAYS
) -> str:
    intro, note = _prepare_expired(event_title, locale, days)
    return _build_html(subject_key="email.claim_expired", intro=intro, note=note, locale=locale)


def build_claim_self_cancelled_html(event_title: str | None, locale: str) -> str:
    intro, note = _prepare_self_cancelled(event_title, locale)
    return _build_html(
        subject_key="email.claim_self_cancelled", intro=intro, note=note, locale=locale
    )


async def _send(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str,
    http_client: httpx.AsyncClient | None,
    log_label: str,
) -> None:
    await send_resend_email(
        {
            "to": [to_email],
            "reply_to": settings.CONTACT_TO_ADDRESS,
            "subject": subject,
            "html": html_body,
            "text": text_body,
        },
        http_client=http_client,
        log_label=f"{log_label} email",
        log_ref=f"to={mask_email(to_email)}",
    )


async def send_claim_granted_email(
    to_email: str,
    event_title: str | None,
    note: str,
    locale: str,
    http_client: httpx.AsyncClient | None = None,
) -> None:
    intro, resolved_note = _prepare_granted(event_title, note, locale)
    html_body = _build_html(
        subject_key="email.claim_granted", intro=intro, note=resolved_note, locale=locale
    )
    text_body = _build_text(intro=intro, note=resolved_note)
    subject = t("email.claim_granted.subject", locale)
    await _send(to_email, subject, html_body, text_body, http_client, "claim-granted")


async def send_claim_declined_email(
    to_email: str,
    event_title: str | None,
    note: str,
    locale: str,
    http_client: httpx.AsyncClient | None = None,
) -> None:
    intro, resolved_note = _prepare_declined(event_title, note, locale)
    html_body = _build_html(
        subject_key="email.claim_declined", intro=intro, note=resolved_note, locale=locale
    )
    text_body = _build_text(intro=intro, note=resolved_note)
    subject = t("email.claim_declined.subject", locale)
    await _send(to_email, subject, html_body, text_body, http_client, "claim-declined")


async def send_claim_expired_email(
    to_email: str,
    event_title: str | None,
    locale: str,
    http_client: httpx.AsyncClient | None = None,
    days: int = CLAIM_EXPIRY_DAYS,
) -> None:
    """`days` is the window that actually fired — CLAIM_EXPIRY_DAYS for an
    automated-mechanism claim, or the caller's CLAIM_ADMIN_REVIEW_EXPIRY_DAYS
    for an admin_review/piletilevi_mailbox one (#430); defaults to
    CLAIM_EXPIRY_DAYS so existing non-expiry-sweep callers, if any, need no
    change."""
    intro, note = _prepare_expired(event_title, locale, days)
    html_body = _build_html(
        subject_key="email.claim_expired", intro=intro, note=note, locale=locale
    )
    text_body = _build_text(intro=intro, note=note)
    subject = t("email.claim_expired.subject", locale)
    await _send(to_email, subject, html_body, text_body, http_client, "claim-expired")


async def send_claim_self_cancelled_email(
    to_email: str,
    event_title: str | None,
    locale: str,
    http_client: httpx.AsyncClient | None = None,
) -> None:
    intro, note = _prepare_self_cancelled(event_title, locale)
    html_body = _build_html(
        subject_key="email.claim_self_cancelled", intro=intro, note=note, locale=locale
    )
    text_body = _build_text(intro=intro, note=note)
    subject = t("email.claim_self_cancelled.subject", locale)
    await _send(to_email, subject, html_body, text_body, http_client, "claim-self-cancelled")
