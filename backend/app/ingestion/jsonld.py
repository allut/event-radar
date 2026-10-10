"""schema.org Event JSON-LD extraction from detail pages.

Location, offers (price tiers), name/description, and organizer readers
shared by the Fienta/Piletilevi adapters and the daily detail-refetch sync.
"""

import json
import math
from typing import Any

from bs4 import BeautifulSoup

from app.constants import (
    CURRENCY_CODE_MAX_LEN,
    LOCALIZED_TEXT_MAX_DESC_CHARS,
    LOCALIZED_TEXT_MAX_TITLE_CHARS,
)
from app.ingestion.pricing import parse_bounded_price
from app.ingestion.selectors import (
    JSONLD_ADDRESS_FIELDS,
    JSONLD_EVENT_TYPE,
    JSONLD_SCRIPT_TYPE,
    JSONLD_SOLD_OUT_SUFFIX,
)

def _coerce_float(value: Any) -> float | None:
    """Coerce a JSON-LD numeric field (number or numeric string) to float."""
    if isinstance(value, bool):
        return None
    result: float | None = None
    if isinstance(value, int | float):
        result = float(value)
    elif isinstance(value, str):
        try:
            result = float(value)
        except ValueError:
            return None
    # "NaN"/"Infinity" parse as floats; they must never reach a Numeric column
    # or a coordinate comparison (OWASP audit M-6).
    return result if result is not None and math.isfinite(result) else None


def _jsonld_event_items(data: Any) -> list[dict[str, Any]]:
    """Flatten a parsed JSON-LD document (plain item, list, or ``@graph``) to dicts."""
    if isinstance(data, dict) and "@graph" in data:
        items = data["@graph"]
    else:
        items = data
    if not isinstance(items, list):
        items = [items]
    return [item for item in items if isinstance(item, dict)]


def parse_jsonld_graph_items(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Every schema.org item across a page's JSON-LD script blocks, with no
    ``@type`` filter — unlike ``parse_jsonld_event_items``, which keeps only
    ``Event``-typed items. Needed by callers that resolve an ``@id`` reference
    (e.g. Piletilevi's ``organizer`` field, app/claims/piletilevi_promoter.py)
    against a sibling node of a different type in the same ``@graph``.
    """
    items: list[dict[str, Any]] = []
    for script in soup.find_all("script", type=JSONLD_SCRIPT_TYPE):
        try:
            data = json.loads(script.string or "")
        except (TypeError, ValueError):
            continue
        items.extend(_jsonld_event_items(data))
    return items


def parse_jsonld_event_items(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Parse every <script type="application/ld+json"> block once and return the
    flattened list of schema.org ``Event``-typed item dicts, in document order.

    Callers needing more than one of location/offers/text from the same page
    (``refetch.py``, ``sources/fienta.py``) should call this once and pass the
    result to the ``*_from_items`` variants below, instead of calling the
    ``extract_jsonld_event_*(soup)`` wrappers repeatedly — each of those
    re-parses every script block from scratch.
    """
    items: list[dict[str, Any]] = []
    for script in soup.find_all("script", type=JSONLD_SCRIPT_TYPE):
        try:
            data = json.loads(script.string or "")
        except (TypeError, ValueError):
            continue
        for item in _jsonld_event_items(data):
            item_type = item.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]
            if JSONLD_EVENT_TYPE in types:
                items.append(item)
    return items


def location_from_jsonld_items(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Find the first item's ``location`` in a pre-parsed ``Event`` item list.

    Returns ``{"venue_name", "venue_address", "lat", "lng"}`` (any value may be
    ``None``) from the first item whose ``location`` is a ``Place``, or
    ``None`` if none carries one. ``venue_address`` joins
    ``streetAddress``/``addressLocality``/``addressRegion`` with ", ".
    """
    for item in items:
        location = item.get("location")
        if not isinstance(location, dict):
            continue
        address = location.get("address")
        address_parts: list[str] = []
        if isinstance(address, dict):
            for key in JSONLD_ADDRESS_FIELDS:
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


def extract_jsonld_event_location(soup: BeautifulSoup) -> dict[str, Any] | None:
    """Find a schema.org ``Event``'s ``location`` in <script type="application/ld+json">.

    Convenience wrapper over ``parse_jsonld_event_items`` +
    ``location_from_jsonld_items`` for callers that only need this one field —
    see ``parse_jsonld_event_items`` docstring for callers needing more than one.
    """
    return location_from_jsonld_items(parse_jsonld_event_items(soup))


def offers_from_jsonld_items(
    items: list[dict[str, Any]],
) -> tuple[float | None, float | None, str | None, bool]:
    """Return ``(min_price, max_price, currency, has_free_tier)`` from the first
    pre-parsed ``Event`` item's schema.org ``offers[]``.

    price_min/max bound the PAID offers only; a zero-priced offer whose
    ``availability`` is ``SoldOut`` is a placeholder (Fienta collapses a
    sold-out event to a single ``{price: 0, availability: SoldOut}`` offer)
    and is ignored entirely — not counted as paid or free. A genuine
    zero-priced, in-stock offer (e.g. a Member/Companion tier) sets
    ``has_free_tier`` alongside any paid offers found. Returns
    ``(None, None, None, False)`` when no offers or no usable prices are found
    in any Event item.
    """
    for item in items:
        offers_raw = item.get("offers") or []
        if isinstance(offers_raw, dict):
            offers_raw = [offers_raw]
        paid_prices: list[float] = []
        has_free_offer = False
        currency: str | None = None
        for offer in offers_raw:
            if not isinstance(offer, dict):
                continue
            price = parse_bounded_price(offer.get("price"))
            if price is None:
                continue
            availability = str(offer.get("availability") or "")
            sold_out = availability.endswith(JSONLD_SOLD_OUT_SUFFIX)
            if price == 0 and sold_out:
                continue  # placeholder — not a real offer
            if price > 0:
                paid_prices.append(price)
                if currency is None:
                    cur_raw = offer.get("priceCurrency")
                    if cur_raw:
                        cur_upper = str(cur_raw).upper()
                        # Bad data (e.g. "EUROS") is dropped, not truncated — a
                        # 4+-char value isn't a real code, and Event.currency
                        # is String(3) so an unbounded value aborts the write.
                        if len(cur_upper) <= CURRENCY_CODE_MAX_LEN:
                            currency = cur_upper
            else:
                has_free_offer = True
        if paid_prices:
            return (min(paid_prices), max(paid_prices), currency, has_free_offer)
        if has_free_offer:
            return (0.0, 0.0, None, False)
        continue  # nothing usable in this item — try next Event item
    return (None, None, None, False)


def extract_jsonld_event_offers(
    soup: BeautifulSoup,
) -> tuple[float | None, float | None, str | None, bool]:
    """Return ``(min_price, max_price, currency, has_free_tier)`` from schema.org
    ``Event`` ``offers[]``.

    Convenience wrapper over ``parse_jsonld_event_items`` +
    ``offers_from_jsonld_items`` — see ``parse_jsonld_event_items`` docstring
    for callers needing more than one field from the same page.
    """
    return offers_from_jsonld_items(parse_jsonld_event_items(soup))


def text_from_jsonld_items(
    items: list[dict[str, Any]], soup: BeautifulSoup
) -> tuple[str | None, str | None]:
    """Return ``(name, description)`` from the first pre-parsed ``Event`` item.

    Falls back to the page ``<h1>`` for name when the item has no ``name``
    field. ``soup`` is only consulted for that ``<h1>`` fallback. Returns
    ``(None, None)`` when no item is found.
    """
    for item in items:
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


def extract_jsonld_event_text(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Return ``(name, description)`` from the first schema.org ``Event`` JSON-LD block.

    Convenience wrapper over ``parse_jsonld_event_items`` +
    ``text_from_jsonld_items`` — see ``parse_jsonld_event_items`` docstring for
    callers needing more than one field from the same page.
    """
    return text_from_jsonld_items(parse_jsonld_event_items(soup), soup)


def organizer_from_jsonld_items(
    items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Return ``{"external_id", "name", "url"}`` from the first item's
    ``organizer`` (schema.org ``Organization``/``Person``), or ``None`` when
    no item carries one.

    ``external_id`` is the organizer's schema.org ``@id`` (falls back to
    ``url`` when ``@id`` is absent) — for Piletilevi this is the promoter's
    profile URL, the key a Publisher resolves against (see CONTEXT.md's Event
    Claiming glossary; resolution itself is a later ticket — this function
    only extracts the raw field, #411).
    """
    for item in items:
        organizer = item.get("organizer")
        if not isinstance(organizer, dict):
            continue
        name_raw = organizer.get("name")
        name = name_raw.strip() or None if isinstance(name_raw, str) else None
        url_raw = organizer.get("url")
        url = str(url_raw) if url_raw else None
        id_raw = organizer.get("@id") or url_raw
        external_id = str(id_raw) if id_raw else None
        if name is None and external_id is None:
            continue
        return {"external_id": external_id, "name": name, "url": url}
    return None


def extract_jsonld_event_organizer(soup: BeautifulSoup) -> dict[str, Any] | None:
    """Return the first schema.org ``Event``'s ``organizer`` field.

    Convenience wrapper over ``parse_jsonld_event_items`` +
    ``organizer_from_jsonld_items`` — see ``parse_jsonld_event_items``
    docstring for callers needing more than one field from the same page.
    """
    return organizer_from_jsonld_items(parse_jsonld_event_items(soup))
