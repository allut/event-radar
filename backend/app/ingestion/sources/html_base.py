"""Shared skeleton for server-rendered HTML listing sources.

HtmlListingAdapter owns the fetch loop, pagination, dedup, partial-tolerance
error handling, capped concurrent detail fetches, and per-locale text
backfill. Concrete sources (piletilevi.py, kumu.py, estonia_concert_hall.py)
subclass it — new HTML-scraped sources should too, per CLAUDE.md.
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup, Tag

from app.constants import (
    DETAIL_FETCH_CONCURRENCY,
    HTML_LISTING_LOCALE_FETCH_DELAY_SECONDS,
    HTML_LISTING_MAX_DETAIL_FETCHES,
    HTTP_TIMEOUT_SECONDS,
    HTTP_USER_AGENT,
    LOCALIZED_TEXT_HTML_LOCALES,
    TALLINN_TZ,
)
from app.ingestion.adapter import NormalizedEvent, SourceAdapter
from app.ingestion.http_client import host_guard_hook, http_get, http_post
from app.ingestion.jsonld import extract_jsonld_event_text
from app.ingestion.locale_urls import locale_from_url_path, localized_detail_urls
from app.ingestion.selectors import WP_THUMBNAIL_HOSTS

log = logging.getLogger(__name__)

_WP_THUMB_SUFFIX_RE = re.compile(r"-\d+x\d+(\.\w+)$")


def full_res_wp_image(url: str | None) -> str | None:
    """Strip the WordPress -WxH thumbnail suffix from a WP_THUMBNAIL_HOSTS image URL
    so we store the full-resolution original, not the listing thumbnail.

    Host-gated to WP_THUMBNAIL_HOSTS (concert.ee, kumu.ekm.ee); the ``\\.\\w+$``
    anchor is an extra guard.
    """
    if not url or not any(h in url for h in WP_THUMBNAIL_HOSTS):
        return url
    return _WP_THUMB_SUFFIX_RE.sub(r"\1", url)


def og_title(soup: BeautifulSoup) -> str | None:
    """Return og:title content, or None if absent."""
    tag = soup.find("meta", property="og:title")
    if tag and isinstance(tag, Tag):
        content = tag.get("content")
        if isinstance(content, str):
            return content.strip() or None
    return None


def attr_str(tag: Tag, name: str) -> str:
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


def first_image_url(img_tag: Tag) -> str | None:
    """Return a usable image URL from a (possibly lazy-loaded) <img> tag.

    Lazy-loaded images carry a placeholder data: URI in ``src`` and the real
    URL(s) in ``data-srcset``; fall back to the first ``data-srcset`` entry.
    """
    src = attr_str(img_tag, "src")
    if src and not src.startswith("data:"):
        return src
    srcset = attr_str(img_tag, "data-srcset")
    if srcset:
        first = srcset.split(",")[0].strip().split(" ")[0]
        return first or None
    return None


def next_occurrence_year(month: int, day: int, today: date | None = None) -> int:
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

    def extract_localized_important_info(
        self, soup: BeautifulSoup, locale: str
    ) -> str | None:
        """Return localized important_info for one locale variant page. No-op by default."""
        return None

    def extract_localized_text(
        self, soup: BeautifulSoup
    ) -> tuple[str | None, str | None]:
        """Return (title, description) for one locale variant page.

        Default reads schema.org Event JSON-LD (works for Piletilevi/Fienta).
        KUMU and ECH override this to use og:title + CSS selectors instead.
        """
        return extract_jsonld_event_text(soup)

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

        log.info("%s fetched %d events", self.source.slug, len(cards))
        return cards

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
            url_locale = locale_from_url_path(detail_url, LOCALIZED_TEXT_HTML_LOCALES)
            detail_host = urlsplit(detail_url).hostname
            loc_titles: dict[str, str] = {}
            loc_descs: dict[str, str] = {}
            loc_infos: dict[str, str] = {}
            for locale, loc_url in locale_urls.items():
                if locale == url_locale or loc_url == detail_url:
                    # Reuse already-loaded soup — this page IS the locale variant
                    loc_name, loc_desc = self.extract_localized_text(detail_soup)
                    loc_info = self.extract_localized_important_info(detail_soup, locale)
                else:
                    try:
                        await asyncio.sleep(HTML_LISTING_LOCALE_FETCH_DELAY_SECONDS)
                        loc_resp = await http_get(client, loc_url)
                        # Reject pages that redirected off-host or to site root
                        final_parsed = urlsplit(str(loc_resp.url))
                        if final_parsed.hostname != detail_host:
                            log.debug(
                                "%s locale fetch redirected off-host locale=%s url=%s",
                                self.source.slug, locale, loc_url,
                            )
                            continue
                        if final_parsed.path in ("/", ""):
                            log.debug(
                                "%s locale page is site root locale=%s url=%s",
                                self.source.slug, locale, loc_url,
                            )
                            continue
                        loc_soup = BeautifulSoup(loc_resp.text, "html.parser")
                        loc_name, loc_desc = self.extract_localized_text(loc_soup)
                        loc_info = self.extract_localized_important_info(loc_soup, locale)
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
                if loc_info:
                    loc_infos[locale] = loc_info
            if loc_titles:
                card["title_localized"] = loc_titles
            if loc_descs:
                card["description_localized"] = loc_descs
            if loc_infos:
                card["important_info_localized"] = loc_infos

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
        loc_infos = raw.get("important_info_localized") or {}
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
            important_info_localized=loc_infos if loc_infos else None,
        )

    def get_raw_external_id(self, raw: dict[str, Any]) -> str | None:
        return raw.get("external_id")
