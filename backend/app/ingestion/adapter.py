"""SourceAdapter — the ingestion write path.

NormalizedEvent, slug generation, ingest skip-id loading, geo bbox gates, and
SourceAdapter.run(): fetch -> raw_events -> normalize -> events(draft).
"""

import hashlib
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    ESTONIA_BBOX,
    EVENT_STATUS_DRAFT,
    INGEST_REJECT_RECHECK_DAYS,
    INGEST_SKIP_ID_LOOKBACK_DAYS,
    INGESTION_ERROR_MAX_LEN,
    SLUG_HASH_HEX_LEN,
    SLUG_SANITIZE_RE,
    SLUG_TITLE_MAX_LEN,
    SOURCE_KIND_USER_SUBMISSION,
    SOURCE_STATUS_ERROR,
    SOURCE_STATUS_OK,
    TALLINN_REGION_BBOX,
    TALLINN_TZ,
)
from app.ingestion.content_filters import is_explicit_text, is_non_event_text
from app.ingestion.http_client import safe_external_url, safe_fetchable_url
from app.models.models import Event, EventSource, IngestionRun, RawEvent, Source

log = logging.getLogger(__name__)


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
    important_info: str | None = None
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
    has_free_tier: bool = False
    title_localized: dict[str, str] | None = None
    description_localized: dict[str, str] | None = None
    important_info_localized: dict[str, str] | None = None

    def __post_init__(self) -> None:
        # Coords without an address are orphan data here — the geocode/sibling-copy
        # chain keys off venue_address — so drop them rather than persist a pin we
        # can never re-derive or match.
        if self.venue_address is None:
            self.lat = None
            self.lng = None


def _make_slug(title: str, starts_at: datetime, external_id: str) -> str:
    safe = re.sub(SLUG_SANITIZE_RE, "-", title.lower()).strip("-")
    date_part = starts_at.strftime("%Y%m%d")
    # short hex keeps collision probability <0.1% up to ~10k events/run
    h = hashlib.md5(external_id.encode(), usedforsecurity=False).hexdigest()[
        :SLUG_HASH_HEX_LEN
    ]
    return f"{safe[:SLUG_TITLE_MAX_LEN]}-{date_part}-{h}"


async def existing_external_ids(db: AsyncSession, source_id: int) -> set[str]:
    """Return external_ids already stored in event_sources for this source,
    for events that started within INGEST_SKIP_ID_LOOKBACK_DAYS (or later).

    Lets adapters skip detail fetches for already-ingested events (forward-only
    + self-healing: new events get fetched every run until stored). Bounded by
    join to Event.starts_at — a source's live listing never re-surfaces an
    external_id belonging to an event that started long ago, and events rows
    are never deleted, so an unbounded query here grows forever (see
    INGEST_SKIP_ID_LOOKBACK_DAYS). Correctness is unaffected if a stale
    external_id drops out of this set: the event_sources unique index plus the
    IntegrityError handler in insert_normalized_event still catch a re-insert.
    """
    cutoff = datetime.now(tz=TALLINN_TZ) - timedelta(days=INGEST_SKIP_ID_LOOKBACK_DAYS)
    rows = await db.scalars(
        select(EventSource.external_id)
        .join(Event, Event.id == EventSource.event_id)
        .where(EventSource.source_id == source_id, Event.starts_at >= cutoff)
    )
    return {r for r in rows.all() if r is not None}


async def ingest_skip_ids(db: AsyncSession, source_id: int) -> set[str]:
    """external_ids to skip this run: already-stored events (forward-only) plus
    events fetched-but-rejected within INGEST_REJECT_RECHECK_DAYS, so a
    permanently-rejected event isn't re-fetched/re-saved every run."""
    stored = await existing_external_ids(db, source_id)
    cutoff = datetime.now(tz=TALLINN_TZ) - timedelta(days=INGEST_REJECT_RECHECK_DAYS)
    rows = await db.scalars(
        select(RawEvent.external_id).where(
            RawEvent.source_id == source_id,
            RawEvent.fetched_at >= cutoff,
        )
    )
    recent = {r for r in rows.all() if r is not None}
    return stored | recent


def coords_in_estonia(lat: float, lng: float) -> bool:
    """Return True when (lat, lng) falls within Estonia's bounding box."""
    lat_min, lat_max, lng_min, lng_max = ESTONIA_BBOX
    return lat_min <= lat <= lat_max and lng_min <= lng <= lng_max


def coords_in_tallinn(lat: float, lng: float) -> bool:
    """Return True when (lat, lng) falls within the greater-Tallinn bounding box."""
    lat_min, lat_max, lng_min, lng_max = TALLINN_REGION_BBOX
    return lat_min <= lat <= lat_max and lng_min <= lng <= lng_max


async def insert_normalized_event(
    db: AsyncSession, source: Source, normalized: NormalizedEvent
) -> Event | None:
    """Insert the Event + EventSource rows inside a savepoint.

    Shared by every ingestion write path: scraper adapters (via
    SourceAdapter._insert_event below) and the organizer direct-submission
    router (routers/organizer_events.py), which has no adapter/normalize()
    step of its own but still needs the same slug/SSRF-guard/content-flag/
    collision-handling behavior.

    Returns None on a slug collision (IntegrityError) — the savepoint rolls
    back just this event, not the whole batch. Callers that need description/
    important_info sanitized must call sanitize_html() before building
    ``normalized`` — this function does not sanitize (that lives in each
    adapter's normalize(), see the module docstring above).
    """
    slug = _make_slug(normalized.title, normalized.starts_at, normalized.external_id)
    # event.url is host-pinned only when something fetches it server-side.
    # Adapter sources are refetched daily (refetch.py), so they keep the SSRF
    # guard; user submissions are excluded from refetch (see
    # refetch.py::_select_candidates), so their url is render-only and gets
    # the same scheme-only check as image_url.
    if source.kind == SOURCE_KIND_USER_SUBMISSION:
        safe_url = safe_external_url(normalized.url, source.slug)
    else:
        safe_url = await safe_fetchable_url(normalized.url, source.slug)
    try:
        async with db.begin_nested():
            event = Event(
                slug=slug,
                title_orig=normalized.title,
                description_orig=normalized.description,
                important_info=normalized.important_info,
                starts_at=normalized.starts_at,
                ends_at=normalized.ends_at,
                venue_name=normalized.venue_name,
                venue_address=normalized.venue_address,
                lat=normalized.lat,
                lng=normalized.lng,
                url=safe_url,
                image_url=safe_external_url(normalized.image_url, source.slug),
                price_min=normalized.price_min,
                price_max=normalized.price_max,
                currency=normalized.currency,
                price_hint=normalized.price_hint,
                has_free_tier=normalized.has_free_tier,
                title_localized=normalized.title_localized,
                description_localized=normalized.description_localized,
                important_info_localized=normalized.important_info_localized,
                status=EVENT_STATUS_DRAFT,
                is_explicit=is_explicit_text(
                    normalized.title,
                    normalized.description,
                    normalized.venue_name,
                    normalized.important_info,
                ),
                is_non_event=is_non_event_text(
                    normalized.title,
                    normalized.venue_name,
                ),
            )
            db.add(event)
            await db.flush()
            db.add(
                EventSource(
                    event_id=event.id,
                    source_id=source.id,
                    external_id=normalized.external_id,
                )
            )
    except IntegrityError:
        log.warning(
            "slug collision source=%s external_id=%s slug=%s — skipped",
            source.slug,
            normalized.external_id,
            slug,
        )
        return None
    return event


class SourceAdapter(ABC):
    def __init__(self, source: Source) -> None:
        self.source = source

    @abstractmethod
    async def fetch_raw(self, known_ids: set[str]) -> list[dict[str, Any]]: ...

    @abstractmethod
    def normalize(self, raw: dict[str, Any]) -> NormalizedEvent | None: ...

    def get_raw_external_id(self, raw: dict[str, Any]) -> str | None:
        """Extract the external ID to store on RawEvent. Override for non-'id' key sources."""
        v = raw.get("id", "")
        return str(v) if v else None

    async def _insert_event(
        self, db: AsyncSession, normalized: NormalizedEvent
    ) -> Event | None:
        """Insert via the shared insert_normalized_event() helper, bound to
        this adapter's source. Returns None on a slug collision."""
        return await insert_normalized_event(db, self.source, normalized)

    async def _process_raw_item(
        self,
        db: AsyncSession,
        raw: dict[str, Any],
        known_ids: set[str],
        seen: set[str],
    ) -> bool:
        """Persist one raw item and, when new, its normalized Event.

        Returns True when a new Event row was inserted.
        """
        raw_event = RawEvent(
            source_id=self.source.id,
            external_id=self.get_raw_external_id(raw),
            payload=raw,
        )
        db.add(raw_event)
        await db.flush()

        normalized = self.normalize(raw)
        if normalized is None or not normalized.external_id:
            return False
        # known_ids (loaded once via ingest_skip_ids) holds every stored
        # external_id for this source — an in-memory check instead of a
        # per-item SELECT (no N+1 on a large crawl). Race safety against a
        # concurrent insert stays covered by the event_sources unique index +
        # the IntegrityError handler in _insert_event.
        if normalized.external_id in seen or normalized.external_id in known_ids:
            raw_event.processed_at = datetime.now(tz=TALLINN_TZ)
            return False

        if not await self._insert_event(db, normalized):
            return False

        raw_event.processed_at = datetime.now(tz=TALLINN_TZ)
        seen.add(normalized.external_id)
        return True

    async def run(self, db: AsyncSession) -> IngestionRun:
        """Execute full pipeline: fetch → raw_events → normalize → events(draft).

        NOTE: the caller is responsible for committing or rolling back the session.
        On error, run.error is populated but the caller must still commit to persist
        the failure record (instead of rolling back the entire transaction).
        """
        known_ids = await ingest_skip_ids(db, self.source.id)
        # Release the connection for the crawl below — fetch_raw is network I/O only
        # (no db access), often taking minutes, which would otherwise hold a checked-out
        # connection idle past Neon's auto-suspend window. Nothing has been written yet,
        # so this is a no-op beyond ending the transaction and returning the connection
        # to the pool. Must be commit(), not rollback(): Session.rollback() unconditionally
        # expires every ORM object in the identity map regardless of expire_on_commit,
        # which would make every later `self.source.*` read below (and in fetch_raw()
        # overrides) trigger an implicit lazy-load — disallowed under AsyncSession outside
        # the greenlet-spawn context (raises MissingGreenlet). commit() respects
        # expire_on_commit=False (app/db.py), so self.source stays usable.
        await db.commit()

        # Captured before the crawl: the IngestionRun row is now inserted after
        # fetch_raw() completes, so started_at's server_default=func.now() would
        # otherwise record crawl-end instead of crawl-start, silently losing the
        # one timestamp this audit column exists to track.
        started_at = datetime.now(tz=TALLINN_TZ)
        run = IngestionRun(source_id=self.source.id, started_at=started_at)

        try:
            raw_items = await self.fetch_raw(known_ids)
            db.add(run)
            await db.flush()
            run.raw_count = len(raw_items)
            new_count = 0
            seen_external_ids: set[str] = set()

            for raw in raw_items:
                if await self._process_raw_item(db, raw, known_ids, seen_external_ids):
                    new_count += 1

            finished_at = datetime.now(tz=TALLINN_TZ)
            run.new_count = new_count
            run.finished_at = finished_at
            self.source.last_run_at = finished_at
            self.source.last_status = SOURCE_STATUS_OK

        except Exception as exc:
            run.error = str(exc)[:INGESTION_ERROR_MAX_LEN]
            self.source.last_status = SOURCE_STATUS_ERROR
            if run.id is None:
                # fetch_raw failed before the persist phase flushed run — it
                # was never added to the session, so add it now to record the
                # error (the caller still expects an IngestionRun row).
                db.add(run)
                await db.flush()
            raise

        return run
