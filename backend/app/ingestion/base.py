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
    EVENT_STATUS_DRAFT,
    HTTP_RETRYABLE_STATUS_CODES,
    HTTP_RETRY_MAX_ATTEMPTS,
    HTTP_RETRY_WAIT_MAX,
    HTTP_RETRY_WAIT_MIN,
    HTTP_RETRY_WAIT_MULTIPLIER,
    INGESTION_ERROR_MAX_LEN,
    PRICE_HINT_MAX_CHARS,
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


def normalize_currency(raw: Any, has_price: bool) -> str | None:
    """Coerce a raw currency value; fall back to DEFAULT_CURRENCY only when a price exists."""
    if raw:
        return str(raw)
    return DEFAULT_CURRENCY if has_price else None


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


def _offer_entry_text(offer: dict[str, Any]) -> str | None:
    price = offer.get("price")
    if price is None:
        return None
    currency = offer.get("priceCurrency") or ""
    name = offer.get("name")
    price_part = f"{price} {currency}".strip()
    return f"{name} {price_part}" if name else price_part


def _offers_text(offers: Any) -> str | None:
    if isinstance(offers, dict):
        low = offers.get("lowPrice")
        high = offers.get("highPrice")
        if low is not None or high is not None:
            currency = offers.get("priceCurrency") or ""
            if low is not None and high is not None and low != high:
                return f"{low} - {high} {currency}".strip()
            return f"{low if low is not None else high} {currency}".strip()
        return _offer_entry_text(offers)
    if isinstance(offers, list):
        parts = [t for o in offers if isinstance(o, dict) and (t := _offer_entry_text(o))]
        return "; ".join(parts) or None
    return None


def extract_jsonld_offers_text(soup: BeautifulSoup) -> str | None:
    """Find <script type="application/ld+json"> offers and return a compact price string.

    Handles ``Offer``/``Offer[]`` (``name``/``price``/``priceCurrency``) and
    ``AggregateOffer`` (``lowPrice``/``highPrice``/``priceCurrency``). This only
    locates/serializes price text — the numeric min/max decision is left to the LLM.
    """
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (TypeError, ValueError):
            continue
        for item in data if isinstance(data, list) else [data]:
            if not isinstance(item, dict):
                continue
            text = _offers_text(item.get("offers"))
            if text:
                return text[:PRICE_HINT_MAX_CHARS]
    return None


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
