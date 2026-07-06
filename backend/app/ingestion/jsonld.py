"""schema.org Event JSON-LD extraction from detail pages.

Location, offers (price tiers), and name/description readers shared by the
Fienta/Piletilevi adapters and the daily detail-refetch sync.
"""

import json
from typing import Any

from bs4 import BeautifulSoup

from app.constants import (
    LOCALIZED_TEXT_MAX_DESC_CHARS,
    LOCALIZED_TEXT_MAX_TITLE_CHARS,
)

def _coerce_float(value: Any) -> float | None:
    """Coerce a JSON-LD numeric field (number or numeric string) to float."""
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _jsonld_event_items(data: Any) -> list[dict[str, Any]]:
    """Flatten a parsed JSON-LD document (plain item, list, or ``@graph``) to dicts."""
    if isinstance(data, dict) and "@graph" in data:
        items = data["@graph"]
    else:
        items = data
    if not isinstance(items, list):
        items = [items]
    return [item for item in items if isinstance(item, dict)]


def extract_jsonld_event_location(soup: BeautifulSoup) -> dict[str, Any] | None:
    """Find a schema.org ``Event``'s ``location`` in <script type="application/ld+json">.

    Returns ``{"venue_name", "venue_address", "lat", "lng"}`` (any value may be
    ``None``) from the first ``Event`` whose ``location`` is a ``Place``, or
    ``None`` if no such block is found. ``venue_address`` joins
    ``streetAddress``/``addressLocality``/``addressRegion`` with ", ".
    """
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (TypeError, ValueError):
            continue
        for item in _jsonld_event_items(data):
            item_type = item.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]
            if "Event" not in types:
                continue
            location = item.get("location")
            if not isinstance(location, dict):
                continue
            address = location.get("address")
            address_parts: list[str] = []
            if isinstance(address, dict):
                for key in ("streetAddress", "addressLocality", "addressRegion"):
                    value = address.get(key)
                    if value:
                        address_parts.append(str(value))
            geo = location.get("geo")
            if isinstance(geo, dict):
                lat_raw = geo.get("latitude")
                lng_raw = geo.get("longitude")
            else:
                lat_raw = location.get("latitude")
                lng_raw = location.get("longitude")
            return {
                "venue_name": location.get("name"),
                "venue_address": ", ".join(address_parts) or None,
                "lat": _coerce_float(lat_raw),
                "lng": _coerce_float(lng_raw),
            }
    return None


def extract_jsonld_event_offers(
    soup: BeautifulSoup,
) -> tuple[float | None, float | None, str | None, bool]:
    """Return ``(min_price, max_price, currency, has_free_tier)`` from schema.org
    ``Event`` ``offers[]``.

    Reads all ``Offer`` entries from the first JSON-LD ``Event`` block. price_min/max
    bound the PAID offers only; a zero-priced offer whose ``availability`` is
    ``SoldOut`` is a placeholder (Fienta collapses a sold-out event to a single
    ``{price: 0, availability: SoldOut}`` offer) and is ignored entirely — not
    counted as paid or free. A genuine zero-priced, in-stock offer (e.g. a
    Member/Companion tier) sets ``has_free_tier`` alongside any paid offers found.
    Returns ``(None, None, None, False)`` when no offers or no usable prices are
    found in any Event block.
    """
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (TypeError, ValueError):
            continue
        for item in _jsonld_event_items(data):
            item_type = item.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]
            if "Event" not in types:
                continue
            offers_raw = item.get("offers") or []
            if isinstance(offers_raw, dict):
                offers_raw = [offers_raw]
            paid_prices: list[float] = []
            has_free_offer = False
            currency: str | None = None
            for offer in offers_raw:
                if not isinstance(offer, dict):
                    continue
                price = _coerce_float(offer.get("price"))
                if price is None:
                    continue
                availability = str(offer.get("availability") or "")
                sold_out = availability.endswith("SoldOut")
                if price == 0 and sold_out:
                    continue  # placeholder — not a real offer
                if price > 0:
                    paid_prices.append(price)
                    if currency is None:
                        cur_raw = offer.get("priceCurrency")
                        if cur_raw:
                            currency = str(cur_raw).upper()
                else:
                    has_free_offer = True
            if paid_prices:
                return (min(paid_prices), max(paid_prices), currency, has_free_offer)
            if has_free_offer:
                return (0.0, 0.0, None, False)
            continue  # nothing usable in this block — try next Event item
    return (None, None, None, False)


def extract_jsonld_event_text(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Return ``(name, description)`` from the first schema.org ``Event`` JSON-LD block.

    Falls back to the page ``<h1>`` for name when the JSON-LD block has no ``name``
    field. Returns ``(None, None)`` when no ``Event`` block is found.
    """
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (TypeError, ValueError):
            continue
        for item in _jsonld_event_items(data):
            item_type = item.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]
            if "Event" not in types:
                continue
            name_raw = item.get("name")
            name: str | None = name_raw.strip()[:LOCALIZED_TEXT_MAX_TITLE_CHARS] or None if isinstance(name_raw, str) else None
            desc_raw = item.get("description")
            desc: str | None = desc_raw.strip()[:LOCALIZED_TEXT_MAX_DESC_CHARS] or None if isinstance(desc_raw, str) else None
            if name is None:
                h1 = soup.find("h1")
                if h1:
                    name = h1.get_text(strip=True) or None
            return (name, desc)
    return (None, None)
