"""Piletilevi adapter — www.piletilevi.ee/en/tickets/all (paginated Nuxt catalog)."""

import logging
import re
from datetime import datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag

from app.constants.core import TALLINN_TZ
from app.constants.http import HTTP_ACCEPT_JSON_HEADERS
from app.constants.ingestion import SOURCE_SLUG_PILETILEVI
from app.ingestion.http_client import http_get, http_post
from app.ingestion.jsonld import (
    location_from_jsonld_items,
    parse_jsonld_event_items,
    text_from_jsonld_items,
)
from app.ingestion.pricing import normalize_currency, to_float
from app.ingestion.sanitize import sanitize_html
from app.ingestion.selectors import (
    PILETILEVI_ALL_PATH,
    PILETILEVI_CARD_SELECTOR,
    PILETILEVI_CODE_RE,
    PILETILEVI_DATE_FORMAT,
    PILETILEVI_DATE_SELECTOR,
    PILETILEVI_DATE_SEPARATOR,
    PILETILEVI_DETAIL_DESC_SELECTOR,
    PILETILEVI_HEIGHT_PATH_RE,
    PILETILEVI_HOST,
    PILETILEVI_IMAGE_HEIGHT,
    PILETILEVI_IMAGE_SELECTOR,
    PILETILEVI_IMPORTANT_INFO_HEADINGS,
    PILETILEVI_INFO_BLOCK_CLASS,
    PILETILEVI_LOGIN_EXPRESS_URL,
    PILETILEVI_MAX_PAGES,
    PILETILEVI_PRICE_OUTCOME_SALE_NOT_STARTED,
    PILETILEVI_PRICE_OUTCOME_SOLD_OUT,
    PILETILEVI_PRICES_LANGUAGE,
    PILETILEVI_PRICES_URL,
    PILETILEVI_SALE_NOT_STARTED_CODE,
    PILETILEVI_SOLD_OUT_MESSAGE,
    PILETILEVI_TALLINN_FILTER,
    PILETILEVI_TITLE_SELECTOR,
    PILETILEVI_VENUE_SELECTOR,
)
from app.ingestion.html_utils import attr_str, localized_description
from app.ingestion.sources.html_base import HtmlListingAdapter, OnceAsync

log = logging.getLogger(__name__)

_PILETILEVI_HEIGHT_RE = re.compile(PILETILEVI_HEIGHT_PATH_RE)
_PILETILEVI_CODE_RE = re.compile(PILETILEVI_CODE_RE)


def _price_bounds_from_store(data: dict[str, Any]) -> tuple[float | None, float | None, bool]:
    """Flatten a Piletilevi store prices response into (min, max, has_free_tier).

    Response shape: {"eventSections": [{"priceZones": [{"ticketTypes": [
    {"price": 36.9, "fee": 0.0}, ...]}]}]}. price_min/price_max bound the PAID
    ticket types only (price > 0); has_free_tier flags a zero-priced ticket
    type existing alongside at least one paid one (e.g. a companion ticket).
    A genuinely free event (every ticket type priced 0) returns
    (0.0, 0.0, False) — mirrors extract_jsonld_event_offers's convention:
    has_free_tier only makes sense alongside a paid price. An event with no
    usable ticket types at all returns (None, None, False).
    """
    paid_prices: list[float] = []
    has_free = False
    for section in data.get("eventSections") or []:
        if not isinstance(section, dict):
            continue
        for zone in section.get("priceZones") or []:
            if not isinstance(zone, dict):
                continue
            for ticket_type in zone.get("ticketTypes") or []:
                if not isinstance(ticket_type, dict):
                    continue
                price = to_float(ticket_type.get("price"))
                if price is None:
                    continue
                if price > 0:
                    paid_prices.append(price)
                elif price == 0:
                    has_free = True
                # negative price: garbage data, ignore — neither paid nor free
    if paid_prices:
        return (min(paid_prices), max(paid_prices), has_free)
    if has_free:
        return (0.0, 0.0, False)
    return (None, None, False)


def classify_store_price_400(body: Any) -> str | None:
    """Name the business state a 400 from the store prices API carries.

    Returns PILETILEVI_PRICE_OUTCOME_SALE_NOT_STARTED or PILETILEVI_PRICE_OUTCOME_SOLD_OUT, or None
    for any other body (a genuine request error).
    """
    if isinstance(body, dict):
        if body.get("code") == PILETILEVI_SALE_NOT_STARTED_CODE:
            return PILETILEVI_PRICE_OUTCOME_SALE_NOT_STARTED
        return None
    if isinstance(body, list):
        sold_out = PILETILEVI_SOLD_OUT_MESSAGE.casefold()
        for entry in body:
            if not isinstance(entry, dict):
                continue
            for error in entry.get("errors") or []:
                if isinstance(error, dict) and str(error.get("message") or "").strip().casefold() == sold_out:
                    return PILETILEVI_PRICE_OUTCOME_SOLD_OUT
    return None


async def piletilevi_store_login(client: httpx.AsyncClient, slug: str) -> bool | None:
    """Login POST establishing the store session cookie; None on failure."""
    try:
        await http_post(
            client,
            PILETILEVI_LOGIN_EXPRESS_URL,
            headers=HTTP_ACCEPT_JSON_HEADERS,
        )
        return True
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        log.warning("%s login-express failed: %s", slug, exc)
        return None


async def fetch_store_prices(
    client: httpx.AsyncClient, code: str, slug: str
) -> tuple[dict[str, Any] | None, str | None]:
    """GET the store prices for one event code (session cookie already set).

    Returns ``(payload, outcome)``. ``outcome`` is set only for a pre-sale or
    sold-out 400, logged at INFO; every other failure logs a WARNING and
    returns ``(None, None)``.
    """
    try:
        resp = await http_get(
            client,
            PILETILEVI_PRICES_URL.format(code=code),
            params={"language": PILETILEVI_PRICES_LANGUAGE},
        )
        data = resp.json()
    except httpx.HTTPStatusError as exc:
        outcome = None
        if exc.response.status_code == 400:
            try:
                outcome = classify_store_price_400(exc.response.json())
            except ValueError:
                pass
        if outcome is not None:
            log.info("%s price unavailable code=%s: %s", slug, code, outcome)
            return None, outcome
        log.warning("%s price fetch failed code=%s: %s", slug, code, exc)
        return None, None
    except (httpx.RequestError, ValueError) as exc:
        log.warning("%s price fetch failed code=%s: %s", slug, code, exc)
        return None, None
    return (data if isinstance(data, dict) else None), None


def full_res_piletilevi_image(url: str | None) -> str | None:
    """Rewrite the /height=N/ path segment to PILETILEVI_IMAGE_HEIGHT for
    full-resolution Piletilevi images. No-op for other hosts or URLs without
    the segment.
    """
    if not url or PILETILEVI_HOST not in url:
        return url
    return _PILETILEVI_HEIGHT_RE.sub(f"/height={PILETILEVI_IMAGE_HEIGHT}/", url)


def _parse_piletilevi_date(date_str: str) -> datetime | None:
    """Parse "We 19.08.2026 • 19:00" → timezone-aware datetime."""
    if not date_str or PILETILEVI_DATE_SEPARATOR not in date_str:
        return None
    try:
        date_part_raw, time_part = date_str.split(PILETILEVI_DATE_SEPARATOR, 1)
        # Strip weekday abbreviation: "We 19.08.2026" → "19.08.2026"
        date_part = date_part_raw.strip().split(" ", 1)[-1].strip()
        time_part = time_part.strip()
        return datetime.strptime(
            f"{date_part} {time_part}", PILETILEVI_DATE_FORMAT
        ).replace(tzinfo=TALLINN_TZ)
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
    block = heading.find_parent("div", class_=PILETILEVI_INFO_BLOCK_CLASS)
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


def _cached_jsonld_items(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Parse a detail page's JSON-LD once and cache it on the soup object.

    For the base locale, parse_detail() and extract_localized_text() both run
    against the identical detail_soup (html_base.py::_fetch_detail passes the
    same object to both) — without this they'd each re-parse every
    <script type="application/ld+json"> block from scratch (Big-O audit #5,
    item 2.1). Caching on the soup instance (rather than a module-level dict)
    is safe under concurrent detail fetches: each fetch creates its own soup.
    """
    cached = getattr(soup, "_piletilevi_jsonld_items", None)
    if cached is None:
        cached = parse_jsonld_event_items(soup)
        soup._piletilevi_jsonld_items = cached  # type: ignore[attr-defined]
    return cached


def piletilevi_localized_text(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Extract (title, description) from a Piletilevi locale-variant detail page.

    Title comes from schema.org JSON-LD (``<h1>`` fallback inside
    text_from_jsonld_items) — Piletilevi's JSON-LD ``name`` is reliable.
    Description comes from the same ``.event__description`` HTML block
    ``parse_detail`` already uses, not the JSON-LD ``description`` string —
    that string is source-flattened plain text with paragraph breaks already
    collapsed, gluing sentences together (e.g. "...maagia.Lisainfo: ...").
    """
    title, _ = text_from_jsonld_items(_cached_jsonld_items(soup), soup)
    return title, localized_description(soup, PILETILEVI_DETAIL_DESC_SELECTOR)


class PiletileviAdapter(HtmlListingAdapter):
    """piletilevi.ee/en/tickets/all — paginated catalog (Nuxt SSR markup).

    parse_detail() resolves price via Piletilevi's own public store API
    (PILETILEVI_PRICES_URL), which requires a session cookie bootstrapped
    once per run via an empty-body login POST (PILETILEVI_LOGIN_EXPRESS_URL).
    Both endpoints live on the listing's own host, so no extra_allowed_hosts
    entry is needed (unlike EstoniaConcertHallAdapter's cross-host lookup).
    """

    needs_detail = True
    max_pages = PILETILEVI_MAX_PAGES

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._store_session: OnceAsync[bool] = OnceAsync(self._bootstrap_store_session)
        self.price_outcomes: dict[str, int] = {}

    async def fetch_raw(self, known_ids: set[str]) -> list[dict[str, Any]]:
        self.price_outcomes = {}
        try:
            return await super().fetch_raw(known_ids)
        finally:
            if self.price_outcomes:
                log.info("%s price unavailable: %s", self.source.slug, self.price_outcomes)

    async def _bootstrap_store_session(self, client: httpx.AsyncClient) -> bool | None:
        """Login POST establishing the Piletilevi store session cookie.

        The client's cookie jar persists across every detail fetch, so one
        successful login covers the whole run — the return value only
        signals success/failure to OnceAsync, the real effect is the
        side-effecting cookie.
        """
        return await piletilevi_store_login(client, self.source.slug)

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

    def extract_localized_text(
        self, soup: BeautifulSoup
    ) -> tuple[str | None, str | None]:
        return piletilevi_localized_text(soup)

    async def parse_detail(
        self, client: httpx.AsyncClient, soup: BeautifulSoup, card: dict[str, Any]
    ) -> None:
        desc_tag = soup.select_one(PILETILEVI_DETAIL_DESC_SELECTOR)
        card["description"] = sanitize_html(desc_tag.decode_contents()) if desc_tag else None
        card["important_info"] = _piletilevi_important_info(soup, "en")

        location = location_from_jsonld_items(_cached_jsonld_items(soup))
        if location:
            card["venue_address"] = location["venue_address"]
            card["lat"] = location["lat"]
            card["lng"] = location["lng"]

        match = _PILETILEVI_CODE_RE.search(card.get("url") or "")
        if not match:
            return
        if not await self._store_session.get(client):
            return

        price_data, outcome = await fetch_store_prices(client, match.group(1), self.source.slug)
        if outcome is not None:
            self.price_outcomes[outcome] = self.price_outcomes.get(outcome, 0) + 1
        if price_data is None:
            return

        price_min, price_max, has_free_tier = _price_bounds_from_store(price_data)
        if price_min is not None:
            card["price_min"] = price_min
            card["price_max"] = price_max
            card["currency"] = normalize_currency(None, price_min is not None)
            card["has_free_tier"] = has_free_tier


async def piletilevi_store_price_fields(
    client: httpx.AsyncClient, url: str, session: OnceAsync[bool]
) -> tuple[float | None, float | None, str | None, bool]:
    """Refetch-side store price lookup for an event with no stored price.

    Returns the ``(price_min, price_max, currency, has_free_tier)`` shape of
    ``offers_from_jsonld_items``; all-empty while the event is pre-sale or
    sold out, or on any failure, so a later refetch retries.
    """
    match = _PILETILEVI_CODE_RE.search(url)
    if not match or not await session.get(client):
        return None, None, None, False
    price_data, _ = await fetch_store_prices(client, match.group(1), SOURCE_SLUG_PILETILEVI)
    if price_data is None:
        return None, None, None, False
    price_min, price_max, has_free_tier = _price_bounds_from_store(price_data)
    if price_min is None:
        return None, None, None, False
    return price_min, price_max, normalize_currency(None, True), has_free_tier
