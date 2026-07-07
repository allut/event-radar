"""HTML templates for digest emails (markup only — styling lives in styles.py).

Table-based layout with inlined styles so the card design (mirroring the
website) survives email clients that strip <style> blocks. All style values
are passed in as {s_*} placeholders sourced from app.email.styles.
"""

# {css} is inserted as a .format() *value*, so literal braces inside it are not
# reinterpreted as placeholders — only literal braces in this template string are.
DIGEST_DOCUMENT = """\
<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>{css}</style></head>
<body style="{s_page}">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="{s_page}">
<tr><td align="center">
<table role="presentation" class="container" width="600" cellpadding="0" cellspacing="0" border="0" style="{s_container}">
<tr><td class="pad" style="{s_header_pad}">
<p style="{s_eyebrow}">EVENT RADAR</p>
<h1 style="{s_h1}">{subject_label}</h1>
<p style="{s_date}">{date_str}</p>
<table role="presentation" align="center" cellpadding="0" cellspacing="0" border="0" style="{s_feed_btn_wrap}"><tr><td>
<a href="{feed_url}" class="feed-btn" style="{s_feed_btn}">{open_feed_label}</a>
</td></tr></table>
</td></tr>
<tr><td class="pad" style="{s_events_pad}">
{events_html}
</td></tr>
<tr><td class="pad" style="{s_footer}">
<a href="{unsubscribe_url}" style="{s_footer_link}">{settings_label}</a>
&nbsp;·&nbsp; Event Radar, Tallinn
</td></tr>
</table>
</td></tr>
</table>
</body></html>"""

EVENT_BLOCK = (
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="{s_card_wrap}">'
    "<tr><td>"
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="{s_card}">'
    "<tr><td>{image_html}</td></tr>"
    '<tr><td style="{s_body}">'
    '<p style="{s_meta}"><span style="{s_time}">{time_str}</span>{venue_html}{price_html}</p>'
    "<p>{title_link}</p>"
    "{bullets_html}"
    "</td></tr>"
    "{tickets_row_html}"
    "</table>"
    "</td></tr>"
    "</table>"
)

EVENT_IMAGE = (
    '<a href="{event_href}"><img src="{image_url}" alt="{title}" width="600" style="{s_img}"></a>'
)

EVENT_IMAGE_BAND = (
    '<a href="{event_href}" style="text-decoration:none;"><table role="presentation" width="100%" '
    'cellpadding="0" cellspacing="0" border="0" style="{s_band}"><tr><td align="center">'
    '<p style="{s_band_diamond}">&#9670;</p>'
    '<p style="{s_band_category}">{category}</p>'
    "</td></tr></table></a>"
)

EVENT_VENUE = ' <span style="{s_venue}">&middot; {venue}</span>'
EVENT_PRICE_PILL = '<span style="{s_price_pill}">{price}</span>'
EVENT_TITLE_LINK = '<a href="{href}" class="event-title-link" style="{s_title_link}">{title}</a>'
EVENT_BULLET = '<p style="{s_bullet_row}"><span style="{s_diamond}">&#9670;</span>{text}</p>'
EVENT_TICKETS_ROW = (
    '<tr><td style="{s_footer_row}">'
    '<a href="{href}" class="tickets-link" style="{s_tickets_link}">{label}</a>'
    "</td></tr>"
)
