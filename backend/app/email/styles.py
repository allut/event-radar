"""Styles for HTML emails (digest, magic link, etc.) — dark and light sets.

Colors/type mirror the website's design tokens (frontend/src/index.css :root).
Structural styling is inlined per-element (EmailStyles.s_* fields below) since
many email clients strip <style> blocks; the css field covers only progressive
enhancement (web fonts, link hover, mobile tweaks) that degrades safely when
stripped.

``get_email_styles(theme_preference)`` is the seam every email builder calls
at render time: ``"dark"`` returns DARK_STYLES (today's values, unchanged);
anything else (``"light"``, ``None``, ``"system"``) returns LIGHT_STYLES.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.constants import THEME_PREFERENCE_DARK

# Tokens shared by both themes (accent hue, on-accent, accent-alpha overlay —
# already translucent/brand-fixed, no light variant per the mapping table).
_ACCENT = "#c8922a"
_ON_ACCENT = "#0f1119"
_ACCENT_ALPHA_PILL_BG = "rgba(200,146,42,0.12)"

_DARK_PALETTE = {
    "bg": "#13161e",
    "bg_raised": "#191e2b",
    "bg_card": "#1c2230",
    "border": "#252c3d",
    "border_subtle": "#1c2333",
    "text": "#e4dfd6",
    "text_muted": "#7a8ba3",
    "accent_light": "#e8a838",
    "footer_text": "#5a6478",
}
_LIGHT_PALETTE = {
    "bg": "#fdfcfa",
    "bg_raised": "#f5f6f9",
    "bg_card": "#eef0f4",
    "border": "#d7dbe4",
    "border_subtle": "#e6e9f0",
    "text": "#211f1a",
    "text_muted": "#4d5c74",
    "accent_light": "#a3701e",
    "footer_text": "#4d5c74",
}

# Structural (non-color) styling — identical across themes.
S_CONTAINER = "max-width:600px;width:100%;margin:0 auto;"
S_HEADER_PAD = "padding:40px 24px 24px 24px;text-align:center;"
S_FEED_BTN_WRAP = "padding:0 0 8px 0;"
S_CONTENT_PAD = "padding:8px 24px 24px 24px;"
S_CARD_WRAP = "padding-bottom:20px;"
S_IMG = "display:block;width:100%;max-width:600px;height:auto;border:0;"
S_BODY = "padding:18px 20px 8px 20px;"
S_META = "font-family:Helvetica,Arial,sans-serif;font-size:14px;margin:0 0 10px 0;"

_EMAIL_CSS_TEMPLATE = """
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@600&display=swap');
body{margin:0;padding:0;}
a{text-decoration:none;}
.event-title-link:hover{color:ACCENT_LIGHT !important;}
.tickets-link:hover{color:ACCENT_LIGHT !important;}
.cta-btn:hover{background:ACCENT_LIGHT !important;}
@media (max-width:600px){
  .container{width:100% !important;}
  .pad{padding-left:16px !important;padding-right:16px !important;}
}
"""


def _build_css(accent_light: str) -> str:
    return _EMAIL_CSS_TEMPLATE.replace("ACCENT_LIGHT", accent_light)


@dataclass(frozen=True)
class EmailStyles:
    css: str
    s_page: str
    s_container: str
    s_header_pad: str
    s_eyebrow: str
    s_h1: str
    s_date: str
    s_feed_btn_wrap: str
    s_feed_btn: str
    s_content_pad: str
    s_body_text: str
    s_muted_note: str
    s_card_wrap: str
    s_card: str
    s_img: str
    s_band: str
    s_band_diamond: str
    s_band_category: str
    s_body: str
    s_meta: str
    s_time: str
    s_venue: str
    s_price_pill: str
    s_title_link: str
    s_bullet_row: str
    s_diamond: str
    s_footer_row: str
    s_tickets_link: str
    s_footer: str
    s_footer_link: str


def _build_styles(p: dict[str, str]) -> EmailStyles:
    return EmailStyles(
        css=_build_css(p["accent_light"]),
        s_page=f"margin:0;padding:0;background-color:{p['bg']};",
        s_container=S_CONTAINER,
        s_header_pad=S_HEADER_PAD,
        s_eyebrow=(
            "font-family:Helvetica,Arial,sans-serif;font-size:12px;"
            f"letter-spacing:3px;text-transform:uppercase;color:{_ACCENT};margin:0 0 8px 0;"
        ),
        s_h1=(
            "font-family:'Cormorant Garamond',Georgia,serif;font-size:32px;font-weight:600;"
            f"color:{p['text']};margin:0 0 6px 0;"
        ),
        s_date=(
            "font-family:Helvetica,Arial,sans-serif;font-size:14px;"
            f"color:{p['text_muted']};margin:0 0 24px 0;"
        ),
        s_feed_btn_wrap=S_FEED_BTN_WRAP,
        s_feed_btn=(
            "display:inline-block;font-family:Helvetica,Arial,sans-serif;"
            f"font-size:14px;font-weight:600;color:{_ON_ACCENT};background-color:{_ACCENT};"
            "padding:12px 28px;border-radius:0;letter-spacing:0.01em;"
        ),
        s_content_pad=S_CONTENT_PAD,
        s_body_text=(
            "font-family:Helvetica,Arial,sans-serif;font-size:15px;"
            f"color:{p['text']};line-height:1.6;text-align:center;margin:0 0 20px 0;"
        ),
        s_muted_note=(
            "font-family:Helvetica,Arial,sans-serif;font-size:13px;"
            f"color:{p['text_muted']};line-height:1.5;text-align:center;margin:20px 0 0 0;"
        ),
        s_card_wrap=S_CARD_WRAP,
        s_card=(
            f"background-color:{p['bg_card']};border:1px solid {p['border']};border-radius:0;"
            "overflow:hidden;"
        ),
        s_img=S_IMG,
        s_band=(
            f"background-color:{p['bg_raised']};text-align:center;padding:32px 16px;"
            "font-family:Helvetica,Arial,sans-serif;"
        ),
        s_band_diamond=f"color:{_ACCENT};font-size:14px;margin:0 0 6px 0;",
        s_band_category=(
            f"color:{p['text_muted']};font-size:12px;letter-spacing:2px;"
            "text-transform:uppercase;margin:0;"
        ),
        s_body=S_BODY,
        s_meta=S_META,
        s_time=f"color:{_ACCENT};font-weight:500;",
        s_venue=f"color:{p['text_muted']};",
        s_price_pill=(
            "display:inline-block;font-family:Helvetica,Arial,sans-serif;"
            f"font-size:12px;font-weight:600;color:{p['accent_light']};"
            f"background-color:{_ACCENT_ALPHA_PILL_BG};"
            "padding:3px 10px;border-radius:100px;letter-spacing:0.04em;margin-left:6px;"
        ),
        s_title_link=(
            "font-family:'Cormorant Garamond',Georgia,serif;font-size:22px;font-weight:600;"
            f"color:{p['text']};line-height:1.2;"
        ),
        s_bullet_row=(
            f"font-family:Helvetica,Arial,sans-serif;font-size:14px;color:{p['text_muted']};"
            "line-height:1.5;margin:0 0 6px 0;padding-left:2px;"
        ),
        s_diamond=f"color:{_ACCENT};font-size:8px;margin-right:8px;",
        s_footer_row=(
            f"border-top:1px solid {p['border_subtle']};padding:12px 20px 16px 20px;"
            "font-family:Helvetica,Arial,sans-serif;font-size:14px;"
        ),
        s_tickets_link=f"color:{_ACCENT};font-weight:600;",
        s_footer=(
            f"margin-top:8px;padding:20px 24px 40px 24px;border-top:1px solid {p['border']};"
            f"font-family:Helvetica,Arial,sans-serif;font-size:12px;color:{p['footer_text']};"
            "text-align:center;"
        ),
        s_footer_link=f"color:{p['text_muted']};",
    )


DARK_STYLES = _build_styles(_DARK_PALETTE)
LIGHT_STYLES = _build_styles(_LIGHT_PALETTE)


def get_email_styles(theme_preference: str | None) -> EmailStyles:
    """'dark' keeps today's styling; anything else ('light'/None/'system') is light."""
    return DARK_STYLES if theme_preference == THEME_PREFERENCE_DARK else LIGHT_STYLES
