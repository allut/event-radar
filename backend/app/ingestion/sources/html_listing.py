import asyncio
import base64
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
from bs4 import BeautifulSoup, Tag

from app.constants import (
    DEFAULT_CURRENCY,
    DETAIL_FETCH_CONCURRENCY,
    ESTONIA_CONCERT_HALL_AJAX_ACTION,
    ESTONIA_CONCERT_HALL_AJAX_PATH,
    ESTONIA_CONCERT_HALL_DATE_SELECTOR,
    ESTONIA_CONCERT_HALL_DESCRIPTION_SELECTOR,
    ESTONIA_CONCERT_HALL_IMAGE_SELECTOR,
    ESTONIA_CONCERT_HALL_LOCATION_SELECTOR,
    ESTONIA_CONCERT_HALL_MAX_EVENTS,
    ESTONIA_CONCERT_HALL_PILETILEVI_AUTH_URL,
    ESTONIA_CONCERT_HALL_PILETILEVI_CENTER,
    ESTONIA_CONCERT_HALL_PILETILEVI_PARAMS,
    ESTONIA_CONCERT_HALL_PILETILEVI_SESSION_CLAIM,
    ESTONIA_CONCERT_HALL_PILETILEVI_SHOP_PROVIDER,
    ESTONIA_CONCERT_HALL_PILETILEVI_URL,
    ESTONIA_CONCERT_HALL_ROW_SELECTOR,
    ESTONIA_CONCERT_HALL_TALLINN_FILTER,
    ESTONIA_CONCERT_HALL_TIME_SELECTOR,
    ESTONIA_CONCERT_HALL_TITLE_SELECTOR,
    ESTONIA_CONCERT_HALL_VENUE_SELECTOR,
    ESTONIA_CONCERT_HALL_VENUES,
    HTML_LISTING_LOCALE_FETCH_DELAY_SECONDS,
    HTML_LISTING_MAX_DETAIL_FETCHES,
    HTTP_TIMEOUT_SECONDS,
    HTTP_USER_AGENT,
    LOCALIZED_TEXT_HTML_LOCALES,
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
    KUMU_TITLE_SELECTOR,
    KUMU_VENUE_ADDRESS,
    KUMU_VENUE_LAT,
    KUMU_VENUE_LNG,
    KUMU_VENUE_NAME,
    PILETILEVI_ALL_PATH,
    PILETILEVI_CARD_SELECTOR,
    PILETILEVI_DATE_FORMAT,
    PILETILEVI_DATE_SELECTOR,
    PILETILEVI_DETAIL_DESC_SELECTOR,
    PILETILEVI_IMAGE_SELECTOR,
    PILETILEVI_IMPORTANT_INFO_HEADING,
    PILETILEVI_MAX_PAGES,
    PILETILEVI_TALLINN_FILTER,
    PILETILEVI_TITLE_SELECTOR,
    PILETILEVI_VENUE_SELECTOR,
    PRICE_HINT_MAX_CHARS,
    TALLINN_TZ,
)
from app.ingestion.base import (
    NormalizedEvent,
    SourceAdapter,
    extract_jsonld_event_location,
    extract_jsonld_event_text,
    host_guard_hook,
    http_get,
    http_post,
    localized_detail_urls,
)

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


@dataclass
class ListingRequest:
    url: str
    method: str = "GET"
    data: dict[str, Any] | None = None


class HtmlListingAdapter(SourceAdapter):
    """Shared skeleton for server-rendered HTML listing pages.

    Subclasses provide ``parse_cards``/``parse_date`` (and optionally
    ``listing_url_for_page``, ``passes_filter``, ``parse_detail``) — this base
    owns the fetch loop, pagination, dedup, partial-tolerance error handling,
    and capped detail-page fetching.
    """

    needs_detail: bool = False
    max_pages: int = 1
    # Hosts beyond the source's own listing host that this adapter
    # deliberately fetches from via a fixed, hardcoded URL (not derived from
    # scraped HTML) — e.g. a price-lookup API on a different domain.
    extra_allowed_hosts: frozenset[str | None] = frozenset()

    def listing_url_for_page(self, page: int) -> str | None:
        """Return the listing URL for ``page`` (1-indexed), or None to stop."""
        if page == 1:
            return str(self.source.config["url"])
        return None

    def listing_request(self, page: int) -> ListingRequest | None:
        """HTTP request for ``page``, or None to stop. Default: GET listing_url_for_page."""
        url = self.listing_url_for_page(page)
        return ListingRequest(url=url) if url is not None else None

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

    async def parse_detail(
        self, client: httpx.AsyncClient, soup: BeautifulSoup, card: dict[str, Any]
    ) -> None:
        """Fill in fields on ``card`` from its detail page. No-op by default."""
        return None

    async def fetch_raw(self, known_ids: set[str]) -> list[dict[str, Any]]:
        seen_ids: set[str] = set()
        cards: list[dict[str, Any]] = []
        listing_errors: list[Exception] = []

        base_host = urlsplit(str(self.source.config["url"])).hostname
        allowed_hosts = frozenset({base_host}) | self.extra_allowed_hosts
        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": HTTP_USER_AGENT},
            event_hooks={"request": [host_guard_hook(allowed_hosts)]},
        ) as client:
            page = 1
            while page <= self.max_pages:
                req = self.listing_request(page)
                if req is None:
                    break

                try:
                    if req.method == "POST":
                        resp = await http_post(client, req.url, data=req.data)
                    else:
                        resp = await http_get(client, req.url)
                except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                    log.warning(
                        "%s listing fetch failed url=%s: %s",
                        self.source.slug,
                        req.url,
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
                    if external_id in known_ids:
                        # Forward-only: don't spend the detail cap on
                        # already-stored events — lets pagination advance
                        # past them to reach new events on later pages.
                        continue
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

                # known_ids cards never reach here — the collection loop above
                # already excludes them, so every card here needs a detail fetch.
                semaphore = asyncio.Semaphore(DETAIL_FETCH_CONCURRENCY)
                results = await asyncio.gather(
                    *[self._fetch_detail(client, card, semaphore) for card in cards],
                    return_exceptions=True,
                )
                # _fetch_detail only swallows httpx errors internally — anything
                # else escaping it is an unexpected bug (e.g. in a subclass's
                # parse_detail). return_exceptions=True keeps one card's crash
                # from cancelling the others' in-flight fetches, but the bug must
                # still surface (log + propagate) rather than vanish silently,
                # per the "never swallow exceptions in fetch_raw()" invariant.
                unexpected = [r for r in results if isinstance(r, BaseException)]
                for detail_exc in unexpected:
                    log.error(
                        "%s detail fetch task raised unexpectedly: %s",
                        self.source.slug,
                        detail_exc,
                    )
                if unexpected:
                    raise unexpected[0]

        # cards already excludes known_ids (collection loop above); the filter
        # here is now a defensive no-op kept for the log line.
        new_cards = [c for c in cards if c.get("external_id") not in known_ids]
        log.info("%s fetched %d events", self.source.slug, len(new_cards))
        return new_cards

    async def _fetch_detail(
        self,
        client: httpx.AsyncClient,
        card: dict[str, Any],
        semaphore: asyncio.Semaphore,
    ) -> None:
        """Fetch one card's detail page and let parse_detail enrich it.

        Failures are logged and swallowed — the run degrades to listing-only
        for that card (same tolerance as the old sequential loop).
        """
        detail_url = card["url"]
        async with semaphore:
            try:
                detail_resp = await http_get(client, detail_url)
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                log.warning(
                    "%s detail fetch failed url=%s: %s",
                    self.source.slug,
                    detail_url,
                    exc,
                )
                return
            detail_soup = BeautifulSoup(detail_resp.text, "html.parser")
            await self.parse_detail(client, detail_soup, card)
            # Fetch locale alternates for native title/description
            locale_urls = localized_detail_urls(
                detail_soup, detail_url, LOCALIZED_TEXT_HTML_LOCALES
            )
            loc_titles: dict[str, str] = {}
            loc_descs: dict[str, str] = {}
            for locale, loc_url in locale_urls.items():
                if loc_url == detail_url:
                    loc_name, loc_desc = extract_jsonld_event_text(detail_soup)
                else:
                    try:
                        await asyncio.sleep(HTML_LISTING_LOCALE_FETCH_DELAY_SECONDS)
                        loc_resp = await http_get(client, loc_url)
                        loc_soup = BeautifulSoup(loc_resp.text, "html.parser")
                        loc_name, loc_desc = extract_jsonld_event_text(loc_soup)
                    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                        log.debug(
                            "%s locale fetch failed locale=%s url=%s: %s",
                            self.source.slug, locale, loc_url, exc,
                        )
                        continue
                    except Exception as exc:
                        log.warning(
                            "%s locale fetch unexpected error locale=%s url=%s: %s",
                            self.source.slug, locale, loc_url, exc,
                        )
                        continue
                if loc_name:
                    loc_titles[locale] = loc_name
                if loc_desc:
                    loc_descs[locale] = loc_desc
            if loc_titles:
                card["title_localized"] = loc_titles
            if loc_descs:
                card["description_localized"] = loc_descs

    def normalize(self, raw: dict[str, Any]) -> NormalizedEvent | None:
        title = raw.get("title") or ""
        external_id = raw.get("external_id") or ""
        if not title or not external_id:
            return None

        starts_at = self.parse_date(raw)
        if starts_at is None:
            return None

        loc_titles = raw.get("title_localized") or {}
        loc_descs = raw.get("description_localized") or {}
        return NormalizedEvent(
            external_id=external_id,
            title=title,
            starts_at=starts_at,
            venue_name=raw.get("venue") or None,
            venue_address=raw.get("venue_address"),
            lat=raw.get("lat"),
            lng=raw.get("lng"),
            description=raw.get("description"),
            important_info=raw.get("important_info"),
            image_url=raw.get("image_url"),
            url=raw.get("url"),
            price_min=raw.get("price_min"),
            price_max=raw.get("price_max"),
            currency=raw.get("currency"),
            price_hint=raw.get("price_hint"),
            title_localized=loc_titles if loc_titles else None,
            description_localized=loc_descs if loc_descs else None,
        )

    def get_raw_external_id(self, raw: dict[str, Any]) -> str | None:
        return raw.get("external_id")


# ---------------------------------------------------------------------------
# Piletilevi — https://www.piletilevi.ee/en/tickets/all (paginated Nuxt catalog)
# ---------------------------------------------------------------------------

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


def _piletilevi_important_info(soup: BeautifulSoup) -> str | None:
    """Extract the "Important information" section text, or None if absent.

    The section's <h2> carries no stable class (generic Tailwind utilities),
    so it's anchored by heading text instead — only two h2s exist on the
    page ("Important information", "Event location"), so this is unambiguous.
    """
    heading = next(
        (
            h2
            for h2 in soup.find_all("h2")
            if h2.get_text(strip=True) == PILETILEVI_IMPORTANT_INFO_HEADING
        ),
        None,
    )
    if heading is None:
        return None
    block = heading.find_parent("div", class_="white-rounded-block")
    if block is None:
        return None
    text = block.get_text(separator=" ", strip=True)
    return text.removeprefix(PILETILEVI_IMPORTANT_INFO_HEADING).strip() or None


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
            href = _attr_str(tag, "href")
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

    async def parse_detail(
        self, client: httpx.AsyncClient, soup: BeautifulSoup, card: dict[str, Any]
    ) -> None:
        desc_tag = soup.select_one(PILETILEVI_DETAIL_DESC_SELECTOR)
        card["description"] = (
            desc_tag.get_text(separator=" ", strip=True) if desc_tag else None
        )
        card["important_info"] = _piletilevi_important_info(soup)

        location = extract_jsonld_event_location(soup)
        if location:
            card["venue_address"] = location["venue_address"]
            card["lat"] = location["lat"]
            card["lng"] = location["lng"]


# ---------------------------------------------------------------------------
# Kumu — https://kumu.ekm.ee/en/calendar/ (single page)
# ---------------------------------------------------------------------------


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
            href = _attr_str(link_tag, "href") if link_tag else ""
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
            image_url = _first_image_url(img_tag) if img_tag else None

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

    async def parse_detail(
        self, client: httpx.AsyncClient, soup: BeautifulSoup, card: dict[str, Any]
    ) -> None:
        desc_tag = soup.select_one(KUMU_DESCRIPTION_SELECTOR)
        if desc_tag:
            card["description"] = desc_tag.get_text(separator=" ", strip=True)

        price_tag = soup.select_one(KUMU_PRICE_SELECTOR)
        if price_tag:
            card["price_hint"] = kumu_price_hint(price_tag)[:PRICE_HINT_MAX_CHARS]


# ---------------------------------------------------------------------------
# Estonia Concert Hall — https://concert.ee/en/ (single page, all-Estonia listing)
# ---------------------------------------------------------------------------

_CONCERT_DATE_RE = re.compile(r"(\d{1,2})\.(\d{1,2})")
_CONCERT_IMAGE_URL_RE = re.compile(r"url\((.*?)\)")
_CONCERT_PID_RE = re.compile(r"pid=(\d+)")


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _jwt_claim(token: str, claim: str) -> str | None:
    """Read one claim out of a JWT's payload segment, without verifying its signature.

    The token is a session credential issued by the very call that hands it to
    us (express-auth) — there's nothing to verify against, we just need the
    opaque session value it carries.
    """
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload_b64 = parts[1]
    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, UnicodeDecodeError):
        return None
    value = payload.get(claim) if isinstance(payload, dict) else None
    return value if isinstance(value, str) else None


class EstoniaConcertHallAdapter(HtmlListingAdapter):
    """concert.ee/en/ — full programme loaded via the "Load more" AJAX endpoint.

    parse_detail() resolves price via a deliberate, hardcoded cross-host POST
    to the Piletilevi ticket store (ESTONIA_CONCERT_HALL_PILETILEVI_URL), so
    that host is allow-listed alongside concert.ee for the SSRF guard. The
    store endpoint requires a fresh per-run session key, bootstrapped once via
    _piletilevi_session_key() and cached on the adapter instance.
    """

    needs_detail = True
    extra_allowed_hosts = frozenset(
        {urlsplit(ESTONIA_CONCERT_HALL_PILETILEVI_URL).hostname}
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._session_key: str | None = None
        self._session_failed = False
        self._session_lock = asyncio.Lock()

    async def _piletilevi_session_key(self, client: httpx.AsyncClient) -> str | None:
        """Bootstrap (once per run) and cache the Piletilevi store session key.

        Token lifetime is ~15 min, comfortably covering one run's detail
        fetches. On failure, caches the failure so later cards don't re-attempt.
        """
        async with self._session_lock:
            if self._session_key is not None or self._session_failed:
                return self._session_key
            try:
                resp = await http_post(
                    client,
                    ESTONIA_CONCERT_HALL_PILETILEVI_AUTH_URL,
                    json_body={
                        "centreId": int(ESTONIA_CONCERT_HALL_PILETILEVI_CENTER),
                        "shopProviderTag": ESTONIA_CONCERT_HALL_PILETILEVI_SHOP_PROVIDER,
                    },
                    headers={"accept": "application/json"},
                )
                data = resp.json()
                token = data.get("accessToken") if isinstance(data, dict) else None
                session_key = (
                    _jwt_claim(token, ESTONIA_CONCERT_HALL_PILETILEVI_SESSION_CLAIM)
                    if isinstance(token, str)
                    else None
                )
            except (httpx.HTTPStatusError, httpx.RequestError, ValueError):
                session_key = None

            if session_key is None:
                self._session_failed = True
            self._session_key = session_key
            return self._session_key

    def listing_request(self, page: int) -> ListingRequest | None:
        if page != 1:
            return None
        parts = urlsplit(str(self.source.config["url"]))
        ajax_url = f"{parts.scheme}://{parts.netloc}{ESTONIA_CONCERT_HALL_AJAX_PATH}"
        return ListingRequest(
            url=ajax_url,
            method="POST",
            data={
                "action": ESTONIA_CONCERT_HALL_AJAX_ACTION,
                "ek_ajax_count[]": str(ESTONIA_CONCERT_HALL_MAX_EVENTS),
            },
        )

    def parse_cards(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        for row in soup.select(ESTONIA_CONCERT_HALL_ROW_SELECTOR):
            link_tag = row.select_one(ESTONIA_CONCERT_HALL_TITLE_SELECTOR)
            href = _attr_str(link_tag, "href") if link_tag else ""
            title = link_tag.get_text(strip=True) if link_tag else ""
            if not href or not title:
                continue

            date_tag = row.select_one(ESTONIA_CONCERT_HALL_DATE_SELECTOR)
            date_text = date_tag.get_text(" ", strip=True) if date_tag else ""

            time_tag = row.select_one(ESTONIA_CONCERT_HALL_TIME_SELECTOR)
            time_text = time_tag.get_text(strip=True) if time_tag else ""

            location_tag = row.select_one(ESTONIA_CONCERT_HALL_LOCATION_SELECTOR)
            location_text = location_tag.get_text(strip=True) if location_tag else ""

            venue_tag = row.select_one(ESTONIA_CONCERT_HALL_VENUE_SELECTOR)
            venue_text = venue_tag.get_text(strip=True) if venue_tag else ""

            image_url: str | None = None
            image_tag = row.select_one(ESTONIA_CONCERT_HALL_IMAGE_SELECTOR)
            if image_tag:
                style = _attr_str(image_tag, "style")
                match = _CONCERT_IMAGE_URL_RE.search(style)
                if match:
                    image_url = match.group(1).strip("'\"") or None

            card: dict[str, Any] = {
                "external_id": href,
                "title": title,
                "date_text": date_text,
                "time_text": time_text,
                "location": location_text,
                "venue": venue_text or None,
                "image_url": image_url,
                "url": href,
            }

            venue_info = ESTONIA_CONCERT_HALL_VENUES.get(venue_text)
            if venue_info:
                card["venue"] = venue_info.name
                card["venue_address"] = venue_info.address
                card["lat"] = venue_info.lat
                card["lng"] = venue_info.lng

            cards.append(card)
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

    async def parse_detail(
        self, client: httpx.AsyncClient, soup: BeautifulSoup, card: dict[str, Any]
    ) -> None:
        """Fill description from the detail page, then resolve price via the
        buy-ticket link's Piletilevi store pid, if present.

        Description covers every event regardless of pid. Price stays null
        when there's no pid (free/sold-out events), the session bootstrap
        fails, or the Piletilevi store lookup fails/returns no sections —
        never fails the run.
        """
        desc_tag = soup.select_one(ESTONIA_CONCERT_HALL_DESCRIPTION_SELECTOR)
        if desc_tag:
            card["description"] = desc_tag.get_text(separator=" ", strip=True)

        link = soup.find("a", href=_CONCERT_PID_RE)
        if link is None:
            return
        match = _CONCERT_PID_RE.search(_attr_str(link, "href"))
        if not match:
            return
        pid = match.group(1)

        session_key = await self._piletilevi_session_key(client)
        if session_key is None:
            return

        params = {**ESTONIA_CONCERT_HALL_PILETILEVI_PARAMS, "key": session_key}
        url = f"{ESTONIA_CONCERT_HALL_PILETILEVI_URL}?{urlencode(params)}"
        try:
            resp = await http_post(client, url, data={"concert": pid})
            data = resp.json()
        except (httpx.HTTPStatusError, httpx.RequestError, ValueError):
            return
        if not isinstance(data, dict):
            return

        response_data = data.get("responseData")
        configuration = (
            response_data.get("configuration")
            if isinstance(response_data, dict)
            else None
        )
        sections = (
            configuration.get("sections") if isinstance(configuration, dict) else None
        )
        if not isinstance(sections, list):
            return

        min_prices = [
            f
            for s in sections
            if isinstance(s, dict) and (f := _to_float(s.get("minPrice"))) is not None
        ]
        max_prices = [
            f
            for s in sections
            if isinstance(s, dict) and (f := _to_float(s.get("maxPrice"))) is not None
        ]
        if not min_prices or not max_prices:
            return

        lo, hi = min(min_prices), max(max_prices)
        card["price_min"] = lo
        card["price_max"] = hi
        card["currency"] = DEFAULT_CURRENCY
