"""Magic-link sign-in email — HTML/text build (styling matches the digest)."""

from __future__ import annotations

import html as html_lib

from app.email import styles
from app.email.styles import EMAIL_CSS
from app.email.templates import (
    EMAIL_DOCUMENT,
    EMAIL_FOOTER_BRAND,
    MAGIC_LINK_BODY,
    MAGIC_LINK_HEADER,
)
from app.i18n import t, ti


def build_magic_link_html(verify_url: str, ttl_minutes: int, locale: str) -> str:
    safe_verify_url = html_lib.escape(verify_url, quote=True)

    header_html = MAGIC_LINK_HEADER.format(
        s_eyebrow=styles.S_EYEBROW,
        s_h1=styles.S_H1,
        heading=t("email.magic_link.heading", locale),
    )
    content_html = MAGIC_LINK_BODY.format(
        s_body_text=styles.S_BODY_TEXT,
        intro=ti("email.magic_link.intro", locale, ttl_minutes=ttl_minutes),
        s_feed_btn_wrap=styles.S_FEED_BTN_WRAP,
        verify_url=safe_verify_url,
        s_feed_btn=styles.S_FEED_BTN,
        cta_label=t("email.magic_link.cta", locale),
        s_muted_note=styles.S_MUTED_NOTE,
        ignore_note=t("email.magic_link.ignore_note", locale),
    )

    return EMAIL_DOCUMENT.format(
        css=EMAIL_CSS,
        s_page=styles.S_PAGE,
        s_container=styles.S_CONTAINER,
        s_header_pad=styles.S_HEADER_PAD,
        header_html=header_html,
        s_content_pad=styles.S_CONTENT_PAD,
        content_html=content_html,
        s_footer=styles.S_FOOTER,
        footer_html=EMAIL_FOOTER_BRAND,
    )


def build_magic_link_text(verify_url: str, ttl_minutes: int, locale: str) -> str:
    intro = ti("email.magic_link.intro", locale, ttl_minutes=ttl_minutes)
    ignore_note = t("email.magic_link.ignore_note", locale)
    return f"{intro}\n\n{verify_url}\n\n{ignore_note}"
