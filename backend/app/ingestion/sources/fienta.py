import asyncio
import http
import logging
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.constants import (
    DETAIL_FETCH_CONCURRENCY,
    FIENTA_CITY_FILTER,
    FIENTA_MAX_DETAIL_FETCHES,
    FIENTA_MAX_PAGES,
    FIENTA_MIN_REQUEST_INTERVAL_SECONDS,
    HTML_PARSER,
    HTTP_TIMEOUT_SECONDS,
    LOCALIZED_TEXT_FIENTA_LOCALES,
)
from app.ingestion.selectors import (
    FIENTA_CITY_FROM_ADDRESS_RE,
    FIENTA_DESCRIPTION_SELECTOR,
    FIENTA_POSTAL_CODE_RE,
)
from app.ingestion.adapter import (
    NormalizedEvent,
    SourceAdapter,
    coords_in_estonia,
    parse_dt,
)
from app.ingestion.http_client import AsyncRateLimiter, host_guard_hook, http_get
from app.ingestion.jsonld import (
    extract_jsonld_event_text,
    location_from_jsonld_items,
    offers_from_jsonld_items,
    parse_jsonld_event_items,
    text_from_jsonld_items,
)
from app.ingestion.locale_urls import (
    locale_from_html_lang,
    locale_from_url_path,
    fetch_locale_variants,
)
from app.ingestion.pricing import parse_price_from_string
from app.ingestion.sanitize import sanitize_html

log = logging.getLogger(__name__)


# \w with UNICODE matches any Unicode letter (covers Estonian, Latvian, Lithuanian diacritics).
_CITY_FROM_ADDRESS_RE = re.compile(FIENTA_CITY_FROM_ADDRESS_RE, re.UNICODE)


def address_city(address: str) -> str | None:
    """Extract city token from a Fienta-style address string, or None if not parseable."""
    m = _CITY_FROM_ADDRESS_RE.search(address)
    return m.group(1) if m else None


def _parse_detail_fields(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the _detail dict's location + offers fields from a detail page's
    pre-parsed JSON-LD ``Event`` items (parse once via parse_jsonld_event_items,
    per jsonld.py's docstring — Big-O audit #5, item 2.1)."""
    loc = location_from_jsonld_items(items)
    price_min, price_max, currency, has_free_tier = offers_from_jsonld_items(items)
    return {
        "venue_name": loc.get("venue_name") if loc else None,
        "venue_address": loc.get("venue_address") if loc else None,
        "lat": loc.get("lat") if loc else None,
        "lng": loc.get("lng") if loc else None,
        "price_min": price_min,
        "price_max": price_max,
        "currency": currency,
        "has_free_tier": has_free_tier,
    }


def _extract_locale_text(
    soup: BeautifulSoup, _locale: str
) -> tuple[str | None, str | None, str | None]:
    """Locale-page extractor for fetch_locale_variants: JSON-LD title, and
    DOM rich-text HTML (preferred) or JSON-LD plain text for the description.
    """
    title, jsonld_desc = extract_jsonld_event_text(soup)
    rich_text_tag = soup.select_one(FIENTA_DESCRIPTION_SELECTOR)
    if rich_text_tag:
        desc = sanitize_html(rich_text_tag.decode_contents())
    else:
        desc = sanitize_html(jsonld_desc)
    return title, desc, None


def is_target_city(address: str | None) -> bool:
    """Keep only FIENTA_CITY_FILTER (Tallinn) or city-less, assumed-Tallinn addresses.

    Allowlist, not denylist: drops any address whose parseable city token is not
    FIENTA_CITY_FILTER, so unknown Estonian towns and foreign cities are excluded
    without needing to enumerate them. City-less addresses (no postal-code pattern)
    are kept — usually a Tallinn venue name with no street/postal in the string.

    Known limitation (acceptable — all observed Fienta data carries postal codes):
    an address with a city but no postal code can't be parsed, so it is kept.
    """
    if not address:
        return True
    city = address_city(address)
    if city is None:
        return True  # unparseable → keep
    return city == FIENTA_CITY_FILTER


_POSTAL_CODE_RE = re.compile(FIENTA_POSTAL_CODE_RE)


def _has_postal_code(address: str | None) -> bool:
    return bool(address and _POSTAL_CODE_RE.search(address))


def _merge_venue(
    raw: dict[str, Any], detail: dict[str, Any]
) -> tuple[str | None, str | None]:
    """Merge listing + detail venue fields per the fixed authority table.

    venue_name: listing wins, detail fallback. venue_address: prefer whichever
    side carries a 5-digit postal code; else listing wins, detail fills empty.
    """
    venue_raw = raw.get("venue") or {}
    if isinstance(venue_raw, dict):
        listing_venue_name = venue_raw.get("name")
        address_candidate = venue_raw.get("address")
    else:
        listing_venue_name = str(venue_raw) or None
        address_candidate = raw.get("address")
    listing_venue_address = (
        address_candidate if isinstance(address_candidate, str) else None
    )

    venue_name = listing_venue_name or detail.get("venue_name") or None

    detail_addr: str | None = detail.get("venue_address")
    if _has_postal_code(listing_venue_address):
        venue_address: str | None = listing_venue_address
    elif _has_postal_code(detail_addr):
        venue_address = detail_addr
    else:
        venue_address = listing_venue_address or detail_addr or None
    return venue_name, venue_address


def _merge_location(detail: dict[str, Any]) -> tuple[float | None, float | None]:
    """lat/lng come only from detail JSON-LD, bbox-gated to Estonia; None
    otherwise (the geocode pass fills them later)."""
    if detail:
        d_lat: float | None = detail.get("lat")
        d_lng: float | None = detail.get("lng")
        if d_lat is not None and d_lng is not None and coords_in_estonia(d_lat, d_lng):
            return d_lat, d_lng
    return None, None


def _merge_price(
    raw: dict[str, Any], detail: dict[str, Any]
) -> tuple[float | None, float | None, str | None, bool]:
    """Merge listing + detail prices; returns (min, max, currency, has_free_tier).

    The deterministic listing parse is the authoritative baseline, overridden
    per-bound by a present detail offer price. A listing parsed as plain
    "Free" (both bounds 0, no paid tier) means admission itself is free — the
    free floor survives even when the detail page reveals an optional paid
    ticket (e.g. an open-mic's €10 support ticket): price_min stays 0, only
    price_max is raised to the detail's paid ceiling.
    """
    listing_price_min, listing_price_max, listing_currency, listing_has_free_tier = (
        parse_price_from_string(raw.get("price_from_string"))
    )
    detail_price_min: float | None = detail.get("price_min") if detail else None
    detail_price_max: float | None = detail.get("price_max") if detail else None
    detail_has_free_tier = bool(detail.get("has_free_tier")) if detail else False

    has_free_tier = listing_has_free_tier or detail_has_free_tier

    if listing_price_min == 0 and listing_price_max == 0 and not listing_has_free_tier:
        price_min: float | None = 0.0
        price_max: float | None = (
            detail_price_max if detail_price_max is not None else listing_price_max
        )
    else:
        price_min = detail_price_min if detail_price_min is not None else listing_price_min
        price_max = detail_price_max if detail_price_max is not None else listing_price_max

    currency: str | None = listing_currency or (detail.get("currency") or None)
    return price_min, price_max, currency, has_free_tier


class FientaAdapter(SourceAdapter):
    """Fetches events from Fienta public API for all organizer IDs in source.config.

    source.config must contain:
      organizer_ids: list[int] — Fienta numeric organizer IDs

    Organizers listed in source.config["stale_organizer_ids"] (set by
    app.ingestion.organizer_sync.sync_fienta_organizers) are skipped here —
    they are still re-probed by the weekly organizer sync so a revival is
    detected, but hourly ingest stops polling a known-dead organizer.

    Pagination: handles both link-based (`links.next`) and meta-based
    (`meta.current_page` / `meta.last_page`) pagination automatically.
    Plain list responses (no pagination envelope) are also supported.

    For each new event (not yet in event_sources), the adapter fetches the
    detail page concurrently and attaches parsed JSON-LD data under
    ``raw["_detail"]``. normalize() merges listing + detail per a fixed
    authority table; absent _detail degrades to listing-only behavior.

    The httpx.AsyncClient sets follow_redirects=True: Fienta detail pages
    302-redirect to a localized path (fienta.com/<slug> -> fienta.com/{et,ru,lv}/
    <slug>); without it every detail fetch raised and was silently dropped.
    httpx's redirect handling has no same-origin restriction on its own — a
    malicious Location header could point a followed redirect at an arbitrary
    host — so a `request` event hook (`host_guard_hook`, `app/ingestion/http_client.py`)
    re-validates the host of *every* request the client sends, including each
    redirect hop, against base_host. This is the actual SSRF enforcement for
    the redirect case; the pre-fetch checks in `_fetch_organizer`/`_fetch_detail`
    remain as defense-in-depth on the un-redirected URL.

    All listing and detail requests share one AsyncRateLimiter per fetch_raw()
    call (FIENTA_MIN_REQUEST_INTERVAL_SECONDS) to proactively pace requests
    below Fienta's rate limit; a 429 also pushes the limiter's backoff out so
    remaining organizers/details pause together instead of piling on.
    """

    async def fetch_raw(self, known_ids: set[str]) -> list[dict[str, Any]]:
        stale_ids: set[int] = set(self.source.config.get("stale_organizer_ids", []))
        organizer_ids: list[int] = [
            oid
            for oid in self.source.config.get("organizer_ids", [])
            if oid not in stale_ids
        ]
        base_url: str = self.source.config.get("base_url", settings.FIENTA_BASE_URL)
        base_host = urlparse(base_url).hostname
        all_events: list[dict[str, Any]] = []

        errors: list[Exception] = []
        limiter = AsyncRateLimiter(FIENTA_MIN_REQUEST_INTERVAL_SECONDS)
        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT_SECONDS,
            follow_redirects=True,
            event_hooks={"request": [host_guard_hook(base_host)]},
        ) as client:
            for org_id in organizer_ids:
                try:
                    all_events.extend(
                        await self._fetch_organizer(client, base_url, org_id, limiter)
                    )
                except httpx.HTTPStatusError as exc:
                    log.warning(
                        "fienta organizer=%s failed: %s",
                        org_id,
                        exc.response.status_code,
                    )
                    errors.append(exc)
                    if exc.response.status_code == http.HTTPStatus.TOO_MANY_REQUESTS:
                        limiter.backoff(FIENTA_MIN_REQUEST_INTERVAL_SECONDS)
                except httpx.RequestError as exc:
                    log.warning("fienta organizer=%s network error: %s", org_id, exc)
                    errors.append(exc)

            # Partial tolerance: if some organizers succeeded we return what we have
            # so a single flaky organizer doesn't suppress a real run. We only raise
            # (which marks the IngestionRun as error) when every organizer failed.
            if not all_events and errors:
                raise errors[0]

            # Forward-only: drop already-stored events before detail fetch and
            # before returning, so each event is enriched exactly once, re-runs
            # stay cheap, and known events never become a duplicate raw_events row.
            semaphore = asyncio.Semaphore(DETAIL_FETCH_CONCURRENCY)

            new_items = [
                item for item in all_events
                if str(item.get("id", "")) not in known_ids
            ]
            if len(new_items) > FIENTA_MAX_DETAIL_FETCHES:
                log.warning(
                    "fienta: %d new items exceed detail-fetch cap %d — truncating "
                    "(self-healing: skipped items stay 'new' and are picked up "
                    "next run via known_ids)",
                    len(new_items),
                    FIENTA_MAX_DETAIL_FETCHES,
                )
                new_items = new_items[:FIENTA_MAX_DETAIL_FETCHES]
            results = await asyncio.gather(
                *[
                    self._fetch_detail(client, item, base_host, semaphore, limiter)
                    for item in new_items
                ],
                return_exceptions=True,
            )
            # _fetch_detail only swallows httpx errors internally — anything else
            # escaping it is an unexpected bug. return_exceptions=True keeps one
            # item's crash from cancelling the others' in-flight fetches, but the
            # bug must still surface (log + propagate) rather than vanish silently,
            # per the "never swallow exceptions in fetch_raw()" invariant.
            unexpected = [r for r in results if isinstance(r, BaseException)]
            for detail_exc in unexpected:
                log.error(
                    "fienta detail fetch task raised unexpectedly: %s", detail_exc
                )
            if unexpected:
                raise unexpected[0]

        return new_items

    async def _fetch_organizer(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        org_id: int,
        limiter: AsyncRateLimiter | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all pages for a single organizer against a shared FIENTA_MAX_PAGES budget."""
        collected: list[dict[str, Any]] = []
        base_host = urlparse(base_url).hostname  # hostname only, excludes port
        budget = FIENTA_MAX_PAGES  # total requests allowed across all pagination styles

        url: str = base_url
        params: dict[str, Any] | None = {"organizer": org_id}
        page = 1  # used only for meta-based pagination

        while url and budget > 0:
            if limiter is not None:
                await limiter.acquire()
            # params=None preserves the URL's existing query string (e.g. links.next
            # already encodes all params); params=dict merges/replaces the query string.
            response = await http_get(client, url, params=params)
            budget -= 1
            data = response.json()

            if isinstance(data, list):
                collected.extend(data)
                break  # plain list — no pagination

            events = data.get("data", data.get("events", []))
            collected.extend(events)

            # link-based pagination: follow links.next (validated against base host)
            next_url = (data.get("links") or {}).get("next") or ""
            if next_url:
                if urlparse(next_url).hostname != base_host:
                    log.error(
                        "fienta: links.next host mismatch (SSRF guard), stopping pagination"
                    )
                    break
                url = next_url
                params = None  # next URL already encodes all params
                continue

            # meta-based pagination: advance page counter.
            meta = data.get("meta") or {}
            last = meta.get("last_page")
            if last is None:
                break  # no links.next and no last_page → nothing more to follow
            current = meta.get("current_page")
            if current is None:
                # Some responses mix link+meta styles and omit current_page. Fall
                # back to the local requested-page counter, but log so a silent
                # truncation/loop becomes visible instead of being assumed away.
                # The FIENTA_MAX_PAGES budget still bounds the loop.
                log.warning(
                    "fienta organizer=%s: meta.current_page missing; "
                    "falling back to local page counter (page=%s, last_page=%s)",
                    org_id,
                    page,
                    last,
                )
                current = page
            if current >= last:
                break
            page = current + 1
            params = {"organizer": org_id, "page": page}

        return collected

    async def _fetch_detail(
        self,
        client: httpx.AsyncClient,
        item: dict[str, Any],
        base_host: str | None,
        semaphore: asyncio.Semaphore,
        limiter: AsyncRateLimiter,
    ) -> None:
        """Fetch the event detail page and attach parsed JSON-LD under item["_detail"].

        Failures are logged and silently dropped — the caller degrades to listing-only.
        SSRF guard: only fetches when the item URL's host matches the Fienta base host.
        """
        url = item.get("url") or item.get("link") or ""
        if not url:
            return
        if urlparse(url).hostname != base_host:
            log.warning(
                "fienta: detail URL host mismatch (SSRF guard), skipping id=%s",
                item.get("id"),
            )
            return
        async with semaphore:
            await limiter.acquire()
            try:
                response = await http_get(client, url)
                soup = BeautifulSoup(response.text, HTML_PARSER)
                jsonld_items = parse_jsonld_event_items(soup)
                item["_detail"] = _parse_detail_fields(jsonld_items)

                # The canonical URL 302s to a locale-prefixed path (e.g. /et/slug).
                # That redirected URL tells us which language the listing API returned.
                primary_locale = locale_from_url_path(
                    str(response.url), LOCALIZED_TEXT_FIENTA_LOCALES
                ) or locale_from_html_lang(soup, LOCALIZED_TEXT_FIENTA_LOCALES)

                loc_titles: dict[str, str] = {}
                loc_descs: dict[str, str] = {}
                if primary_locale:
                    # Reuse this page for the primary locale; the listing API HTML
                    # is authoritative for its description, with JSON-LD plain
                    # text as fallback when the API field is absent.
                    loc_name, jsonld_desc = text_from_jsonld_items(jsonld_items, soup)
                    html_desc = sanitize_html(item.get("description")) or sanitize_html(jsonld_desc)
                    if loc_name:
                        loc_titles[primary_locale] = loc_name
                    if html_desc:
                        loc_descs[primary_locale] = html_desc

                fetched_titles, fetched_descs, _ = await fetch_locale_variants(
                    client,
                    soup,
                    url,
                    LOCALIZED_TEXT_FIENTA_LOCALES,
                    _extract_locale_text,
                    fetch=http_get,
                    wait=limiter.acquire,
                    source_label="fienta",
                    base_locale=primary_locale,
                    wanted_locales=set(LOCALIZED_TEXT_FIENTA_LOCALES)
                    - ({primary_locale} if primary_locale else set()),
                )
                loc_titles.update(fetched_titles)
                loc_descs.update(fetched_descs)
                if loc_titles or loc_descs:
                    item["_detail_localized"] = {
                        "title": loc_titles,
                        "description": loc_descs,
                    }
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == http.HTTPStatus.TOO_MANY_REQUESTS:
                    limiter.backoff(FIENTA_MIN_REQUEST_INTERVAL_SECONDS)
                log.warning(
                    "fienta: detail fetch failed id=%s url=%s: %s",
                    item.get("id"),
                    url,
                    exc,
                )
            except httpx.RequestError as exc:
                log.warning(
                    "fienta: detail fetch network error id=%s url=%s: %s",
                    item.get("id"),
                    url,
                    exc,
                )
            except ValueError as exc:
                # host_guard_hook's SSRF guard raises ValueError when a redirect
                # hop targets an unexpected host — an expected per-item rejection,
                # not a bug, so it degrades to listing-only like the httpx cases.
                log.warning(
                    "fienta: detail fetch host mismatch (SSRF guard) id=%s url=%s: %s",
                    item.get("id"),
                    url,
                    exc,
                )
            # Anything else (e.g. a bug in JSON-LD/BeautifulSoup parsing) is not a
            # transient fetch failure — let it propagate so the gather() in
            # fetch_raw() surfaces it, per the "never swallow exceptions in
            # fetch_raw()" invariant, instead of silently degrading to
            # listing-only for every future run.

    def normalize(self, raw: dict[str, Any]) -> NormalizedEvent | None:
        title = raw.get("name") or raw.get("title") or ""
        if not title:
            return None

        external_id = str(raw.get("id", ""))
        if not external_id:
            return None

        raw_start = (
            raw.get("starts_at") or raw.get("start_date") or raw.get("start_time")
        )
        if not raw_start:
            return None
        starts_at = parse_dt(str(raw_start))
        if starts_at is None:
            return None

        raw_end = raw.get("ends_at") or raw.get("end_date") or raw.get("end_time")
        ends_at = parse_dt(str(raw_end)) if raw_end else None

        # Merge table — applied when detail is present; listing-only when absent.
        detail: dict[str, Any] = raw.get("_detail") or {}

        venue_name, venue_address = _merge_venue(raw, detail)
        if not is_target_city(venue_address):
            return None

        lat, lng = _merge_location(detail)
        price_min, price_max, currency, has_free_tier = _merge_price(raw, detail)

        detail_localized = raw.get("_detail_localized") or {}
        loc_titles = detail_localized.get("title") or {}
        loc_descs = detail_localized.get("description") or {}

        return NormalizedEvent(
            external_id=external_id,
            title=str(title),
            description=sanitize_html(raw.get("description") or raw.get("body")),
            starts_at=starts_at,
            ends_at=ends_at,
            venue_name=venue_name or None,
            venue_address=venue_address or None,
            lat=lat,
            lng=lng,
            url=raw.get("url") or raw.get("link"),
            image_url=raw.get("image_url")
            or raw.get("image")
            or raw.get("cover_image"),
            price_min=price_min,
            price_max=price_max,
            currency=currency,
            has_free_tier=has_free_tier,
            title_localized=loc_titles if loc_titles else None,
            description_localized=loc_descs if loc_descs else None,
        )
