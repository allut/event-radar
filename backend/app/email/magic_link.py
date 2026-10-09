"""Magic-link sign-in email — HTML/text build (styling matches the digest)."""

from __future__ import annotations

import html as html_lib

from app.email.brand import brand_mark_html
from app.email.styles import get_email_styles
from app.email.templates import (
    EMAIL_DOCUMENT,
    EMAIL_FOOTER_BRAND,
    MAGIC_LINK_BODY,
    MAGIC_LINK_HEADER,
)
from app.i18n import t, ti


def build_magic_link_html(
    verify_url: str,
    ttl_minutes: int,
    locale: str,
) -> str:
    s = get_email_styles()
    safe_verify_url = html_lib.escape(verify_url, quote=True)

    header_html = MAGIC_LINK_HEADER.format(
        brand_mark_html=brand_mark_html(s),
        s_eyebrow=s.s_eyebrow,
        s_h1=s.s_h1,
        heading=t("email.magic_link.heading", locale),
    )
    content_html = MAGIC_LINK_BODY.format(
        s_body_text=s.s_body_text,
        intro=ti("email.magic_link.intro", locale, ttl_minutes=ttl_minutes),
        s_feed_btn_wrap=s.s_feed_btn_wrap,
        verify_url=safe_verify_url,
        s_feed_btn=s.s_feed_btn,
        cta_label=t("email.magic_link.cta", locale),
        s_muted_note=s.s_muted_note,
        ignore_note=t("email.magic_link.ignore_note", locale),
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


def build_magic_link_text(verify_url: str, ttl_minutes: int, locale: str) -> str:
    intro = ti("email.magic_link.intro", locale, ttl_minutes=ttl_minutes)
    ignore_note = t("email.magic_link.ignore_note", locale)
    return f"{intro}\n\n{verify_url}\n\n{ignore_note}"
