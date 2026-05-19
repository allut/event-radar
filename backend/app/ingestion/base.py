import hashlib
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import httpx
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


@retry(
    retry=retry_if_exception(_is_retryable),
    wait=wait_exponential(
        multiplier=HTTP_RETRY_WAIT_MULTIPLIER,
        min=HTTP_RETRY_WAIT_MIN,
        max=HTTP_RETRY_WAIT_MAX,
    ),
    stop=stop_after_attempt(HTTP_RETRY_MAX_ATTEMPTS),
    reraise=True,
)
async def _http_get(
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


def normalize_currency(raw: Any, has_price: bool) -> Optional[str]:
    """Coerce a raw currency value; fall back to DEFAULT_CURRENCY only when a price exists."""
    if raw:
        return str(raw)
    return DEFAULT_CURRENCY if has_price else None


def _parse_dt(value: str) -> Optional[datetime]:
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
    description: Optional[str] = None
    ends_at: Optional[datetime] = None
    venue_name: Optional[str] = None
    venue_address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    url: Optional[str] = None
    image_url: Optional[str] = None
    price_min: Optional[float] = None
    price_max: Optional[float] = None
    currency: Optional[str] = None


def _make_slug(title: str, starts_at: datetime, external_id: str) -> str:
    safe = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    date_part = starts_at.strftime("%Y%m%d")
    # short hex keeps collision probability <0.1% up to ~10k events/run
    h = hashlib.md5(external_id.encode(), usedforsecurity=False).hexdigest()[:SLUG_HASH_HEX_LEN]
    return f"{safe[:SLUG_TITLE_MAX_LEN]}-{date_part}-{h}"


class SourceAdapter(ABC):
    def __init__(self, source: Source) -> None:
        self.source = source

    @abstractmethod
    async def fetch_raw(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def normalize(self, raw: dict[str, Any]) -> Optional[NormalizedEvent]: ...

    def get_raw_external_id(self, raw: dict[str, Any]) -> Optional[str]:
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
            raw_items = await self.fetch_raw()
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

                slug = _make_slug(normalized.title, normalized.starts_at, normalized.external_id)
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
                            url=normalized.url,
                            image_url=normalized.image_url,
                            price_min=normalized.price_min,
                            price_max=normalized.price_max,
                            currency=normalized.currency,
                            status=EVENT_STATUS_DRAFT,
                        )
                        db.add(event)
                        await db.flush()
                        db.add(EventSource(
                            event_id=event.id,
                            source_id=self.source.id,
                            external_id=normalized.external_id,
                        ))
                except IntegrityError:
                    log.warning(
                        "slug collision source=%s external_id=%s slug=%s — skipped",
                        self.source.slug, normalized.external_id, slug,
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
