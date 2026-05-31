"""HTML templates for digest emails (markup only — styling lives in styles.py)."""

# {css} must always be passed as a .format() value — never embed CSS literals here,
# since CSS braces would be misinterpreted as format placeholders.
DIGEST_DOCUMENT = """\
<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>{css}</style></head>
<body><div class="wrap">
<h1>{subject_label}</h1>
<h2>{date_str}</h2>
{events_html}
<div class="footer">
  <a href="{unsubscribe_url}">{settings_label}</a>
  &nbsp;·&nbsp; Event Radar, Tallinn
</div>
</div></body></html>"""

EVENT_BLOCK = (
    '<div class="event">'
    "<p>{title_link}</p>"
    '<p class="event-meta">{meta}</p>'
    '<ul class="bullets">{bullets_html}</ul>'
    "{price_html}"
    "</div>"
)

EVENT_TITLE_LINK = '<a href="{href}" class="event-title">{title}</a>'
EVENT_BULLET = "<li>{text}</li>"
EVENT_PRICE = '<p class="price">{price}</p>'
