import hashlib
import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    DEFAULT_CURRENCY,
    ESTONIA_BBOX,
    EVENT_STATUS_DRAFT,
    EXPLICIT_KEYWORDS,
    FIENTA_CITY_FILTER,
    HTTP_RETRYABLE_STATUS_CODES,
    HTTP_RETRY_MAX_ATTEMPTS,
    HTTP_RETRY_WAIT_MAX,
    HTTP_RETRY_WAIT_MIN,
    HTTP_RETRY_WAIT_MULTIPLIER,
    INGESTION_ERROR_MAX_LEN,
    PRICE_FROM_STRING_RE,
    SAFE_URL_SCHEMES,
    SLUG_HASH_HEX_LEN,
    SLUG_TITLE_MAX_LEN,
    SOURCE_STATUS_ERROR,
    SOURCE_STATUS_OK,
    TALLINN_TZ,
)
from app.models.models import Event, EventSource, IngestionRun, RawEvent, Source

log = logging.getLogger(__name__)


def _is_retryable(exc: BaseException) -> bool:
    """Return True for transient HTTP failures worth retrying."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in HTTP_RETRYABLE_STATUS_CODES
    return isinstance(exc, httpx.RequestError)


_http_retry = retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_exponential(
        multiplier=HTTP_RETRY_WAIT_MULTIPLIER,
        min=HTTP_RETRY_WAIT_MIN,
        max=HTTP_RETRY_WAIT_MAX,
    ),
    stop=stop_after_attempt(HTTP_RETRY_MAX_ATTEMPTS),
    reraise=True,
)


@_http_retry
async def http_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
) -> httpx.Response:
    """Shared HTTP GET with exponential-backoff retry for transient failures."""
    r = await client.get(url, params=params, headers=headers)
    r.raise_for_status()
    return r


@_http_retry
async def http_post(
    client: httpx.AsyncClient,
    url: str,
    *,
    data: dict | None = None,
    headers: dict | None = None,
) -> httpx.Response:
    """Shared HTTP POST with exponential-backoff retry for transient failures."""
    r = await client.post(url, data=data, headers=headers)
    r.raise_for_status()
    return r


def safe_external_url(url: str | None) -> str | None:
    """Drop URLs whose scheme isn't http(s) — guards against stored XSS via
    javascript:/data: URLs from untrusted sources rendered into <a href>/<img src>."""
    if not url:
        return None
    if urlsplit(url).scheme.lower() not in SAFE_URL_SCHEMES:
        return None
    return url


_EXPLICIT_KEYWORD_PATTERNS = [
    re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
    for kw in EXPLICIT_KEYWORDS
]


def is_explicit_text(*parts: str | None) -> bool:
    """Word-boundary match of EXPLICIT_KEYWORDS against the joined text parts.

    Used at ingest time to flag sexually-explicit listings (Event.is_explicit)
    before they ever reach the LLM."""
    text = " ".join(p for p in parts if p)
    return any(pattern.search(text) for pattern in _EXPLICIT_KEYWORD_PATTERNS)


def normalize_currency(raw: Any, has_price: bool) -> str | None:
    """Coerce a raw currency value; fall back to DEFAULT_CURRENCY only when a price exists."""
    if raw:
        return str(raw)
    return DEFAULT_CURRENCY if has_price else None


# Regex to extract the city token from Fienta-style addresses:
# "<street>, <postal code> <City>, <county>" — city sits after a postal code.
# Estonian codes are 5 digits; foreign codes (LV: 4, LT: 5) also covered by 3-6.
# \w with UNICODE matches any Unicode letter (covers Estonian, Latvian, Lithuanian diacritics).
_CITY_FROM_ADDRESS_RE = re.compile(r"\b\d{3,6}\s+(\w[\w\-]+)", re.UNICODE)


def address_city(address: str) -> str | None:
    """Extract city token from a Fienta-style address string, or None if not parseable."""
    m = _CITY_FROM_ADDRESS_RE.search(address)
    return m.group(1) if m else None


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


def parse_dt(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TALLINN_TZ)
        return dt
    except (ValueError, TypeError):
        return None


@dataclass
class NormalizedEvent:
    external_id: str
    title: str
    starts_at: datetime  # must be timezone-aware
    description: str | None = None
    ends_at: datetime | None = None
    venue_name: str | None = None
    venue_address: str | None = None
    lat: float | None = None
    lng: float | None = None
    url: str | None = None
    image_url: str | None = None
    price_min: float | None = None
    price_max: float | None = None
    currency: str | None = None
    price_hint: str | None = None


def _make_slug(title: str, starts_at: datetime, external_id: str) -> str:
    safe = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    date_part = starts_at.strftime("%Y%m%d")
    # short hex keeps collision probability <0.1% up to ~10k events/run
    h = hashlib.md5(external_id.encode(), usedforsecurity=False).hexdigest()[
        :SLUG_HASH_HEX_LEN
    ]
    return f"{safe[:SLUG_TITLE_MAX_LEN]}-{date_part}-{h}"


async def existing_external_ids(db: AsyncSession, source_id: int) -> set[str]:
    """Return external_ids already stored in event_sources for this source.

    Lets adapters skip detail fetches for already-ingested events (forward-only
    + self-healing: new events get fetched every run until stored).
    """
    rows = await db.scalars(
        select(EventSource.external_id).where(EventSource.source_id == source_id)
    )
    return {r for r in rows.all() if r is not None}


_PRICE_FROM_STRING_RE = re.compile(PRICE_FROM_STRING_RE, re.IGNORECASE)


def parse_price_from_string(
    value: str | None,
) -> tuple[float | None, float | None, str | None]:
    """Parse a Fienta listing price_from_string into (price_min, price_max, currency).

    Grammar (verified across all 803 live rows): optional "From ", a number, a 3-letter
    currency; optional ", free" suffix; or the literal "Free"; or None/empty.
      - "10 EUR"           -> (10, 10, "EUR")    exact price, min == max
      - "From 28 EUR"      -> (28, None, "EUR")  open-ended, no listing ceiling
      - "From 6 EUR, free" -> (0, None, "EUR")   free tier present, paid from 6
      - "40 EUR, free"     -> (0, 40, "EUR")     free tier present, ceiling 40
      - "Free"             -> (0, 0, None)
      - None / unparseable -> (None, None, None)
    """
    if not value:
        return (None, None, None)
    text = value.strip()
    has_free = text.lower() == "free" or text.lower().endswith(", free")
    m = _PRICE_FROM_STRING_RE.search(text)
    if not m:
        return (0.0, 0.0, None) if has_free else (None, None, None)
    amount = float(m.group(1).replace(",", "."))
    currency = m.group(2).upper()
    # The optional "From " prefix is captured inside the match, so test the raw
    # string's start rather than text[:m.start()] (which would be empty here).
    is_from = text.lower().startswith("from")
    ceiling = None if is_from else amount
    price_min = 0.0 if has_free else amount
    return (price_min, ceiling, currency)


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
) -> tuple[float | None, float | None, str | None]:
    """Return ``(min_price, max_price, currency)`` from schema.org ``Event`` ``offers[]``.

    Reads all ``Offer`` entries from the first JSON-LD ``Event`` block, returns
    ``(None, None, None)`` when no offers or no parseable prices are found.
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
            prices: list[float] = []
            currency: str | None = None
            for offer in offers_raw:
                if not isinstance(offer, dict):
                    continue
                price = _coerce_float(offer.get("price"))
                if price is not None:
                    prices.append(price)
                if currency is None:
                    cur_raw = offer.get("priceCurrency")
                    if cur_raw:
                        currency = str(cur_raw).upper()
            if not prices:
                continue  # no parseable prices in this block — try next Event item
            return (min(prices), max(prices), currency)
    return (None, None, None)


def coords_in_estonia(lat: float, lng: float) -> bool:
    """Return True when (lat, lng) falls within Estonia's bounding box."""
    lat_min, lat_max, lng_min, lng_max = ESTONIA_BBOX
    return lat_min <= lat <= lat_max and lng_min <= lng <= lng_max


class SourceAdapter(ABC):
    def __init__(self, source: Source) -> None:
        self.source = source

    @abstractmethod
    async def fetch_raw(self, db: AsyncSession) -> list[dict[str, Any]]: ...

    @abstractmethod
    def normalize(self, raw: dict[str, Any]) -> NormalizedEvent | None: ...

    def get_raw_external_id(self, raw: dict[str, Any]) -> str | None:
        """Extract the external ID to store on RawEvent. Override for non-'id' key sources."""
        v = raw.get("id", "")
        return str(v) if v else None

    async def run(self, db: AsyncSession) -> IngestionRun:
        """Execute full pipeline: fetch → raw_events → normalize → events(draft).

        NOTE: the caller is responsible for committing or rolling back the session.
        On error, run.error is populated but the caller must still commit to persist
        the failure record (instead of rolling back the entire transaction).
        """
        run = IngestionRun(source_id=self.source.id)
        db.add(run)
        await db.flush()

        try:
            raw_items = await self.fetch_raw(db)
            run.raw_count = len(raw_items)
            new_count = 0
            seen_external_ids: set[str] = set()

            for raw in raw_items:
                raw_event = RawEvent(
                    source_id=self.source.id,
                    external_id=self.get_raw_external_id(raw),
                    payload=raw,
                )
                db.add(raw_event)
                await db.flush()

                normalized = self.normalize(raw)
                if normalized is None or not normalized.external_id:
                    continue

                if normalized.external_id in seen_external_ids:
                    raw_event.processed_at = datetime.now(tz=TALLINN_TZ)
                    continue

                existing = await db.scalar(
                    select(EventSource).where(
                        EventSource.source_id == self.source.id,
                        EventSource.external_id == normalized.external_id,
                    )
                )
                if existing:
                    raw_event.processed_at = datetime.now(tz=TALLINN_TZ)
                    continue

                slug = _make_slug(
                    normalized.title, normalized.starts_at, normalized.external_id
                )
                try:
                    async with db.begin_nested():
                        event = Event(
                            slug=slug,
                            title_orig=normalized.title,
                            description_orig=normalized.description,
                            starts_at=normalized.starts_at,
                            ends_at=normalized.ends_at,
                            venue_name=normalized.venue_name,
                            venue_address=normalized.venue_address,
                            lat=normalized.lat,
                            lng=normalized.lng,
                            url=safe_external_url(normalized.url),
                            image_url=safe_external_url(normalized.image_url),
                            price_min=normalized.price_min,
                            price_max=normalized.price_max,
                            currency=normalized.currency,
                            price_hint=normalized.price_hint,
                            status=EVENT_STATUS_DRAFT,
                            is_explicit=is_explicit_text(
                                normalized.title,
                                normalized.description,
                                normalized.venue_name,
                            ),
                        )
                        db.add(event)
                        await db.flush()
                        db.add(
                            EventSource(
                                event_id=event.id,
                                source_id=self.source.id,
                                external_id=normalized.external_id,
                            )
                        )
                except IntegrityError:
                    log.warning(
                        "slug collision source=%s external_id=%s slug=%s — skipped",
                        self.source.slug,
                        normalized.external_id,
                        slug,
                    )
                    continue

                raw_event.processed_at = datetime.now(tz=TALLINN_TZ)
                seen_external_ids.add(normalized.external_id)
                new_count += 1

            finished_at = datetime.now(tz=TALLINN_TZ)
            run.new_count = new_count
            run.finished_at = finished_at
            self.source.last_run_at = finished_at
            self.source.last_status = SOURCE_STATUS_OK

        except Exception as exc:
            run.error = str(exc)[:INGESTION_ERROR_MAX_LEN]
            self.source.last_status = SOURCE_STATUS_ERROR
            raise

        return run
