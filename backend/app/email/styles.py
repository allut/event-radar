"""Styles for HTML emails (digest, magic link, etc.) — dark and light sets.

Colors/type mirror the website's design tokens (frontend/src/index.css :root).
Structural styling is inlined per-element (EmailStyles.s_* fields below) since
many email clients strip <style> blocks; the css field covers only progressive
enhancement (web fonts, link hover, mobile tweaks) that degrades safely when
stripped.

``get_email_styles()`` is the seam every email builder calls at render time —
one bundle, the light palette with a ``prefers-color-scheme:dark`` override,
so a client that honors OS dark mode renders dark and one that doesn't (or
strips ``<style>``) still gets a readable, intentional light render. There is
no per-recipient theme column to branch on — a stored theme can't
track a device that changes after the mail is sent. The bundle declares its
scheme via ``<meta name="color-scheme">`` (see ``EmailStyles.color_scheme``
and ``EMAIL_DOCUMENT``) so clients stop guessing and inverting on their own.
"""

from __future__ import annotations

from dataclasses import dataclass

# Tokens shared by both themes (accent hue, on-accent, accent-alpha overlay —
# already translucent/brand-fixed, no light variant per the mapping table).
_ACCENT = "#c8922a"
_ON_ACCENT = "#0f1119"
_ACCENT_ALPHA_PILL_BG = "rgba(200,146,42,0.12)"
# The paid-placement frame: the price-pill alpha family, so one tint and one
# hairline serve both themes.
_ACCENT_ALPHA_FRAME_BG = "rgba(200,146,42,0.10)"
_ACCENT_ALPHA_FRAME_BORDER = "rgba(200,146,42,0.35)"

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
S_BRAND_MARK = "display:block;margin:0 auto 12px auto;border:0;width:32px;height:32px;"
S_HEADER_PAD = "padding:40px 24px 24px 24px;text-align:center;"
S_FEED_BTN_WRAP = "padding:0 0 8px 0;"
S_CONTENT_PAD = "padding:8px 24px 24px 24px;"
S_CARD_WRAP = "padding-bottom:20px;"
S_IMG = "display:block;width:100%;max-width:600px;height:auto;border:0;"
S_BODY = "padding:18px 20px 8px 20px;"
S_META = "font-family:Helvetica,Arial,sans-serif;font-size:14px;margin:0 0 10px 0;"

# Class hooks in templates.py -> the palette tokens a prefers-color-scheme:dark
# client must repaint for the SYSTEM_STYLES (unset-preference) bundle. Inline
# styles win unless the rule is !important, since inline always beats a <style>
# block absent that.
_THEME_CLASS_RULES: dict[str, tuple[tuple[str, str], ...]] = {
    "e-page": (("background-color", "bg"),),
    "e-h1": (("color", "text"),),
    "e-date": (("color", "text_muted"),),
    "e-body-text": (("color", "text"),),
    "e-muted": (("color", "text_muted"),),
    "e-card": (("background-color", "bg_card"), ("border-color", "border")),
    "e-band": (("background-color", "bg_raised"),),
    "e-band-cat": (("color", "text_muted"),),
    "e-venue": (("color", "text_muted"),),
    "e-price": (("color", "accent_light"),),
    "e-title": (("color", "text"),),
    "e-bullet": (("color", "text_muted"),),
    "e-ticket-row": (("border-top-color", "border_subtle"),),
    "e-sponsor-label": (("color", "accent_light"),),
    "e-footer": (("color", "footer_text"), ("border-top-color", "border")),
    "e-footer-link": (("color", "text_muted"),),
}

_EMAIL_CSS_TEMPLATE = """
:root{color-scheme:COLOR_SCHEME;supported-color-schemes:COLOR_SCHEME;}
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


def _build_dark_override_css() -> str:
    rules = "\n".join(
        f"  .{cls}{{{''.join(f'{prop}:{_DARK_PALETTE[key]} !important;' for prop, key in decls)}}}"
        for cls, decls in _THEME_CLASS_RULES.items()
    )
    return f"@media (prefers-color-scheme:dark){{\n{rules}\n}}\n"


def _build_css(
    accent_light: str, *, color_scheme: str, dark_overrides: bool = False
) -> str:
    css = _EMAIL_CSS_TEMPLATE.replace("ACCENT_LIGHT", accent_light).replace(
        "COLOR_SCHEME", color_scheme
    )
    if dark_overrides:
        css += _build_dark_override_css()
    return css


@dataclass(frozen=True)
class EmailStyles:
    css: str
    color_scheme: str
    s_page: str
    s_container: str
    s_header_pad: str
    s_brand_mark: str
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
    s_sponsor_wrap: str
    s_sponsor: str
    s_sponsor_head: str
    s_sponsor_label: str
    s_sponsor_org: str
    s_sponsor_body: str
    s_sponsor_foot: str
    s_sponsor_note: str
    s_sponsor_stop: str


def _build_styles(
    p: dict[str, str], *, color_scheme: str, dark_overrides: bool = False
) -> EmailStyles:
    return EmailStyles(
        css=_build_css(
            p["accent_light"],
            color_scheme=color_scheme,
            dark_overrides=dark_overrides,
        ),
        color_scheme=color_scheme,
        s_page=f"margin:0;padding:0;background-color:{p['bg']};",
        s_container=S_CONTAINER,
        s_header_pad=S_HEADER_PAD,
        s_brand_mark=S_BRAND_MARK,
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
        s_sponsor_wrap="padding-top:8px;",
        s_sponsor=(
            f"background-color:{_ACCENT_ALPHA_FRAME_BG};"
            f"border:1px solid {_ACCENT_ALPHA_FRAME_BORDER};border-radius:0;"
        ),
        s_sponsor_head="padding:16px 20px 12px 20px;",
        s_sponsor_label=(
            "font-family:'Cormorant Garamond',Georgia,serif;font-style:italic;"
            f"font-size:20px;font-weight:600;color:{p['accent_light']};margin:0 0 2px 0;"
        ),
        s_sponsor_org=(
            "font-family:Helvetica,Arial,sans-serif;font-size:13px;"
            f"color:{p['text_muted']};margin:0;"
        ),
        s_sponsor_body="padding:0 20px;",
        s_sponsor_foot="padding:4px 20px 18px 20px;",
        s_sponsor_note=(
            "font-family:Helvetica,Arial,sans-serif;font-size:13px;line-height:1.5;"
            f"color:{p['text_muted']};margin:0 0 8px 0;"
        ),
        s_sponsor_stop=(
            "font-family:Helvetica,Arial,sans-serif;font-size:13px;"
            f"color:{p['text_muted']};text-decoration:underline;"
        ),
    )


EMAIL_STYLES = _build_styles(
    _LIGHT_PALETTE, color_scheme="light dark", dark_overrides=True
)


def get_email_styles() -> EmailStyles:
    """The one email bundle — light base, declares 'light dark',
    and carries a prefers-color-scheme:dark override so a client honoring OS
    theme still renders dark instead of force-inverting a purely-light email."""
    return EMAIL_STYLES
