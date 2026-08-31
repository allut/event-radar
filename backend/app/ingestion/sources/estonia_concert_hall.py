"""Estonia Concert Hall adapter — concert.ee/en/ (AJAX-loaded all-Estonia listing)."""

import base64
import json
import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
from bs4 import BeautifulSoup

from app.constants import (
    DEFAULT_CURRENCY,
    HTTP_METHOD_POST,
    TALLINN_TZ,
)
from app.ingestion.http_client import http_post
from app.ingestion.pricing import to_float
from app.ingestion.sanitize import sanitize_html
from app.ingestion.selectors import (
    ECH_SITE_NAME_ET,
    ECH_SITE_TITLE_SUFFIX,
    ESTONIA_CONCERT_HALL_AJAX_ACTION,
    ESTONIA_CONCERT_HALL_AJAX_PATH,
    ESTONIA_CONCERT_HALL_DATE_RE,
    ESTONIA_CONCERT_HALL_DATE_SELECTOR,
    ESTONIA_CONCERT_HALL_DESCRIPTION_SELECTOR,
    ESTONIA_CONCERT_HALL_IMAGE_SELECTOR,
    ESTONIA_CONCERT_HALL_IMAGE_URL_RE,
    ESTONIA_CONCERT_HALL_LOCATION_SELECTOR,
    ESTONIA_CONCERT_HALL_MAX_EVENTS,
    ESTONIA_CONCERT_HALL_PID_RE,
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
    ESTONIA_CONCERT_HALL_VENUES,
    ESTONIA_CONCERT_HALL_VENUE_SELECTOR,
)
from app.ingestion.html_utils import attr_str, og_title_localized_text
from app.ingestion.sources.html_base import (
    HtmlListingAdapter,
    ListingRequest,
    OnceAsync,
    full_res_wp_image,
    next_occurrence_year,
)

log = logging.getLogger(__name__)

_CONCERT_DATE_RE = re.compile(ESTONIA_CONCERT_HALL_DATE_RE)
_CONCERT_IMAGE_URL_RE = re.compile(ESTONIA_CONCERT_HALL_IMAGE_URL_RE)
_CONCERT_PID_RE = re.compile(ESTONIA_CONCERT_HALL_PID_RE)


def estonia_concert_hall_localized_text(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Extract (title, description) from an ECH (concert.ee) detail page.

    Uses og:title (suffix-stripped) — ECH pages carry no JSON-LD Event block.
    Falls back to <h1> text when og:title is absent.
    """
    return og_title_localized_text(
        soup,
        site_name=ECH_SITE_NAME_ET,
        title_suffix=ECH_SITE_TITLE_SUFFIX,
        desc_selector=ESTONIA_CONCERT_HALL_DESCRIPTION_SELECTOR,
    )


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
    self._session (OnceAsync wrapping _bootstrap_session_key()) and cached on
    the adapter instance.
    """

    needs_detail = True
    extra_allowed_hosts = frozenset(
        {urlsplit(ESTONIA_CONCERT_HALL_PILETILEVI_URL).hostname}
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._session: OnceAsync[str] = OnceAsync(self._bootstrap_session_key)

    async def _bootstrap_session_key(self, client: httpx.AsyncClient) -> str | None:
        """Auth POST + JWT-claim extraction for the Piletilevi store session key.

        Token lifetime is ~15 min, comfortably covering one run's detail fetches.
        """
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
            return (
                _jwt_claim(token, ESTONIA_CONCERT_HALL_PILETILEVI_SESSION_CLAIM)
                if isinstance(token, str)
                else None
            )
        except (httpx.HTTPStatusError, httpx.RequestError, ValueError):
            return None

    def listing_request(self, page: int) -> ListingRequest | None:
        if page != 1:
            return None
        parts = urlsplit(str(self.source.config["url"]))
        ajax_url = f"{parts.scheme}://{parts.netloc}{ESTONIA_CONCERT_HALL_AJAX_PATH}"
        return ListingRequest(
            url=ajax_url,
            method=HTTP_METHOD_POST,
            data={
                "action": ESTONIA_CONCERT_HALL_AJAX_ACTION,
                "ek_ajax_count[]": str(ESTONIA_CONCERT_HALL_MAX_EVENTS),
            },
        )

    def parse_cards(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        cards: list[dict[str, Any]] = []
        for row in soup.select(ESTONIA_CONCERT_HALL_ROW_SELECTOR):
            link_tag = row.select_one(ESTONIA_CONCERT_HALL_TITLE_SELECTOR)
            href = attr_str(link_tag, "href") if link_tag else ""
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
                style = attr_str(image_tag, "style")
                match = _CONCERT_IMAGE_URL_RE.search(style)
                if match:
                    image_url = full_res_wp_image(
                        match.group(1).strip("'\"") or None
                    )

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

        year = next_occurrence_year(month, day)
        try:
            return datetime(year, month, day, hour, minute, tzinfo=TALLINN_TZ)
        except ValueError:
            return None

    def extract_localized_text(
        self, soup: BeautifulSoup
    ) -> tuple[str | None, str | None]:
        return estonia_concert_hall_localized_text(soup)

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
            card["description"] = sanitize_html(desc_tag.decode_contents())

        link = soup.find("a", href=_CONCERT_PID_RE)
        if link is None:
            return
        match = _CONCERT_PID_RE.search(attr_str(link, "href"))
        if not match:
            return
        pid = match.group(1)

        session_key = await self._session.get(client)
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
            if isinstance(s, dict) and (f := to_float(s.get("minPrice"))) is not None
        ]
        max_prices = [
            f
            for s in sections
            if isinstance(s, dict) and (f := to_float(s.get("maxPrice"))) is not None
        ]
        if not min_prices or not max_prices:
            return

        lo, hi = min(min_prices), max(max_prices)
        card["price_min"] = lo
        card["price_max"] = hi
        card["currency"] = DEFAULT_CURRENCY
