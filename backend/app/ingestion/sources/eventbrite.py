import logging
from typing import Any, Optional

import httpx

from app.config import settings
from app.constants import (
    EVENTBRITE_BASE_URL,
    EVENTBRITE_LOCATION_ADDRESS,
    EVENTBRITE_LOCATION_RADIUS,
    EVENTBRITE_MAX_PAGES,
    EVENTBRITE_PAGE_SIZE,
    HTTP_TIMEOUT_SECONDS,
    HTTP_USER_AGENT,
)
from app.ingestion.base import NormalizedEvent, SourceAdapter, _http_get, _parse_dt

log = logging.getLogger(__name__)


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_eb_price(raw: dict) -> tuple[Optional[float], Optional[float], Optional[str]]:
    if raw.get("is_free"):
        return 0.0, 0.0, "EUR"
    classes = raw.get("ticket_classes") or []
    mn: Optional[float] = None
    mx: Optional[float] = None
    cur: Optional[str] = None
    for tc in classes:
        cost = tc.get("cost") or {}
        val = cost.get("value")  # minor units (cents)
        if val is not None:
            v = float(val) / 100
            mn = v if mn is None else min(mn, v)
            mx = v if mx is None else max(mx, v)
            cur = cur or cost.get("currency")
    return mn, mx, cur or "EUR"


class EventbriteAdapter(SourceAdapter):
    """Eventbrite API v3 — events in Tallinn, EE.

    Requires EVENTBRITE_API_KEY (private OAuth token). If unset, fetch_raw returns [].
    source.config: {"api_key": "..."} — falls back to settings.EVENTBRITE_API_KEY.
    """

    def get_raw_external_id(self, raw: dict[str, Any]) -> Optional[str]:
        return raw.get("id")

    async def fetch_raw(self) -> list[dict]:
        api_key = self.source.config.get("api_key") or settings.EVENTBRITE_API_KEY
        if not api_key:
            log.warning("eventbrite: EVENTBRITE_API_KEY not set, skipping")
            return []
        all_events: list[dict] = []
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS, follow_redirects=True) as client:
            for page in range(1, EVENTBRITE_MAX_PAGES + 1):
                params = {
                    "location.address": EVENTBRITE_LOCATION_ADDRESS,
                    "location.within": EVENTBRITE_LOCATION_RADIUS,
                    "expand": "venue,ticket_classes",
                    "page_size": EVENTBRITE_PAGE_SIZE,
                    "page": page,
                    "sort_by": "date",
                }
                try:
                    response = await _http_get(
                        client,
                        EVENTBRITE_BASE_URL,
                        params=params,
                        headers={"Authorization": f"Bearer {api_key}", "User-Agent": HTTP_USER_AGENT},
                    )
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 404:
                        # Eventbrite /v3/events/search/ was deprecated for non-partner accounts.
                        # Return whatever we collected rather than crashing the pipeline.
                        log.error(
                            "eventbrite: search endpoint returned 404 — API may require partner approval. "
                            "See https://www.eventbrite.com/platform/api"
                        )
                        return all_events
                    raise
                data = response.json()
                events = data.get("events") or []
                all_events.extend(events)
                pagination = data.get("pagination", {})
                log.info(
                    "eventbrite page=%d/%s fetched=%d",
                    page,
                    pagination.get("page_count", "?"),
                    len(events),
                )
                if not pagination.get("has_more_items"):
                    break
        return all_events

    def normalize(self, raw: dict) -> Optional[NormalizedEvent]:
        title = (raw.get("name") or {}).get("text") or ""
        if not title:
            return None
        external_id = raw.get("id")
        if not external_id:
            return None
        starts_at = _parse_dt((raw.get("start") or {}).get("utc") or "")
        if not starts_at:
            return None
        ends_at = _parse_dt((raw.get("end") or {}).get("utc") or "")

        venue = raw.get("venue") or {}
        addr = venue.get("address") or {}
        venue_name = venue.get("name") or None
        venue_address = addr.get("localized_address_display") or None
        lat = _to_float(venue.get("latitude"))
        lng = _to_float(venue.get("longitude"))

        price_min, price_max, currency = _parse_eb_price(raw)
        image_url = (raw.get("logo") or {}).get("url") or None
        description = (raw.get("description") or {}).get("text") or raw.get("summary") or None

        return NormalizedEvent(
            external_id=str(external_id),
            title=str(title),
            description=description,
            starts_at=starts_at,
            ends_at=ends_at or None,
            venue_name=venue_name,
            venue_address=venue_address,
            lat=lat,
            lng=lng,
            url=raw.get("url") or None,
            image_url=image_url,
            price_min=price_min,
            price_max=price_max,
            currency=currency,
        )
