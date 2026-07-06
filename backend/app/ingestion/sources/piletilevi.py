"""Piletilevi adapter — www.piletilevi.ee/en/tickets/all (paginated Nuxt catalog)."""

import logging
import re
from datetime import datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag

from app.constants import TALLINN_TZ
from app.ingestion.jsonld import extract_jsonld_event_location
from app.ingestion.sanitize import sanitize_html
from app.ingestion.selectors import (
    PILETILEVI_ALL_PATH,
    PILETILEVI_CARD_SELECTOR,
    PILETILEVI_DATE_FORMAT,
    PILETILEVI_DATE_SELECTOR,
    PILETILEVI_DETAIL_DESC_SELECTOR,
    PILETILEVI_IMAGE_HEIGHT,
    PILETILEVI_IMAGE_SELECTOR,
    PILETILEVI_IMPORTANT_INFO_HEADINGS,
    PILETILEVI_MAX_PAGES,
    PILETILEVI_TALLINN_FILTER,
    PILETILEVI_TITLE_SELECTOR,
    PILETILEVI_VENUE_SELECTOR,
)
from app.ingestion.sources.html_base import HtmlListingAdapter, attr_str

log = logging.getLogger(__name__)

_PILETILEVI_HEIGHT_RE = re.compile(r"/height=\d+/")


def full_res_piletilevi_image(url: str | None) -> str | None:
    """Rewrite the /height=N/ path segment to PILETILEVI_IMAGE_HEIGHT for
    full-resolution Piletilevi images. No-op for other hosts or URLs without
    the segment.
    """
    if not url or "piletilevi.ee" not in url:
        return url
    return _PILETILEVI_HEIGHT_RE.sub(f"/height={PILETILEVI_IMAGE_HEIGHT}/", url)


def _parse_piletilevi_date(date_str: str) -> datetime | None:
    """Parse "We 19.08.2026 • 19:00" → timezone-aware datetime."""
    if not date_str or "•" not in date_str:
        return None
    try:
        date_part_raw, time_part = date_str.split("•", 1)
        # Strip weekday abbreviation: "We 19.08.2026" → "19.08.2026"
        date_part = date_part_raw.strip().split(" ", 1)[-1].strip()
        time_part = time_part.strip()
        naive = datetime.strptime(f"{date_part} {time_part}", PILETILEVI_DATE_FORMAT)
        return naive.replace(tzinfo=TALLINN_TZ)
    except (ValueError, IndexError):
        return None


def _piletilevi_important_info(soup: BeautifulSoup, locale: str = "en") -> str | None:
    """Extract the important-info section text for the given locale, or None if absent.

    The section's <h2> carries no stable class (generic Tailwind utilities),
    so it's anchored by heading text instead — only two h2s exist on the
    page, so this is unambiguous.
    """
    heading_text = PILETILEVI_IMPORTANT_INFO_HEADINGS.get(
        locale, PILETILEVI_IMPORTANT_INFO_HEADINGS["en"]
    )
    heading = next(
        (
            h2
            for h2 in soup.find_all("h2")
            if h2.get_text(strip=True) == heading_text
        ),
        None,
    )
    if heading is None:
        return None
    block = heading.find_parent("div", class_="white-rounded-block")
    if block is None:
        return None
    # Piletilevi's Nuxt SSR markup leaves bare "[" / "]" text nodes as direct
    # children of the block (fragment-boundary artifacts) — real content is
    # always tag-wrapped (<p>, <strong>, ...), so a bare text node matching
    # exactly one of these is noise, not content.
    inner_html = "".join(
        str(child)
        for child in block.children
        if child is not heading
        and not (
            isinstance(child, NavigableString)
            and not isinstance(child, Tag)
            and child.strip() in ("[", "]")
        )
    )
    raw = sanitize_html(inner_html)
    return raw.strip() or None if raw else None


class PiletileviAdapter(HtmlListingAdapter):
    """piletilevi.ee/en/tickets/all — paginated catalog (Nuxt SSR markup)."""

    needs_detail = True
    max_pages = PILETILEVI_MAX_PAGES

    def listing_url_for_page(self, page: int) -> str | None:
        return f"{self.source.config['url']}{PILETILEVI_ALL_PATH}?page={page}"

    def parse_cards(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        base_url = str(self.source.config["url"])
        cards: list[dict[str, Any]] = []
        for tag in soup.select(PILETILEVI_CARD_SELECTOR):
            href = attr_str(tag, "href")
            if not href:
                continue

            title_tag = tag.select_one(PILETILEVI_TITLE_SELECTOR)
            title = title_tag.get_text(strip=True) if title_tag else ""
            if not title:
                continue

            date_tag = tag.select_one(PILETILEVI_DATE_SELECTOR)
            date_str = date_tag.get_text(strip=True) if date_tag else ""

            venue_tag = tag.select_one(PILETILEVI_VENUE_SELECTOR)
            venue_str = venue_tag.get_text(strip=True) if venue_tag else ""

            img_tag = tag.select_one(PILETILEVI_IMAGE_SELECTOR)
            image_url: str | None = None
            if img_tag:
                src = attr_str(img_tag, "src")
                if src:
                    raw_url = base_url + src if src.startswith("/") else src
                    image_url = full_res_piletilevi_image(raw_url)

            cards.append(
                {
                    "external_id": href,
                    "title": title,
                    "date_str": date_str,
                    "venue": venue_str,
                    "image_url": image_url,
                    "url": base_url + href,
                }
            )
        return cards

    def passes_filter(self, card: dict[str, Any]) -> bool:
        venue = card.get("venue") or ""
        # Filter non-Tallinn events when city information is present
        return not venue or PILETILEVI_TALLINN_FILTER in venue

    def parse_date(self, card: dict[str, Any]) -> datetime | None:
        return _parse_piletilevi_date(card.get("date_str") or "")

    def extract_localized_important_info(
        self, soup: BeautifulSoup, locale: str
    ) -> str | None:
        return _piletilevi_important_info(soup, locale)

    async def parse_detail(
        self, client: httpx.AsyncClient, soup: BeautifulSoup, card: dict[str, Any]
    ) -> None:
        desc_tag = soup.select_one(PILETILEVI_DETAIL_DESC_SELECTOR)
        card["description"] = sanitize_html(desc_tag.decode_contents()) if desc_tag else None
        card["important_info"] = _piletilevi_important_info(soup, "en")

        location = extract_jsonld_event_location(soup)
        if location:
            card["venue_address"] = location["venue_address"]
            card["lat"] = location["lat"]
            card["lng"] = location["lng"]
