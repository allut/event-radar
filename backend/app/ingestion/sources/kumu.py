"""KUMU adapter — kumu.ekm.ee/en/calendar/ (server-rendered event grid)."""

import logging
from datetime import datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup, Tag

from app._generated.shared_constants import DEFAULT_CURRENCY
from app.constants.core import TALLINN_TZ
from app.constants.ingestion import PRICE_HINT_MAX_CHARS
from app.ingestion.pricing import eur_price_bounds_from_text, strip_fee_amounts
from app.ingestion.sanitize import sanitize_html
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
from app.ingestion.html_utils import attr_str, og_title_localized_text
from app.ingestion.sources.html_base import (
    HtmlListingAdapter,
    first_image_url,
    full_res_wp_image,
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


def kumu_price_bounds(
    soup: BeautifulSoup,
) -> tuple[float | None, float | None, str | None, bool]:
    """(price_min, price_max, currency, has_free_tier) from a KUMU detail page.

    KUMU's pages carry no schema.org Event/offers JSON-LD (#424) — the
    JSON-LD price reconciliation refetch.py/pinning.py otherwise share never
    fires for this source. Reuses the same KUMU_PRICE_SELECTOR block the
    ingest adapter reads (kumu_price_hint), truncated to PRICE_HINT_MAX_CHARS
    same as the stored price_hint (so a tier past the cutoff at ingest time
    can't manufacture a spurious "price changed" diff here), then derives
    bounds the same deterministic way classify_event's price-widening step
    does: strip_fee_amounts() first (drops booking/service-fee clauses like
    "agenditasu 3,20 €" so a fee isn't mistaken for a ticket price), then
    eur_price_bounds_from_text() over what's left. has_free_tier is always
    False here — the hint's tiers aren't individually priceable enough to
    tell a free companion ticket from a €0 typo, so this fallback only ever
    widens/fills the paid bounds, never sets the free-tier flag.
    """
    price_tag = soup.select_one(KUMU_PRICE_SELECTOR)
    if price_tag is None:
        return (None, None, None, False)
    hint = kumu_price_hint(price_tag)[:PRICE_HINT_MAX_CHARS]
    price_min, price_max = eur_price_bounds_from_text(strip_fee_amounts(hint))
    if price_min is None:
        return (None, None, None, False)
    return (price_min, price_max, DEFAULT_CURRENCY, False)


def kumu_localized_text(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Extract (title, description) from a KUMU detail page.

    Uses og:title (suffix-stripped) instead of JSON-LD — KUMU's JSON-LD is a
    Yoast WebPage graph with no Event block, so extract_jsonld_event_text returns
    (None, None). Falls back to <h1> text when og:title is absent.
    """
    return og_title_localized_text(
        soup,
        site_name=KUMU_SITE_NAME_ET,
        title_suffix=KUMU_SITE_TITLE_SUFFIX,
        desc_selector=KUMU_DESCRIPTION_SELECTOR,
    )


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
