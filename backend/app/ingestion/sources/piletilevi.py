import logging
from datetime import datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.constants import (
    HTTP_TIMEOUT_SECONDS,
    HTTP_USER_AGENT,
    PILETILEVI_BASE_URL,
    PILETILEVI_DATE_FORMAT,
    PILETILEVI_LISTING_URLS,
    PILETILEVI_MAX_DETAIL_FETCHES,
    PILETILEVI_TALLINN_FILTER,
    TALLINN_TZ,
)
from app.ingestion.base import NormalizedEvent, SourceAdapter, http_get

log = logging.getLogger(__name__)

_CARD_SELECTOR = 'a.card[href*="/en/tickets/"]'
_TITLE_SELECTOR = ".card__time-title h3"
_DATE_SELECTOR = ".card__time"
_VENUE_SELECTOR = ".card__description"
_IMAGE_SELECTOR = ".card__image"
_DETAIL_DESC_SELECTOR = ".event__description"


class PiletileviAdapter(SourceAdapter):
    """Scrapes piletilevi.ee listing pages for Tallinn events."""

    async def fetch_raw(self) -> list[dict[str, Any]]:
        seen_hrefs: set[str] = set()
        cards: list[dict[str, Any]] = []
        listing_errors: list[Exception] = []

        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": HTTP_USER_AGENT},
        ) as client:
            for path in PILETILEVI_LISTING_URLS:
                url = PILETILEVI_BASE_URL + path
                try:
                    resp = await http_get(client, url)
                except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                    log.warning("piletilevi listing fetch failed url=%s: %s", url, exc)
                    listing_errors.append(exc)
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")
                for tag in soup.select(_CARD_SELECTOR):
                    href: str = tag.get("href", "")
                    if not href or href in seen_hrefs:
                        continue

                    title_tag = tag.select_one(_TITLE_SELECTOR)
                    title = title_tag.get_text(strip=True) if title_tag else ""
                    if not title:
                        continue

                    date_tag = tag.select_one(_DATE_SELECTOR)
                    date_str = date_tag.get_text(strip=True) if date_tag else ""

                    venue_tag = tag.select_one(_VENUE_SELECTOR)
                    venue_str = venue_tag.get_text(strip=True) if venue_tag else ""

                    # Filter non-Tallinn events when city information is present
                    if venue_str and PILETILEVI_TALLINN_FILTER not in venue_str:
                        continue

                    img_tag = tag.select_one(_IMAGE_SELECTOR)
                    image_src: str | None = None
                    if img_tag:
                        image_src = img_tag.get("src") or img_tag.get("data-src")

                    seen_hrefs.add(href)
                    cards.append(
                        {
                            "href": href,
                            "title": title,
                            "date_str": date_str,
                            "venue": venue_str,
                            "image_url": image_src,
                        }
                    )

            # Partial tolerance: only raise when ALL listing URLs failed so a
            # single unavailable category page doesn't suppress a real run.
            if not cards and listing_errors:
                raise listing_errors[0]

            # Fetch detail pages for description (capped to prevent runaway on abnormally large listings)
            if len(cards) > PILETILEVI_MAX_DETAIL_FETCHES:
                log.warning(
                    "piletilevi: %d cards exceed cap %d — truncating detail fetches",
                    len(cards),
                    PILETILEVI_MAX_DETAIL_FETCHES,
                )
                cards = cards[:PILETILEVI_MAX_DETAIL_FETCHES]

            for card in cards:
                detail_url = PILETILEVI_BASE_URL + card["href"]
                try:
                    detail_resp = await http_get(client, detail_url)
                    detail_soup = BeautifulSoup(detail_resp.text, "html.parser")
                    desc_tag = detail_soup.select_one(_DETAIL_DESC_SELECTOR)
                    card["description"] = (
                        desc_tag.get_text(separator=" ", strip=True)
                        if desc_tag
                        else None
                    )
                except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                    log.warning(
                        "piletilevi detail fetch failed url=%s: %s", detail_url, exc
                    )
                    card["description"] = None

        log.info("piletilevi fetched %d events", len(cards))
        return cards

    def normalize(self, raw: dict[str, Any]) -> NormalizedEvent | None:
        title = raw.get("title") or ""
        if not title:
            return None

        href = raw.get("href") or ""
        if not href:
            return None

        starts_at = _parse_piletilevi_date(raw.get("date_str") or "")
        if starts_at is None:
            return None

        image_url = raw.get("image_url")
        # Relative image URLs → absolute
        if image_url and image_url.startswith("/"):
            image_url = PILETILEVI_BASE_URL + image_url

        return NormalizedEvent(
            external_id=href,
            title=title,
            starts_at=starts_at,
            venue_name=raw.get("venue") or None,
            description=raw.get("description"),
            image_url=image_url,
            url=PILETILEVI_BASE_URL + href,
        )

    def get_raw_external_id(self, raw: dict[str, Any]) -> str | None:
        return raw.get("href")


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
