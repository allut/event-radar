import logging
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.constants import FIENTA_MAX_PAGES, HTTP_TIMEOUT_SECONDS
from app.ingestion.base import (
    NormalizedEvent,
    SourceAdapter,
    _http_get,
    _parse_dt,
    normalize_currency,
)

log = logging.getLogger(__name__)


def _first_not_none(*vals: Any) -> Any:
    return next((v for v in vals if v is not None), None)


class FientaAdapter(SourceAdapter):
    """Fetches events from Fienta public API for all organizer IDs in source.config.

    source.config must contain:
      organizer_ids: list[int] — Fienta numeric organizer IDs

    Pagination: handles both link-based (`links.next`) and meta-based
    (`meta.current_page` / `meta.last_page`) pagination automatically.
    Plain list responses (no pagination envelope) are also supported.
    """

    async def fetch_raw(self) -> list[dict[str, Any]]:
        organizer_ids: list[int] = self.source.config.get("organizer_ids", [])
        base_url: str = self.source.config.get("base_url", settings.FIENTA_BASE_URL)
        all_events: list[dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
            for org_id in organizer_ids:
                try:
                    all_events.extend(
                        await self._fetch_organizer(client, base_url, org_id)
                    )
                except httpx.HTTPStatusError as exc:
                    log.warning(
                        "fienta organizer=%s failed: %s",
                        org_id,
                        exc.response.status_code,
                    )
                except httpx.RequestError as exc:
                    log.warning("fienta organizer=%s network error: %s", org_id, exc)

        return all_events

    async def _fetch_organizer(
        self, client: httpx.AsyncClient, base_url: str, org_id: int
    ) -> list[dict[str, Any]]:
        """Fetch all pages for a single organizer against a shared FIENTA_MAX_PAGES budget."""
        collected: list[dict[str, Any]] = []
        base_host = urlparse(base_url).hostname  # hostname only, excludes port
        budget = FIENTA_MAX_PAGES  # total requests allowed across all pagination styles

        url: str = base_url
        params: dict[str, Any] | None = {"organizer": org_id}
        page = 1  # used only for meta-based pagination

        while url and budget > 0:
            # params=None preserves the URL's existing query string (e.g. links.next
            # already encodes all params); params=dict merges/replaces the query string.
            response = await _http_get(client, url, params=params)
            budget -= 1
            data = response.json()

            if isinstance(data, list):
                collected.extend(data)
                break  # plain list — no pagination

            events = data.get("data", data.get("events", []))
            collected.extend(events)

            # link-based pagination: follow links.next (validated against base host)
            next_url = (data.get("links") or {}).get("next") or ""
            if next_url:
                if urlparse(next_url).hostname != base_host:
                    log.error(
                        "fienta: links.next host mismatch (SSRF guard), stopping pagination"
                    )
                    break
                url = next_url
                params = None  # next URL already encodes all params
                continue

            # meta-based pagination: advance page counter.
            # Assumes APIs that mix link+meta styles always include current_page in meta.
            meta = data.get("meta") or {}
            current = meta.get("current_page", page)
            last = meta.get("last_page")
            if last is None or current >= last:
                break
            page = current + 1
            params = {"organizer": org_id, "page": page}

        return collected

    def normalize(self, raw: dict[str, Any]) -> Optional[NormalizedEvent]:
        title = raw.get("name") or raw.get("title") or ""
        if not title:
            return None

        external_id = str(raw.get("id", ""))
        if not external_id:
            return None

        raw_start = (
            raw.get("starts_at") or raw.get("start_date") or raw.get("start_time")
        )
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

        price_raw = raw.get("price")
        if isinstance(price_raw, dict):
            price_min = _first_not_none(price_raw.get("min"), raw.get("min_price"))
            price_max = _first_not_none(price_raw.get("max"), raw.get("max_price"))
            currency_raw = _first_not_none(
                price_raw.get("currency"), raw.get("currency")
            )
        else:
            # price_raw is None, int, or unexpected type — fall back to top-level fields
            price_min = _first_not_none(raw.get("min_price"), raw.get("price_min"))
            price_max = _first_not_none(raw.get("max_price"), raw.get("price_max"))
            currency_raw = raw.get("currency")

        currency = normalize_currency(
            currency_raw, price_min is not None or price_max is not None
        )

        return NormalizedEvent(
            external_id=external_id,
            title=str(title),
            description=raw.get("description") or raw.get("body"),
            starts_at=starts_at,
            ends_at=ends_at,
            venue_name=venue_name or None,
            venue_address=venue_address or None,
            url=raw.get("url") or raw.get("link"),
            image_url=raw.get("image_url")
            or raw.get("image")
            or raw.get("cover_image"),
            price_min=float(price_min) if price_min is not None else None,
            price_max=float(price_max) if price_max is not None else None,
            currency=currency,
        )
