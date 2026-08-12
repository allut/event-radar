"""KUMU adapter — kumu.ekm.ee/en/calendar/ (server-rendered event grid)."""

import logging
from datetime import datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup, Tag

from app.constants import (
    LOCALIZED_TEXT_MAX_DESC_CHARS,
    LOCALIZED_TEXT_MAX_TITLE_CHARS,
    PRICE_HINT_MAX_CHARS,
    TALLINN_TZ,
)
from app.ingestion.sanitize import html_to_text, sanitize_html
from app.ingestion.selectors import (
    KUMU_CARD_SELECTOR,
    KUMU_DATE_FORMAT,
    KUMU_DATE_SELECTOR,
    KUMU_DESCRIPTION_SELECTOR,
    KUMU_HIDDEN_SELECTOR,
    KUMU_IMAGE_SELECTOR,
    KUMU_LINK_SELECTOR,
    KUMU_MAX_PAGES,
    KUMU_PRICE_SELECTOR,
    KUMU_PRICE_TOOLTIP_ITEM_SELECTOR,
    KUMU_PRICE_TOOLTIP_TITLE_SELECTOR,
    KUMU_PRICE_TOOLTIP_VALUE_SELECTOR,
    KUMU_SITE_NAME_ET,
    KUMU_SITE_TITLE_SUFFIX,
    KUMU_TITLE_SELECTOR,
    KUMU_VENUE_ADDRESS,
    KUMU_VENUE_LAT,
    KUMU_VENUE_LNG,
    KUMU_VENUE_NAME,
)
from app.ingestion.html_utils import attr_str
from app.ingestion.sources.html_base import (
    HtmlListingAdapter,
    first_image_url,
    full_res_wp_image,
    og_title,
)

log = logging.getLogger(__name__)


def kumu_price_hint(price_tag: Tag) -> str:
    """Readable, comma-separated price hint from KUMU's ticket-price block.

    The headline is the price div's own direct text (e.g. "€16"), prefixed with
    its preceding label span (e.g. "Adult: Kumu Art Museum"); each tooltip row
    adds a "{label} {value}" entry (e.g. "Family: Kumu Art Museum €32").
    Space-joining the whole block fused labels and values ambiguously.
    """
    parts: list[str] = []
    headline = " ".join(
        s.strip() for s in price_tag.find_all(string=True, recursive=False) if s.strip()
    )
    if headline:
        label_tag = price_tag.find_previous_sibling("span")
        label = label_tag.get_text(" ", strip=True) if label_tag else ""
        parts.append(f"{label} {headline}".strip())
    for item in price_tag.select(KUMU_PRICE_TOOLTIP_ITEM_SELECTOR):
        title = item.select_one(KUMU_PRICE_TOOLTIP_TITLE_SELECTOR)
        value = item.select_one(KUMU_PRICE_TOOLTIP_VALUE_SELECTOR)
        label = title.get_text(" ", strip=True) if title else ""
        amount = value.get_text(" ", strip=True) if value else ""
        entry = f"{label} {amount}".strip()
        if entry:
            parts.append(entry)
    return ", ".join(parts) if parts else price_tag.get_text(" ", strip=True)


def kumu_localized_text(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Extract (title, description) from a KUMU detail page.

    Uses og:title (suffix-stripped) instead of JSON-LD — KUMU's JSON-LD is a
    Yoast WebPage graph with no Event block, so extract_jsonld_event_text returns
    (None, None). Falls back to <h1> text when og:title is absent.
    """
    raw_title = og_title(soup)
    if raw_title:
        if raw_title == KUMU_SITE_NAME_ET or raw_title.startswith(KUMU_SITE_NAME_ET + " -"):
            # Site-level page (homepage) — og:title is the venue/site name, not an event
            title = None
        else:
            title = raw_title.removesuffix(KUMU_SITE_TITLE_SUFFIX).strip() or None
    else:
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else None
    title = title[:LOCALIZED_TEXT_MAX_TITLE_CHARS] if title else None

    desc_tag = soup.select_one(KUMU_DESCRIPTION_SELECTOR)
    desc: str | None = None
    if desc_tag:
        html = sanitize_html(desc_tag.decode_contents())
        if html:
            desc = html if len(html) <= LOCALIZED_TEXT_MAX_DESC_CHARS else (
                (html_to_text(html) or "")[:LOCALIZED_TEXT_MAX_DESC_CHARS] or None
            )

    return title, desc


class KumuAdapter(HtmlListingAdapter):
    """kumu.ekm.ee/en/calendar/ — server-rendered, paginated event grid."""

    needs_detail = True
    max_pages = KUMU_MAX_PAGES

    def listing_url_for_page(self, page: int) -> str | None:
        url = str(self.source.config["url"])
        if page == 1:
            return url
        return f"{url.rstrip('/')}/page/{page}/"

    def parse_cards(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        for item in soup.select(KUMU_CARD_SELECTOR):
            link_tag = item.select_one(KUMU_LINK_SELECTOR)
            href = attr_str(link_tag, "href") if link_tag else ""
            if not href:
                continue

            title_tag = item.select_one(KUMU_TITLE_SELECTOR)
            title = ""
            if title_tag:
                hidden = title_tag.select_one(KUMU_HIDDEN_SELECTOR)
                if hidden:
                    hidden.extract()
                title = title_tag.get_text(" ", strip=True)
            if not title:
                continue

            date_tag = item.select_one(KUMU_DATE_SELECTOR)
            date_str = date_tag.get_text(strip=True) if date_tag else ""

            img_tag = item.select_one(KUMU_IMAGE_SELECTOR)
            image_url = full_res_wp_image(first_image_url(img_tag)) if img_tag else None

            cards.append(
                {
                    "external_id": href,
                    "title": title,
                    "date_str": date_str,
                    "image_url": image_url,
                    "url": href,
                    "venue": KUMU_VENUE_NAME,
                    "venue_address": KUMU_VENUE_ADDRESS,
                    "lat": KUMU_VENUE_LAT,
                    "lng": KUMU_VENUE_LNG,
                }
            )
        return cards

    def parse_date(self, card: dict[str, Any]) -> datetime | None:
        try:
            naive = datetime.strptime(card.get("date_str") or "", KUMU_DATE_FORMAT)
        except ValueError:
            return None
        return naive.replace(tzinfo=TALLINN_TZ)

    def extract_localized_text(
        self, soup: BeautifulSoup
    ) -> tuple[str | None, str | None]:
        return kumu_localized_text(soup)

    async def parse_detail(
        self, client: httpx.AsyncClient, soup: BeautifulSoup, card: dict[str, Any]
    ) -> None:
        desc_tag = soup.select_one(KUMU_DESCRIPTION_SELECTOR)
        if desc_tag:
            card["description"] = sanitize_html(desc_tag.decode_contents())

        price_tag = soup.select_one(KUMU_PRICE_SELECTOR)
        if price_tag:
            card["price_hint"] = kumu_price_hint(price_tag)[:PRICE_HINT_MAX_CHARS]
