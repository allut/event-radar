import json
import logging
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup

from app.constants import HTTP_TIMEOUT_SECONDS, HTTP_USER_AGENT, JSONLD_EVENT_TYPES
from app.ingestion.base import (
    NormalizedEvent,
    SourceAdapter,
    _http_get,
    _parse_dt,
    normalize_currency,
)

log = logging.getLogger(__name__)


class JsonLdAdapter(SourceAdapter):
    """Fetches a listing page and extracts schema.org Event JSON-LD blocks.

    source.config must contain:
      url: str — the events listing page URL

    Subclass and override normalize() for site-specific quirks, or
    override fetch_raw() to add a CSS-selector fallback when JSON-LD is absent.
    """

    @property
    def listing_url(self) -> str:
        return self.source.config["url"]

    def get_raw_external_id(self, raw: dict[str, Any]) -> Optional[str]:
        v = raw.get("url") or raw.get("@id") or ""
        return str(v) if v else None

    async def fetch_raw(self) -> list[dict[str, Any]]:
        url = self.listing_url
        try:
            async with httpx.AsyncClient(
                timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True
            ) as client:
                response = await _http_get(
                    client, url, headers={"User-Agent": HTTP_USER_AGENT}
                )
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            log.error(
                "jsonld fetch failed source=%s url=%s: %s", self.source.slug, url, exc
            )
            raise
        events = _extract_jsonld_events(response.text)
        log.info(
            "jsonld source=%s url=%s extracted=%d events",
            self.source.slug,
            url,
            len(events),
        )
        return events

    def normalize(self, raw: dict[str, Any]) -> Optional[NormalizedEvent]:
        title = raw.get("name") or ""
        if not title:
            return None

        external_id = raw.get("url") or raw.get("@id") or ""
        if not external_id:
            return None

        raw_start = raw.get("startDate") or raw.get("startTime") or ""
        if not raw_start:
            return None
        starts_at = _parse_dt(str(raw_start))
        if starts_at is None:
            return None

        raw_end = raw.get("endDate") or raw.get("endTime")
        ends_at = _parse_dt(str(raw_end)) if raw_end else None

        venue_name, venue_address, lat, lng = _parse_location(raw.get("location"))

        price_min, price_max, currency = _parse_offers(raw.get("offers"))

        image = raw.get("image")
        if isinstance(image, list):
            image = image[0] if image else None
        if isinstance(image, dict):
            image = image.get("url")
        image_url = str(image) if image else None

        return NormalizedEvent(
            external_id=external_id,
            title=str(title),
            description=raw.get("description"),
            starts_at=starts_at,
            ends_at=ends_at,
            venue_name=venue_name,
            venue_address=venue_address,
            lat=lat,
            lng=lng,
            url=raw.get("url"),
            image_url=image_url,
            price_min=price_min,
            price_max=price_max,
            currency=normalize_currency(
                currency, price_min is not None or price_max is not None
            ),
        )


class TelliskiviAdapter(JsonLdAdapter):
    """telliskivi.cc/en/events/ — schema.org JSON-LD events listing."""


class KultuurikateldAdapter(JsonLdAdapter):
    """kultuurikatel.ee/en/events/ — schema.org JSON-LD events listing."""


class FotografiskaAdapter(JsonLdAdapter):
    """tallinn.fotografiska.com/en/events — schema.org JSON-LD events listing."""


class KumuAdapter(JsonLdAdapter):
    """kumu.ekm.ee/en/whats-on/ — schema.org JSON-LD events listing."""


class EstoniaConcertHallAdapter(JsonLdAdapter):
    """concert.ee/en/events/ — Estonia Concert Hall schema.org JSON-LD events listing."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_jsonld_events(html: str) -> list[dict[str, Any]]:
    """Return all schema.org Event items found in JSON-LD script tags."""
    soup = BeautifulSoup(html, "html.parser")
    events: list[dict[str, Any]] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        _collect_events(data, events)
    return events


def _collect_events(data: Any, out: list[dict[str, Any]]) -> None:
    """Recursively collect Event-typed items from a JSON-LD value."""
    if isinstance(data, list):
        for item in data:
            _collect_events(item, out)
        return
    if not isinstance(data, dict):
        return
    event_type = data.get("@type", "")
    if isinstance(event_type, list):
        event_type = event_type[0] if event_type else ""
    if event_type in JSONLD_EVENT_TYPES:
        out.append(data)
    # @graph may wrap multiple typed nodes — recurse so nested @graph is handled
    graph = data.get("@graph")
    if graph:
        _collect_events(graph, out)


def _parse_location(
    location: Any,
) -> tuple[Optional[str], Optional[str], Optional[float], Optional[float]]:
    if isinstance(location, list):
        location = location[0] if location else None
    if not isinstance(location, dict):
        return (str(location) if location else None), None, None, None

    venue_name: Optional[str] = location.get("name") or None
    addr = location.get("address") or {}
    if isinstance(addr, dict):
        parts = [addr.get("streetAddress"), addr.get("addressLocality")]
        venue_address: Optional[str] = ", ".join(p for p in parts if p) or None
    else:
        venue_address = str(addr) or None

    geo = location.get("geo") or {}
    lat = _to_float(geo.get("latitude")) if isinstance(geo, dict) else None
    lng = _to_float(geo.get("longitude")) if isinstance(geo, dict) else None
    return venue_name, venue_address, lat, lng


def _parse_offers(
    offers: Any,
) -> tuple[Optional[float], Optional[float], Optional[str]]:
    if offers is None:
        return None, None, None
    if isinstance(offers, dict):
        offers = [offers]
    if not isinstance(offers, list):
        return None, None, None

    price_min: Optional[float] = None
    price_max: Optional[float] = None
    currency: Optional[str] = None

    for offer in offers:
        if not isinstance(offer, dict):
            continue
        p = _to_float(offer.get("price"))
        if p is not None:
            price_min = p if price_min is None else min(price_min, p)
            price_max = p if price_max is None else max(price_max, p)
        if currency is None:
            currency = offer.get("priceCurrency") or None

    return price_min, price_max, currency


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
