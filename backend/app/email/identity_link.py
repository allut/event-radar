"""Google sign-in identity-link emails (ADR 0002, OWASP audit #3) — HTML/text.

Two emails, both distinct from the plain magic-link sign-in email so a
recipient can tell them apart:
- the *confirmation* email sent when Google isn't authoritative for the
  address (names the address and says a Google account is being linked);
- the *notice* sent whenever a Google identity is actually linked to an
  existing account.
"""

from __future__ import annotations

import html as html_lib

from app.email.brand import brand_mark_html
from app.email.styles import get_email_styles
from app.email.templates import (
    ACCOUNT_NOTICE_BODY,
    EMAIL_DOCUMENT,
    EMAIL_FOOTER_BRAND,
    MAGIC_LINK_BODY,
    MAGIC_LINK_HEADER,
)
from app.i18n import t, ti


def _document(header_html: str, content_html: str) -> str:
    s = get_email_styles()
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


def _header(heading: str) -> str:
    s = get_email_styles()
    return MAGIC_LINK_HEADER.format(
        brand_mark_html=brand_mark_html(s),
        s_eyebrow=s.s_eyebrow,
        s_h1=s.s_h1,
        heading=html_lib.escape(heading),
    )


def build_google_link_confirmation_html(
    verify_url: str, ttl_minutes: int, email: str, locale: str
) -> str:
    s = get_email_styles()
    content_html = MAGIC_LINK_BODY.format(
        s_body_text=s.s_body_text,
        intro=html_lib.escape(
            ti("email.google_link.intro", locale, email=email, ttl_minutes=ttl_minutes)
        ),
        s_feed_btn_wrap=s.s_feed_btn_wrap,
        verify_url=html_lib.escape(verify_url, quote=True),
        s_feed_btn=s.s_feed_btn,
        cta_label=t("email.google_link.cta", locale),
        s_muted_note=s.s_muted_note,
        ignore_note=t("email.google_link.ignore_note", locale),
    )
    return _document(_header(t("email.google_link.heading", locale)), content_html)


def build_google_link_confirmation_text(
    verify_url: str, ttl_minutes: int, email: str, locale: str
) -> str:
    intro = ti("email.google_link.intro", locale, email=email, ttl_minutes=ttl_minutes)
    ignore_note = t("email.google_link.ignore_note", locale)
    return f"{intro}\n\n{verify_url}\n\n{ignore_note}"


def build_identity_linked_html(email: str, locale: str) -> str:
    s = get_email_styles()
    content_html = ACCOUNT_NOTICE_BODY.format(
        s_body_text=s.s_body_text,
        intro=html_lib.escape(ti("email.identity_linked.intro", locale, email=email)),
        s_muted_note=s.s_muted_note,
        note=t("email.identity_linked.note", locale),
    )
    return _document(_header(t("email.identity_linked.heading", locale)), content_html)


def build_identity_linked_text(email: str, locale: str) -> str:
    intro = ti("email.identity_linked.intro", locale, email=email)
    note = t("email.identity_linked.note", locale)
    return f"{intro}\n\n{note}"
