"""One-off maintenance: backfill important_info_localized for existing Piletilevi events.

Fetches each locale alternate page for Piletilevi events that have a URL but
no important_info_localized yet, extracts the localized heading block, and
writes the result to events.important_info_localized.

Run from backend/ with the venv active:
    python scripts/backfill_important_info_localized.py            # dry run
    python scripts/backfill_important_info_localized.py --yes      # write to DB
    python scripts/backfill_important_info_localized.py --yes --limit 50  # cap rows
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path
from urllib.parse import urlsplit

# backend/ must be on sys.path so `from app.*` resolves regardless of CWD.
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select

from app.constants import (
    BACKFILL_DEFAULT_LIMIT,
    HTML_LISTING_LOCALE_FETCH_DELAY_SECONDS,
    HTTP_TIMEOUT_SECONDS,
    HTTP_USER_AGENT,
    LOCALIZED_TEXT_HTML_LOCALES,
    SOURCE_SLUG_PILETILEVI,
)
from app.ingestion.http_client import host_guard_hook, http_get
from app.ingestion.locale_urls import locale_from_url_path, localized_detail_urls
from app.ingestion.sources.piletilevi import _piletilevi_important_info
from app.logging_config import configure_logging
from app.models.models import Event, EventSource, Source
from app.routers.utils import mask_db_url

configure_logging()
log = logging.getLogger(__name__)


async def _fetch_localized_infos(
    client: httpx.AsyncClient,
    event_url: str,
) -> dict[str, str]:
    """Fetch all locale alternates for event_url and extract important_info per locale."""
    try:
        detail_resp = await http_get(client, event_url)
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        log.warning("detail fetch failed url=%s: %s", event_url, exc)
        return {}

    detail_soup = BeautifulSoup(detail_resp.text, "html.parser")
    detail_host = urlsplit(event_url).hostname
    url_locale = locale_from_url_path(event_url, LOCALIZED_TEXT_HTML_LOCALES)
    locale_urls = localized_detail_urls(detail_soup, event_url, LOCALIZED_TEXT_HTML_LOCALES)

    loc_infos: dict[str, str] = {}

    for locale, loc_url in locale_urls.items():
        if locale == url_locale or loc_url == event_url:
            soup = detail_soup
        else:
            try:
                await asyncio.sleep(HTML_LISTING_LOCALE_FETCH_DELAY_SECONDS)
                loc_resp = await http_get(client, loc_url)
                final = urlsplit(str(loc_resp.url))
                if final.hostname != detail_host or final.path in ("/", ""):
                    log.debug("locale redirect off-host or root locale=%s url=%s", locale, loc_url)
                    continue
                soup = BeautifulSoup(loc_resp.text, "html.parser")
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                log.debug("locale fetch failed locale=%s url=%s: %s", locale, loc_url, exc)
                continue

        info = _piletilevi_important_info(soup, locale)
        if info:
            loc_infos[locale] = info

    return loc_infos


async def main(confirm: bool, limit: int) -> None:
    from app.config import settings
    from app.db import AsyncSessionLocal

    print(f"DB: {mask_db_url(settings.DATABASE_URL)}")

    async with AsyncSessionLocal() as db:
        # Load Piletilevi source
        src_result = await db.execute(
            select(Source).where(Source.slug == SOURCE_SLUG_PILETILEVI)
        )
        source = src_result.scalar_one_or_none()
        if source is None:
            print(f"Source '{SOURCE_SLUG_PILETILEVI}' not found in DB. Nothing to do.")
            return

        # Events from Piletilevi that have a URL but no important_info_localized yet
        stmt = (
            select(Event)
            .join(EventSource, EventSource.event_id == Event.id)
            .where(EventSource.source_id == source.id)
            .where(Event.url.isnot(None))
            .where(Event.important_info_localized.is_(None))
            .order_by(Event.id)
            .limit(limit)
        )
        result = await db.execute(stmt)
        events = result.scalars().all()

    print(f"Found {len(events)} Piletilevi events without important_info_localized.")
    if not events:
        return

    if not confirm:
        print("Dry run — pass --yes to write to DB. Sample URLs:")
        for ev in events[:5]:
            print(f"  [{ev.id}] {ev.url}")
        return

    allowed_hosts = frozenset(
        h for ev in events if (h := urlsplit(ev.url or "").hostname)
    )
    updated = 0
    skipped = 0

    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT_SECONDS,
        headers={"User-Agent": HTTP_USER_AGENT},
        follow_redirects=True,
        event_hooks={"request": [host_guard_hook(allowed_hosts)]},
    ) as client:
        async with AsyncSessionLocal() as db:
            for i, ev in enumerate(events, 1):
                assert ev.url is not None
                log.info("[%d/%d] event_id=%d url=%s", i, len(events), ev.id, ev.url)
                try:
                    loc_infos = await _fetch_localized_infos(client, ev.url)

                    if not loc_infos:
                        skipped += 1
                        log.info("  → no important_info found in any locale, skipping")
                        continue

                    ev_db = await db.get(Event, ev.id)
                    if ev_db is None:
                        skipped += 1
                        continue
                    ev_db.important_info_localized = loc_infos
                    updated += 1
                    log.info("  → %s", loc_infos)

                    # Commit every 50 events to avoid a massive transaction
                    if updated % 50 == 0:
                        await db.commit()
                        log.info("Committed %d updates so far.", updated)
                except Exception as exc:
                    # Catches ValueError from host_guard_hook SSRF guard + anything unexpected
                    skipped += 1
                    log.warning("  → error processing event_id=%d: %s", ev.id, exc)
                finally:
                    # Always pace requests regardless of outcome
                    await asyncio.sleep(HTML_LISTING_LOCALE_FETCH_DELAY_SECONDS)

            await db.commit()

    print(f"\nDone. updated={updated} skipped={skipped}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill important_info_localized for existing Piletilevi events."
    )
    parser.add_argument("--yes", action="store_true", help="Write results to DB.")
    parser.add_argument(
        "--limit",
        type=int,
        default=BACKFILL_DEFAULT_LIMIT,
        help=f"Max events to process (default {BACKFILL_DEFAULT_LIMIT}).",
    )
    args = parser.parse_args()
    asyncio.run(main(confirm=args.yes, limit=args.limit))
