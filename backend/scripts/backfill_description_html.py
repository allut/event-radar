"""One-off maintenance: re-fetch and sanitize description/important_info as HTML.

Re-fetches each Piletilevi/KUMU/ECH event's detail page (and locale alternates)
and re-stores sanitized HTML in description_orig, important_info,
description_localized, and important_info_localized.

Run from backend/ with the venv active:
    python scripts/backfill_description_html.py            # dry run
    python scripts/backfill_description_html.py --yes      # write to DB
    python scripts/backfill_description_html.py --yes --limit 50  # cap rows
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select

from app.constants import (
    BACKFILL_DEFAULT_LIMIT,
    ESTONIA_CONCERT_HALL_DESCRIPTION_SELECTOR,
    FIENTA_DESCRIPTION_SELECTOR,
    HTML_LISTING_LOCALE_FETCH_DELAY_SECONDS,
    HTTP_TIMEOUT_SECONDS,
    HTTP_USER_AGENT,
    KUMU_DESCRIPTION_SELECTOR,
    LOCALIZED_TEXT_FIENTA_LOCALES,
    LOCALIZED_TEXT_HTML_LOCALES,
    LOCALIZED_TEXT_MAX_DESC_CHARS,
    PILETILEVI_DETAIL_DESC_SELECTOR,
    SOURCE_SLUG_ESTONIA_CONCERT_HALL,
    SOURCE_SLUG_FIENTA,
    SOURCE_SLUG_KUMU,
    SOURCE_SLUG_PILETILEVI,
)
from app.ingestion.http_client import host_guard_hook, http_get
from app.ingestion.locale_urls import (
    locale_from_html_lang,
    locale_from_url_path,
    localized_detail_urls,
)
from app.ingestion.sanitize import html_to_text, sanitize_html
from app.ingestion.sources.html_listing import (
    _piletilevi_important_info,
    estonia_concert_hall_localized_text,
    kumu_localized_text,
)
from app.logging_config import configure_logging
from app.models.models import Event, EventSource, Source
from app.routers.utils import mask_db_url

configure_logging()
log = logging.getLogger(__name__)

SUPPORTED_SLUGS = {SOURCE_SLUG_PILETILEVI, SOURCE_SLUG_KUMU, SOURCE_SLUG_ESTONIA_CONCERT_HALL, SOURCE_SLUG_FIENTA}


def _extract_description(soup: BeautifulSoup, source_slug: str) -> str | None:
    if source_slug == SOURCE_SLUG_PILETILEVI:
        tag = soup.select_one(PILETILEVI_DETAIL_DESC_SELECTOR)
        return sanitize_html(tag.decode_contents()) if tag else None
    if source_slug == SOURCE_SLUG_KUMU:
        tag = soup.select_one(KUMU_DESCRIPTION_SELECTOR)
        if tag:
            html = sanitize_html(tag.decode_contents())
            return html[:LOCALIZED_TEXT_MAX_DESC_CHARS] if html else None
        return None
    if source_slug == SOURCE_SLUG_ESTONIA_CONCERT_HALL:
        tag = soup.select_one(ESTONIA_CONCERT_HALL_DESCRIPTION_SELECTOR)
        if tag:
            html = sanitize_html(tag.decode_contents())
            return html[:LOCALIZED_TEXT_MAX_DESC_CHARS] if html else None
        return None
    return None


def _extract_localized_text(
    soup: BeautifulSoup, source_slug: str
) -> tuple[str | None, str | None]:
    if source_slug == SOURCE_SLUG_KUMU:
        return kumu_localized_text(soup)
    if source_slug == SOURCE_SLUG_ESTONIA_CONCERT_HALL:
        return estonia_concert_hall_localized_text(soup)
    return None, None


async def _process_event(
    client: httpx.AsyncClient,
    event: Event,
    source_slug: str,
    write: bool,
    stats: dict[str, int],
) -> None:
    if not event.url:
        stats["skip_no_url"] += 1
        return

    try:
        resp = await http_get(client, event.url)
        soup = BeautifulSoup(resp.text, "html.parser")
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        log.warning("fetch failed event_id=%s url=%s: %s", event.id, event.url, exc)
        stats["fetch_error"] += 1
        return

    if source_slug == SOURCE_SLUG_FIENTA:
        # Fienta: primary-locale description comes from stored listing HTML.
        # The initial fetch is needed to detect the primary locale via resp.url
        # and to find alternate-locale URLs. Non-primary locales are scraped from
        # the div.rich-text element on each locale-prefixed detail page.
        new_desc = sanitize_html(event.description_orig)
        primary_locale = locale_from_url_path(
            str(resp.url), LOCALIZED_TEXT_FIENTA_LOCALES
        ) or locale_from_html_lang(soup, LOCALIZED_TEXT_FIENTA_LOCALES)
        if primary_locale is None and event.description_localized:
            # Fallback: match plain-text content against stored localized values.
            # Normalize whitespace so block-level HTML (`<p>A</p><p>B</p>`) and
            # already-stored plain text ("A B") compare equal.
            plain = " ".join((html_to_text(new_desc) or "").split())
            for loc, loc_desc in (event.description_localized or {}).items():
                if " ".join((html_to_text(loc_desc) or "").split()) == plain:
                    primary_locale = loc
                    break

        changed = False
        if new_desc and new_desc != event.description_orig:
            if write:
                event.description_orig = new_desc
            changed = True

        merged = dict(event.description_localized or {})
        if primary_locale and new_desc:
            merged[primary_locale] = new_desc

        # Fetch non-primary locale pages and extract HTML from div.rich-text.
        fienta_locale_urls = localized_detail_urls(soup, event.url, LOCALIZED_TEXT_FIENTA_LOCALES)
        for fl, fl_url in fienta_locale_urls.items():
            if primary_locale is not None and fl == primary_locale:
                continue
            try:
                if fl_url == event.url:
                    fl_soup = soup
                else:
                    await asyncio.sleep(HTML_LISTING_LOCALE_FETCH_DELAY_SECONDS)
                    fl_resp = await http_get(client, fl_url)
                    fl_soup = BeautifulSoup(fl_resp.text, "html.parser")
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                log.debug("fienta locale fetch failed event_id=%s locale=%s: %s", event.id, fl, exc)
                continue
            rich_text_tag = fl_soup.select_one(FIENTA_DESCRIPTION_SELECTOR)
            if rich_text_tag:
                loc_html = sanitize_html(rich_text_tag.decode_contents())
                if loc_html:
                    merged[fl] = loc_html

        if merged != dict(event.description_localized or {}):
            if write:
                event.description_localized = merged
            changed = True

        if changed:
            stats["updated"] += 1
            log.info(
                "%s event_id=%s source=%s",
                "wrote" if write else "would update",
                event.id,
                source_slug,
            )
        else:
            stats["unchanged"] += 1
        return

    new_desc = _extract_description(soup, source_slug)
    new_info: str | None = None
    if source_slug == SOURCE_SLUG_PILETILEVI:
        new_info = _piletilevi_important_info(soup, "en")

    changed = False
    if new_desc and new_desc != event.description_orig:
        if write:
            event.description_orig = new_desc
        changed = True

    if new_info and new_info != event.important_info:
        if write:
            event.important_info = new_info
        changed = True

    # Locale alternates
    if source_slug == SOURCE_SLUG_PILETILEVI:
        urls = localized_detail_urls(soup, event.url, LOCALIZED_TEXT_HTML_LOCALES)
        loc_descs: dict[str, str] = {}
        loc_infos: dict[str, str] = {}
        url_locale_pil = locale_from_url_path(event.url, LOCALIZED_TEXT_HTML_LOCALES)
        for locale in LOCALIZED_TEXT_HTML_LOCALES:
            loc_url = urls.get(locale)
            if not loc_url or loc_url == event.url:
                # Same page already fetched — seed from the main extraction so the
                # same-language localized field matches description_orig/important_info.
                if locale == url_locale_pil:
                    if new_desc:
                        loc_descs[locale] = new_desc
                    if new_info:
                        loc_infos[locale] = new_info
                elif url_locale_pil is None:
                    log.debug(
                        "event_id=%s: url has no locale segment, skipping same-lang seed",
                        event.id,
                    )
                continue
            await asyncio.sleep(HTML_LISTING_LOCALE_FETCH_DELAY_SECONDS)
            try:
                loc_resp = await http_get(client, loc_url)
                loc_soup = BeautifulSoup(loc_resp.text, "html.parser")
            except (httpx.HTTPStatusError, httpx.RequestError, ValueError) as exc:
                log.debug("locale fetch failed locale=%s: %s", locale, exc)
                continue
            loc_tag = loc_soup.select_one(PILETILEVI_DETAIL_DESC_SELECTOR)
            if loc_tag:
                html = sanitize_html(loc_tag.decode_contents())
                if html:
                    loc_descs[locale] = html
            loc_info_text = _piletilevi_important_info(loc_soup, locale)
            if loc_info_text:
                loc_infos[locale] = loc_info_text
        if loc_descs:
            merged_descs = dict(event.description_localized or {})
            merged_descs.update(loc_descs)
            if merged_descs != dict(event.description_localized or {}):
                if write:
                    event.description_localized = merged_descs
                changed = True
        if loc_infos:
            merged_infos = dict(event.important_info_localized or {})
            merged_infos.update(loc_infos)
            if merged_infos != dict(event.important_info_localized or {}):
                if write:
                    event.important_info_localized = merged_infos
                changed = True
    elif source_slug in (SOURCE_SLUG_KUMU, SOURCE_SLUG_ESTONIA_CONCERT_HALL):
        urls = localized_detail_urls(soup, event.url, LOCALIZED_TEXT_HTML_LOCALES)
        loc_descs = {}
        for locale in LOCALIZED_TEXT_HTML_LOCALES:
            loc_url = urls.get(locale)
            if not loc_url:
                continue
            url_locale = locale_from_url_path(event.url, LOCALIZED_TEXT_HTML_LOCALES)
            if locale == url_locale or loc_url == event.url:
                # Already fetched this page — assign new_desc directly; it is
                # already sanitized and truncated, so skip the reprocessing pipeline
                # that would double-truncate and potentially re-break tag boundaries.
                if new_desc:
                    loc_descs[locale] = new_desc
                continue
            await asyncio.sleep(HTML_LISTING_LOCALE_FETCH_DELAY_SECONDS)
            try:
                loc_resp = await http_get(client, loc_url)
                loc_soup = BeautifulSoup(loc_resp.text, "html.parser")
            except (httpx.HTTPStatusError, httpx.RequestError, ValueError) as exc:
                log.debug("locale fetch failed locale=%s: %s", locale, exc)
                continue
            _, loc_desc = _extract_localized_text(loc_soup, source_slug)
            if loc_desc:
                sanitized = sanitize_html(loc_desc)
                if sanitized:
                    loc_descs[locale] = sanitized[:LOCALIZED_TEXT_MAX_DESC_CHARS]
        if loc_descs:
            merged = dict(event.description_localized or {})
            merged.update(loc_descs)
            if merged != dict(event.description_localized or {}):
                if write:
                    event.description_localized = merged
                changed = True

    if changed:
        stats["updated"] += 1
        log.info(
            "%s event_id=%s source=%s",
            "wrote" if write else "would update",
            event.id,
            source_slug,
        )
    else:
        stats["unchanged"] += 1


async def main(write: bool, limit: int) -> None:
    from app.db import AsyncSessionLocal

    # Load phase: fetch all (event, source) pairs then close the session so it
    # doesn't stay open during the long HTTP fetch loop (Neon free tier drops
    # idle connections after ~5 min; 853 events × 0.5 s delay exceeds that).
    async with AsyncSessionLocal() as load_db:
        from app.config import settings

        log.info("DB: %s", mask_db_url(settings.DATABASE_URL or ""))

        rows = await load_db.execute(
            select(Event, Source)
            .join(EventSource, EventSource.event_id == Event.id)
            .join(Source, Source.id == EventSource.source_id)
            .where(Source.slug.in_(SUPPORTED_SLUGS))
            .where(Event.url.isnot(None))
            .order_by(Event.id)
            .limit(limit)
        )
        pairs = rows.all()
        load_db.expunge_all()
    log.info("Found %d events to process", len(pairs))

    stats: dict[str, int] = {
        "updated": 0,
        "unchanged": 0,
        "fetch_error": 0,
        "skip_no_url": 0,
        "skip_deleted": 0,
    }

    allowed_hosts = frozenset(
        h for event, _ in pairs if (h := urlsplit(event.url or "").hostname)
    )
    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT_SECONDS,
        headers={"User-Agent": HTTP_USER_AGENT},
        follow_redirects=True,
        event_hooks={"request": [host_guard_hook(allowed_hosts)]},
    ) as client:
        async with AsyncSessionLocal() as db:
            for i, (event, source) in enumerate(pairs, 1):
                await asyncio.sleep(HTML_LISTING_LOCALE_FETCH_DELAY_SECONDS)
                if write:
                    # Re-fetch within the write session so SQLAlchemy tracks mutations.
                    event_db = await db.get(Event, event.id)
                    if event_db is None:
                        stats["skip_deleted"] += 1
                        log.warning("event id=%d no longer in DB, skipping", event.id)
                        continue
                    await _process_event(client, event_db, source.slug, write, stats)
                else:
                    # Dry run: use detached objects (no DB needed, just read cached attrs).
                    await _process_event(client, event, source.slug, write, stats)
                if write and i % 50 == 0:
                    await db.commit()
                    log.info("Committed batch at %d/%d events", i, len(pairs))
            if write and len(pairs) % 50 != 0:
                await db.commit()

    log.info(
        "Done. updated=%d unchanged=%d fetch_error=%d skip_no_url=%d skip_deleted=%d",
        stats["updated"],
        stats["unchanged"],
        stats["fetch_error"],
        stats["skip_no_url"],
        stats["skip_deleted"],
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="Write changes to DB")
    parser.add_argument("--limit", type=int, default=BACKFILL_DEFAULT_LIMIT)
    args = parser.parse_args()
    asyncio.run(main(write=args.yes, limit=args.limit))
