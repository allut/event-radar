"""Static styles for HTML emails (digest, magic link, etc.).

Colors/type mirror the website's design tokens (frontend/src/index.css :root).
Structural styling is inlined per-element (S_* constants below) since many email
clients strip <style> blocks; EMAIL_CSS covers only progressive enhancement
(web fonts, link hover, mobile tweaks) that degrades safely when stripped.
"""

EMAIL_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@600&family=DM+Sans:wght@400;500;600&display=swap');
body{margin:0;padding:0;}
a{text-decoration:none;}
.event-title-link:hover{color:#e8a838 !important;}
.tickets-link:hover{color:#e8a838 !important;}
.cta-btn:hover{background:#e8a838 !important;}
@media (max-width:600px){
  .container{width:100% !important;}
  .pad{padding-left:16px !important;padding-right:16px !important;}
}
"""

# Shared page chrome
S_PAGE = "margin:0;padding:0;background-color:#13161e;"
S_CONTAINER = "max-width:600px;width:100%;margin:0 auto;"
S_HEADER_PAD = "padding:40px 24px 24px 24px;text-align:center;"
S_EYEBROW = (
    "font-family:'DM Sans',Helvetica,Arial,sans-serif;font-size:12px;"
    "letter-spacing:3px;text-transform:uppercase;color:#c8922a;margin:0 0 8px 0;"
)
S_H1 = (
    "font-family:'Cormorant Garamond',Georgia,serif;font-size:32px;font-weight:600;"
    "color:#e4dfd6;margin:0 0 6px 0;"
)
S_DATE = (
    "font-family:'DM Sans',Helvetica,Arial,sans-serif;font-size:14px;"
    "color:#7a8ba3;margin:0 0 24px 0;"
)
S_FEED_BTN_WRAP = "padding:0 0 8px 0;"
S_FEED_BTN = (
    "display:inline-block;font-family:'DM Sans',Helvetica,Arial,sans-serif;"
    "font-size:14px;font-weight:600;color:#0f1119;background-color:#c8922a;"
    "padding:12px 28px;border-radius:6px;letter-spacing:0.01em;"
)
S_CONTENT_PAD = "padding:8px 24px 24px 24px;"

# Magic-link body copy (reuses page-chrome tokens above)
S_BODY_TEXT = (
    "font-family:'DM Sans',Helvetica,Arial,sans-serif;font-size:15px;"
    "color:#e4dfd6;line-height:1.6;text-align:center;margin:0 0 20px 0;"
)
S_MUTED_NOTE = (
    "font-family:'DM Sans',Helvetica,Arial,sans-serif;font-size:13px;"
    "color:#7a8ba3;line-height:1.5;text-align:center;margin:20px 0 0 0;"
)

# Event card
S_CARD_WRAP = "padding-bottom:20px;"
S_CARD = (
    "background-color:#1c2230;border:1px solid #252c3d;border-radius:6px;"
    "overflow:hidden;"
)
S_IMG = "display:block;width:100%;max-width:600px;height:auto;border:0;"
S_BAND = (
    "background-color:#191e2b;text-align:center;padding:32px 16px;"
    "font-family:'DM Sans',Helvetica,Arial,sans-serif;"
)
S_BAND_DIAMOND = "color:#c8922a;font-size:14px;margin:0 0 6px 0;"
S_BAND_CATEGORY = (
    "color:#7a8ba3;font-size:12px;letter-spacing:2px;text-transform:uppercase;margin:0;"
)
S_BODY = "padding:18px 20px 8px 20px;"
S_META = (
    "font-family:'DM Sans',Helvetica,Arial,sans-serif;font-size:14px;margin:0 0 10px 0;"
)
S_TIME = "color:#c8922a;font-weight:500;"
S_VENUE = "color:#7a8ba3;"
S_PRICE_PILL = (
    "display:inline-block;font-family:'DM Sans',Helvetica,Arial,sans-serif;"
    "font-size:12px;font-weight:600;color:#e8a838;background-color:rgba(200,146,42,0.12);"
    "padding:3px 10px;border-radius:100px;letter-spacing:0.04em;margin-left:6px;"
)
S_TITLE_LINK = (
    "font-family:'Cormorant Garamond',Georgia,serif;font-size:22px;font-weight:600;"
    "color:#e4dfd6;line-height:1.2;"
)
S_BULLET_ROW = (
    "font-family:'DM Sans',Helvetica,Arial,sans-serif;font-size:14px;color:#7a8ba3;"
    "line-height:1.5;margin:0 0 6px 0;padding-left:2px;"
)
S_DIAMOND = "color:#c8922a;font-size:8px;margin-right:8px;"
S_FOOTER_ROW = (
    "border-top:1px solid #1c2333;padding:12px 20px 16px 20px;"
    "font-family:'DM Sans',Helvetica,Arial,sans-serif;font-size:14px;"
)
S_TICKETS_LINK = "color:#c8922a;font-weight:600;"

# Page footer
S_FOOTER = (
    "margin-top:8px;padding:20px 24px 40px 24px;border-top:1px solid #252c3d;"
    "font-family:'DM Sans',Helvetica,Arial,sans-serif;font-size:12px;color:#5a6478;"
    "text-align:center;"
)
S_FOOTER_LINK = "color:#7a8ba3;"
