import logging
import re
from datetime import date, datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup, Tag

from app.constants import (
    ESTONIA_CONCERT_HALL_TALLINN_FILTER,
    HTML_LISTING_MAX_DETAIL_FETCHES,
    HTTP_TIMEOUT_SECONDS,
    HTTP_USER_AGENT,
    KUMU_DATE_FORMAT,
    PILETILEVI_ALL_PATH,
    PILETILEVI_DATE_FORMAT,
    PILETILEVI_MAX_PAGES,
    PILETILEVI_TALLINN_FILTER,
    TALLINN_TZ,
    TELLISKIVI_DATE_FORMAT,
)
from app.ingestion.base import NormalizedEvent, SourceAdapter, http_get

log = logging.getLogger(__name__)


def _attr_str(tag: Tag, name: str) -> str:
    """Return a single-string attribute value.

    bs4 types attribute values as ``str | list[str]`` (multi-valued attributes
    like ``class`` parse as lists). The attributes we read here (href, src,
    data-srcset, style) are single-valued, so collapse any list to its first
    element.
    """
    value = tag.get(name)
    if isinstance(value, list):
        return value[0] if value else ""
    return value or ""


def _first_image_url(img_tag: Tag) -> str | None:
    """Return a usable image URL from a (possibly lazy-loaded) <img> tag.

    Lazy-loaded images carry a placeholder data: URI in ``src`` and the real
    URL(s) in ``data-srcset``; fall back to the first ``data-srcset`` entry.
    """
    src = _attr_str(img_tag, "src")
    if src and not src.startswith("data:"):
        return src
    srcset = _attr_str(img_tag, "data-srcset")
    if srcset:
        first = srcset.split(",")[0].strip().split(" ")[0]
        return first or None
    return None


def _next_occurrence_year(month: int, day: int, today: date | None = None) -> int:
    """Pick the year (current or next) in which month/day next occurs.

    Source listings render dates without a year. If the date has already
    passed this year, assume the next occurrence is next year.
    """
    if today is None:
        today = datetime.now(TALLINN_TZ).date()
    try:
        candidate = today.replace(month=month, day=day)
    except ValueError:
        return today.year
    return today.year if candidate >= today else today.year + 1


class HtmlListingAdapter(SourceAdapter):
    """Shared skeleton for server-rendered HTML listing pages.

    Subclasses provide ``parse_cards``/``parse_date`` (and optionally
    ``listing_url_for_page``, ``passes_filter``, ``parse_detail``) — this base
    owns the fetch loop, pagination, dedup, partial-tolerance error handling,
    and capped detail-page fetching.
    """

    needs_detail: bool = False
    max_pages: int = 1

    def listing_url_for_page(self, page: int) -> str | None:
        """Return the listing URL for ``page`` (1-indexed), or None to stop."""
        if page == 1:
            return str(self.source.config["url"])
        return None

    def parse_cards(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        """Parse one listing page into common card dicts.

        Card dicts carry ``external_id``, ``title``, ``url``, and whatever
        site-specific keys ``parse_date``/``parse_detail`` need.
        """
        raise NotImplementedError

    def parse_date(self, card: dict[str, Any]) -> datetime | None:
        """Parse a tz-aware start datetime from a card dict, or None if unparseable."""
        raise NotImplementedError

    def passes_filter(self, card: dict[str, Any]) -> bool:
        """Return False to drop a card before it is collected (e.g. non-Tallinn)."""
        return True

    def parse_detail(self, soup: BeautifulSoup, card: dict[str, Any]) -> None:
        """Fill in fields on ``card`` from its detail page. No-op by default."""
        return None

    async def fetch_raw(self) -> list[dict[str, Any]]:
        seen_ids: set[str] = set()
        cards: list[dict[str, Any]] = []
        listing_errors: list[Exception] = []

        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": HTTP_USER_AGENT},
        ) as client:
            page = 1
            while page <= self.max_pages:
                url = self.listing_url_for_page(page)
                if url is None:
                    break

                try:
                    resp = await http_get(client, url)
                except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                    log.warning(
                        "%s listing fetch failed url=%s: %s",
                        self.source.slug,
                        url,
                        exc,
                    )
                    listing_errors.append(exc)
                    page += 1
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")
                # Count new external ids regardless of passes_filter, so a page
                # consisting entirely of filtered-out events (e.g. non-Tallinn
                # Piletilevi listings) doesn't prematurely stop pagination.
                new_ids_on_page = 0
                for card in self.parse_cards(soup):
                    external_id = card.get("external_id") or ""
                    if not external_id or external_id in seen_ids:
                        continue
                    seen_ids.add(external_id)
                    new_ids_on_page += 1
                    if not self.passes_filter(card):
                        continue
                    cards.append(card)

                if new_ids_on_page == 0:
                    break
                if self.needs_detail and len(cards) >= HTML_LISTING_MAX_DETAIL_FETCHES:
                    break
                page += 1

            # Partial tolerance: only raise when ALL listing pages failed so a
            # single unavailable page doesn't suppress a real run.
            if not cards and listing_errors:
                raise listing_errors[0]

            if self.needs_detail:
                if len(cards) > HTML_LISTING_MAX_DETAIL_FETCHES:
                    log.warning(
                        "%s: %d cards exceed cap %d — truncating detail fetches",
                        self.source.slug,
                        len(cards),
                        HTML_LISTING_MAX_DETAIL_FETCHES,
                    )
                    cards = cards[:HTML_LISTING_MAX_DETAIL_FETCHES]

                for card in cards:
                    detail_url = card["url"]
                    try:
                        detail_resp = await http_get(client, detail_url)
                    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                        log.warning(
                            "%s detail fetch failed url=%s: %s",
                            self.source.slug,
                            detail_url,
                            exc,
                        )
                        continue
                    detail_soup = BeautifulSoup(detail_resp.text, "html.parser")
                    self.parse_detail(detail_soup, card)

        log.info("%s fetched %d events", self.source.slug, len(cards))
        return cards

    def normalize(self, raw: dict[str, Any]) -> NormalizedEvent | None:
        title = raw.get("title") or ""
        external_id = raw.get("external_id") or ""
        if not title or not external_id:
            return None

        starts_at = self.parse_date(raw)
        if starts_at is None:
            return None

        return NormalizedEvent(
            external_id=external_id,
            title=title,
            starts_at=starts_at,
            venue_name=raw.get("venue") or None,
            description=raw.get("description"),
            image_url=raw.get("image_url"),
            url=raw.get("url"),
        )

    def get_raw_external_id(self, raw: dict[str, Any]) -> str | None:
        return raw.get("external_id")


# ---------------------------------------------------------------------------
# Piletilevi — https://www.piletilevi.ee/en/tickets/all (paginated Nuxt catalog)
# ---------------------------------------------------------------------------

_PILETILEVI_CARD_SELECTOR = "a.card"
_PILETILEVI_TITLE_SELECTOR = ".card__time-title h3"
_PILETILEVI_DATE_SELECTOR = ".card__time"
_PILETILEVI_VENUE_SELECTOR = ".card__description"
_PILETILEVI_IMAGE_SELECTOR = "img.card__image"
_PILETILEVI_DETAIL_DESC_SELECTOR = ".event__description"


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


class PiletileviAdapter(HtmlListingAdapter):
    """piletilevi.ee/en/tickets/all — paginated catalog (Nuxt SSR markup)."""

    needs_detail = True
    max_pages = PILETILEVI_MAX_PAGES

    def listing_url_for_page(self, page: int) -> str | None:
        return f"{self.source.config['url']}{PILETILEVI_ALL_PATH}?page={page}"

    def parse_cards(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        base_url = str(self.source.config["url"])
        cards: list[dict[str, Any]] = []
        for tag in soup.select(_PILETILEVI_CARD_SELECTOR):
            href = _attr_str(tag, "href")
            if not href:
                continue

            title_tag = tag.select_one(_PILETILEVI_TITLE_SELECTOR)
            title = title_tag.get_text(strip=True) if title_tag else ""
            if not title:
                continue

            date_tag = tag.select_one(_PILETILEVI_DATE_SELECTOR)
            date_str = date_tag.get_text(strip=True) if date_tag else ""

            venue_tag = tag.select_one(_PILETILEVI_VENUE_SELECTOR)
            venue_str = venue_tag.get_text(strip=True) if venue_tag else ""

            img_tag = tag.select_one(_PILETILEVI_IMAGE_SELECTOR)
            image_url: str | None = None
            if img_tag:
                src = _attr_str(img_tag, "src")
                if src:
                    image_url = base_url + src if src.startswith("/") else src

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

    def parse_detail(self, soup: BeautifulSoup, card: dict[str, Any]) -> None:
        desc_tag = soup.select_one(_PILETILEVI_DETAIL_DESC_SELECTOR)
        card["description"] = (
            desc_tag.get_text(separator=" ", strip=True) if desc_tag else None
        )


# ---------------------------------------------------------------------------
# Kumu — https://kumu.ekm.ee/en/calendar/ (single page)
# ---------------------------------------------------------------------------

_KUMU_CARD_SELECTOR = "ul.event-grid__cards > li.event-grid__item"
_KUMU_LINK_SELECTOR = "a.card__link"
_KUMU_TITLE_SELECTOR = "h2.card__header-title"
_KUMU_DATE_SELECTOR = ".card__header-date-text"
_KUMU_IMAGE_SELECTOR = "img.image__img.lazyload"


class KumuAdapter(HtmlListingAdapter):
    """kumu.ekm.ee/en/calendar/ — server-rendered event grid."""

    def parse_cards(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        for item in soup.select(_KUMU_CARD_SELECTOR):
            link_tag = item.select_one(_KUMU_LINK_SELECTOR)
            href = _attr_str(link_tag, "href") if link_tag else ""
            if not href:
                continue

            title_tag = item.select_one(_KUMU_TITLE_SELECTOR)
            title_node = title_tag.find(string=True, recursive=False) if title_tag else None
            title = title_node.strip() if title_node else ""
            if not title:
                continue

            date_tag = item.select_one(_KUMU_DATE_SELECTOR)
            date_str = date_tag.get_text(strip=True) if date_tag else ""

            img_tag = item.select_one(_KUMU_IMAGE_SELECTOR)
            image_url = _first_image_url(img_tag) if img_tag else None

            cards.append(
                {
                    "external_id": href,
                    "title": title,
                    "date_str": date_str,
                    "image_url": image_url,
                    "url": href,
                }
            )
        return cards

    def parse_date(self, card: dict[str, Any]) -> datetime | None:
        try:
            naive = datetime.strptime(card.get("date_str") or "", KUMU_DATE_FORMAT)
        except ValueError:
            return None
        return naive.replace(tzinfo=TALLINN_TZ)


# ---------------------------------------------------------------------------
# Estonia Concert Hall — https://concert.ee/en/ (single page, all-Estonia listing)
# ---------------------------------------------------------------------------

_CONCERT_ROW_SELECTOR = ".event-list .row"
_CONCERT_TITLE_SELECTOR = ".info h2 a"
_CONCERT_DATE_SELECTOR = ".event-date"
_CONCERT_TIME_SELECTOR = ".event-time"
_CONCERT_LOCATION_SELECTOR = ".event-location"
_CONCERT_VENUE_SELECTOR = ".event-venue"
_CONCERT_IMAGE_SELECTOR = ".image"
_CONCERT_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})")
_CONCERT_IMAGE_URL_RE = re.compile(r"url\((.*?)\)")


class EstoniaConcertHallAdapter(HtmlListingAdapter):
    """concert.ee/en/ — root listing spans all Estonia; filtered to Tallinn."""

    def parse_cards(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        for row in soup.select(_CONCERT_ROW_SELECTOR):
            link_tag = row.select_one(_CONCERT_TITLE_SELECTOR)
            href = _attr_str(link_tag, "href") if link_tag else ""
            title = link_tag.get_text(strip=True) if link_tag else ""
            if not href or not title:
                continue

            date_tag = row.select_one(_CONCERT_DATE_SELECTOR)
            date_text = date_tag.get_text(" ", strip=True) if date_tag else ""

            time_tag = row.select_one(_CONCERT_TIME_SELECTOR)
            time_text = time_tag.get_text(strip=True) if time_tag else ""

            location_tag = row.select_one(_CONCERT_LOCATION_SELECTOR)
            location_text = location_tag.get_text(strip=True) if location_tag else ""

            venue_tag = row.select_one(_CONCERT_VENUE_SELECTOR)
            venue_text = venue_tag.get_text(strip=True) if venue_tag else ""

            image_url: str | None = None
            image_tag = row.select_one(_CONCERT_IMAGE_SELECTOR)
            if image_tag:
                style = _attr_str(image_tag, "style")
                match = _CONCERT_IMAGE_URL_RE.search(style)
                if match:
                    image_url = match.group(1).strip("'\"") or None

            cards.append(
                {
                    "external_id": href,
                    "title": title,
                    "date_text": date_text,
                    "time_text": time_text,
                    "location": location_text,
                    "venue": venue_text or None,
                    "image_url": image_url,
                    "url": href,
                }
            )
        return cards

    def passes_filter(self, card: dict[str, Any]) -> bool:
        return ESTONIA_CONCERT_HALL_TALLINN_FILTER in (card.get("location") or "")

    def parse_date(self, card: dict[str, Any]) -> datetime | None:
        match = _CONCERT_DATE_RE.search(card.get("date_text") or "")
        if not match:
            return None
        day, month = int(match.group(1)), int(match.group(2))

        hour, minute = 0, 0
        time_text = card.get("time_text") or ""
        if ":" in time_text:
            hour_str, _, minute_str = time_text.partition(":")
            try:
                hour, minute = int(hour_str), int(minute_str)
            except ValueError:
                hour, minute = 0, 0

        year = _next_occurrence_year(month, day)
        try:
            return datetime(year, month, day, hour, minute, tzinfo=TALLINN_TZ)
        except ValueError:
            return None


# ---------------------------------------------------------------------------
# Telliskivi — https://telliskivi.cc/en/events/ (single page)
# ---------------------------------------------------------------------------

_TELLISKIVI_CARD_SELECTOR = "div.card"
_TELLISKIVI_LINK_SELECTOR = "a.card__overlay-link"
_TELLISKIVI_TITLE_SELECTOR = "h3.card__title"
_TELLISKIVI_DATE_SELECTOR = ".card__timestamp-date"
_TELLISKIVI_IMAGE_SELECTOR = "img.image__img.lazyload"


class TelliskiviAdapter(HtmlListingAdapter):
    """telliskivi.cc/en/events/ — listing cards carry a year-less "Mon D" date."""

    def parse_cards(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        for card_tag in soup.select(_TELLISKIVI_CARD_SELECTOR):
            link_tag = card_tag.select_one(_TELLISKIVI_LINK_SELECTOR)
            href = _attr_str(link_tag, "href") if link_tag else ""
            if not href:
                continue

            title_tag = card_tag.select_one(_TELLISKIVI_TITLE_SELECTOR)
            title = title_tag.get_text(strip=True) if title_tag else ""
            if not title:
                continue

            date_tag = card_tag.select_one(_TELLISKIVI_DATE_SELECTOR)
            date_str = date_tag.get_text(strip=True) if date_tag else ""

            img_tag = card_tag.select_one(_TELLISKIVI_IMAGE_SELECTOR)
            image_url = _first_image_url(img_tag) if img_tag else None

            cards.append(
                {
                    "external_id": href,
                    "title": title,
                    "date_str": date_str,
                    "image_url": image_url,
                    "url": href,
                }
            )
        return cards

    def parse_date(self, card: dict[str, Any]) -> datetime | None:
        date_str = card.get("date_str") or ""
        try:
            parsed = datetime.strptime(date_str, TELLISKIVI_DATE_FORMAT)
        except ValueError:
            return None
        year = _next_occurrence_year(parsed.month, parsed.day)
        try:
            return datetime(year, parsed.month, parsed.day, tzinfo=TALLINN_TZ)
        except ValueError:
            return None
