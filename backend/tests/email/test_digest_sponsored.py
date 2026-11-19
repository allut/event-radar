"""The Sponsored block in the digest HTML (#611): frame, copy, links, no tracking."""

import re
from datetime import date

from app.email.digest import build_digest_html
from app.promotions.digest_slot import DigestSlot

STOP = "https://app.radar.example/en/email-consent-off?token=tok"


def render(make_event, locale="en", with_slot=True):
    picks = [make_event(event_id=i, title=f"Pick {i}") for i in range(1, 6)]
    slot = DigestSlot(7, "Acme & Co OÜ", make_event(event_id=99, title="Paid Show"))
    return build_digest_html(
        picks,
        date(2026, 5, 20),
        locale,
        "https://app.radar.example",
        sponsored=slot if with_slot else None,
        ads_off_url=STOP if with_slot else None,
    )


def test_block_sits_below_the_picks(make_event):
    html = render(make_event)
    assert html.index("Paid Show") > html.index("Pick 5")
    assert html.index('class="e-sponsor"') > html.index("Pick 5")


def test_no_block_without_slot(make_event):
    html = render(make_event, with_slot=False)
    assert 'class="e-sponsor"' not in html
    assert "digest-ad" not in html


def test_frame_is_sharp_and_gold_tinted_via_styles(make_event):
    html = render(make_event)
    frame = re.search(r'class="e-sponsor" style="([^"]*)"', html)
    assert frame is not None
    assert "border-radius:0" in frame.group(1)
    assert "rgba(200,146,42,0.10)" in frame.group(1)
    label = re.search(r'class="e-sponsor-label" style="([^"]*)"', html)
    assert label is not None and "font-style:italic" in label.group(1)


def test_event_links_carry_ref_and_picks_do_not(make_event):
    html = render(make_event)
    assert html.count("/en/events/99?ref=digest-ad") >= 2  # image/band + title
    assert "/en/events/1?ref=" not in html


def test_stop_link_and_escaped_advertiser(make_event):
    html = render(make_event)
    assert f'href="{STOP}"' in html
    assert "Stop ads in this email" in html
    assert "Paid for by Acme &amp; Co OÜ" in html
    assert "<p" in html and ">Ad</p>" in html


def test_no_open_tracking_pixel(make_event):
    html = render(make_event)
    assert not re.search(r"<img[^>]*(width=\"1\"|height=\"1\"|track|pixel|open)", html, re.I)


def test_no_bare_ad_hooks(make_event):
    html = render(make_event)
    assert not re.search(r'(id|class)="[^"]*\bads?\b[^"]*"', html)
