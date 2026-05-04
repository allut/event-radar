import logging
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx

from app.config import settings
from app.ingestion.base import NormalizedEvent, SourceAdapter
TALLINN_TZ = ZoneInfo("Europe/Tallinn")
log = logging.getLogger(__name__)


def _first_not_none(*vals: Any) -> Any:
    return next((v for v in vals if v is not None), None)


class FientaAdapter(SourceAdapter):
    """Fetches events from Fienta public API for all organizer IDs in source.config.

    source.config must contain:
      organizer_ids: list[int]   — Fienta numeric organizer IDs

    TODO: add pagination support once Fienta API pagination fields are confirmed.
    """

    async def fetch_raw(self) -> list[dict[str, Any]]:
        organizer_ids: list[int] = self.source.config.get("organizer_ids", [])
        all_events: list[dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            for org_id in organizer_ids:
                try:
                    response = await client.get(
                        self.source.config.get("base_url", settings.FIENTA_BASE_URL),
                        params={"organizer": org_id},
                    )
                    response.raise_for_status()
                    data = response.json()
                    events = data if isinstance(data, list) else data.get("data", data.get("events", []))
                    all_events.extend(events)
                except httpx.HTTPStatusError as exc:
                    log.warning("fienta organizer=%s failed: %s", org_id, exc.response.status_code)
                except httpx.RequestError as exc:
                    log.warning("fienta organizer=%s network error: %s", org_id, exc)

        return all_events

    def normalize(self, raw: dict[str, Any]) -> Optional[NormalizedEvent]:
        title = raw.get("name") or raw.get("title") or ""
        if not title:
            return None

        external_id = str(raw.get("id", ""))
        if not external_id:
            return None

        raw_start = raw.get("starts_at") or raw.get("start_date") or raw.get("start_time")
        if not raw_start:
            return None
        starts_at = _parse_dt(str(raw_start))
        if starts_at is None:
            return None

        raw_end = raw.get("ends_at") or raw.get("end_date") or raw.get("end_time")
        ends_at = _parse_dt(str(raw_end)) if raw_end else None

        venue_raw = raw.get("venue") or {}
        if isinstance(venue_raw, dict):
            venue_name = venue_raw.get("name")
            venue_address = venue_raw.get("address")
        else:
            venue_name = str(venue_raw) or None
            venue_address = None

        price_raw = raw.get("price") or {}
        if isinstance(price_raw, dict):
            price_min = _first_not_none(price_raw.get("min"), raw.get("min_price"))
            price_max = _first_not_none(price_raw.get("max"), raw.get("max_price"))
            currency_raw = _first_not_none(price_raw.get("currency"), raw.get("currency"))
        else:
            price_min = _first_not_none(raw.get("min_price"), raw.get("price_min"))
            price_max = _first_not_none(raw.get("max_price"), raw.get("price_max"))
            currency_raw = raw.get("currency")

        has_price = price_min is not None or price_max is not None
        currency = str(currency_raw) if currency_raw else ("EUR" if has_price else None)

        return NormalizedEvent(
            external_id=external_id,
            title=str(title),
            description=raw.get("description") or raw.get("body"),
            starts_at=starts_at,
            ends_at=ends_at,
            venue_name=venue_name or None,
            venue_address=venue_address or None,
            url=raw.get("url") or raw.get("link"),
            image_url=raw.get("image_url") or raw.get("image") or raw.get("cover_image"),
            price_min=float(price_min) if price_min is not None else None,
            price_max=float(price_max) if price_max is not None else None,
            currency=currency,
        )


def _parse_dt(value: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TALLINN_TZ)
        return dt
    except (ValueError, TypeError):
        return None
