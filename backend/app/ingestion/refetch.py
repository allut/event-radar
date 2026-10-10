"""Daily detail-page refetch sync for future events.

Re-fetches every future event's detail page (``event.url``), parses the
schema.org JSON-LD ``Event`` block, and reconciles the stored row against the
source: updating ``venue_name``/``venue_address``/``lat``/``lng``/price fields
when the detail page reports a *different* value, and filling them when they were
empty — never clobbering a good stored value with nothing.

Generic JSON-LD, not Fienta-specific: it no-ops on any page without an ``Event``
block, so it is safe across sources (Fienta is the only beneficiary today; HTML
sources already fetch detail at ingest).

Coexists with the geocode passes (``extract_address_from_venue_name`` /
``copy_venue_from_siblings``): ``venue_address`` and ``lat``/``lng`` are
reconciled as one coupled unit so they never drift apart, and a clean stored
``venue_name`` is never overwritten by a suspect detail name. See the module
docstring of ``geocode.py`` and the project plan for the full rationale.

A locale pinned via the claim-editing surface (#416/#417,
``Event.pinned_fields``, ``app/claims/pinning.py``) is skipped by the
title/description locale backfill — see ``_backfill_localized_text``. Price
fields are never pinned (co-authoritative per #416) so this pass keeps
reconciling them unconditionally; a claimed event is excluded from
``_select_candidates`` by the same organizer-submission signals every other
organizer-owned event already is, so no additional filtering is needed there.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    DEFAULT_CURRENCY,
    EVENT_STATUS_CLASSIFIED,
    EVENT_STATUS_PUBLISHED,
    GEOCODE_COORD_QUANT_DECIMALS,
    HTML_PARSER,
    HTTP_TIMEOUT_SECONDS,
    LOCALIZED_TEXT_FIENTA_LOCALES,
    REFETCH_COMMIT_INTERVAL_SECONDS,
    REFETCH_MAX_PER_RUN,
    REFETCH_MAX_RUN_SECONDS,
    REFETCH_MIN_INTERVAL_DAYS,
    REFETCH_PLACEHOLDER_VENUE_NAMES,
    REFETCH_PRICE_TOLERANCE,
    REFETCH_HOST_CONCURRENCY,
    REFETCH_REQUEST_DELAY_SECONDS,
    SOURCE_KIND_USER_SUBMISSION,
    TALLINN_TZ,
    VENUE_NAME_MAX_LEN,
)
from app.ingestion.selectors import (
    ESTONIA_CONCERT_HALL_HOST,
    KUMU_HOST,
    PILETILEVI_HOST,
    SUSPECT_LOCALE_TITLE_PREFIXES,
)
from app.ingestion.content_filters import content_flags
from app.ingestion.http_client import (
    host_guard_hook,
    host_is_allowed,
    http_get,
    normalized_hostname,
)
from app.ingestion.jsonld import (
    extract_jsonld_event_text,
    location_from_jsonld_items,
    offers_from_jsonld_items,
    parse_jsonld_event_items,
)
from app.ingestion.locale_urls import (
    fetch_locale_variants,
    locale_from_html_lang,
    locale_from_url_path,
)
from app.claims.lifecycle import bulk_dormant_pinned_event_ids
from app.claims.pinning import pin_key
from app.ingestion.price_fallback import PRICE_FALLBACK_EXTRACTORS
from app.ingestion.sanitize import sanitize_html
from app.ingestion.geocode import is_suspect_venue_name
from app.ingestion.sources.estonia_concert_hall import (
    estonia_concert_hall_localized_text,
)
from app.ingestion.sources.kumu import kumu_localized_text
from app.ingestion.sources.piletilevi import piletilevi_localized_text
from app.models.models import Event, EventSource, Source

log = logging.getLogger(__name__)

# Maps event URL hostname → locale-text extractor. Default (no entry) is the
# generic JSON-LD reader (extract_jsonld_event_text). KUMU/ECH need a custom
# extractor because their detail pages carry no schema.org Event JSON-LD block
# at all; Piletilevi needs one because its JSON-LD description is
# source-flattened plain text with paragraph breaks collapsed (glues
# sentences together) — the HTML .event__description block preserves them.
# Normalized hostname (leading "www." stripped) so both bare and www variants match.
_LocaleTextExtractor = Callable[[BeautifulSoup], tuple[str | None, str | None]]

_LOCALE_TEXT_EXTRACTORS: dict[str, _LocaleTextExtractor] = {
    KUMU_HOST: kumu_localized_text,
    ESTONIA_CONCERT_HALL_HOST: estonia_concert_hall_localized_text,
    PILETILEVI_HOST: piletilevi_localized_text,
}


def _is_suspect_locale_title(title: str, normalized_host: str) -> bool:
    """True when a stored localized title looks like site-level (homepage) content.

    Detects garbage written by a broken hreflang link to the venue's own
    homepage instead of the event page — these are re-fetchable on the next run.
    The prefix must be followed by a separator (" -") or be the entire title to
    avoid rejecting legitimate event titles in the genitive form (e.g.
    "Kumu kunstimuuseumi 100. aastapäeva näitus").
    """
    prefix = SUSPECT_LOCALE_TITLE_PREFIXES.get(normalized_host)
    if prefix is None:
        return False
    return title == prefix or title.startswith(prefix + " -")


def _is_empty_venue_name(name: str | None) -> bool:
    """True when a stored venue_name is missing or a placeholder (replaceable)."""
    if name is None:
        return True
    stripped = name.strip()
    if not stripped:
        return True
    return stripped.lower() in REFETCH_PLACEHOLDER_VENUE_NAMES


def _price_differs(stored: float | None, fresh: float) -> bool:
    """True when a detail-page price differs from the stored value beyond tolerance.

    A NULL stored price with any fresh price counts as a change (fill case).
    ``stored`` is a ``Decimal`` (Numeric column) or None at runtime; ``fresh`` is a float.
    """
    if stored is None:
        return True
    return abs(float(stored) - fresh) > REFETCH_PRICE_TOLERANCE


def _coords_differ(
    stored_lat: float | None,
    stored_lng: float | None,
    fresh_lat: float,
    fresh_lng: float,
) -> bool:
    """True when fresh coords differ from stored beyond the quantization grid.

    NULL stored coords with present fresh coords count as a change (fill case).
    Comparison is rounded to GEOCODE_COORD_QUANT_DECIMALS — the same grid
    copy_venue_from_siblings uses — so a sub-meter re-store reads as unchanged.
    """
    if stored_lat is None or stored_lng is None:
        return True
    q = GEOCODE_COORD_QUANT_DECIMALS
    return (
        round(stored_lat, q) != round(fresh_lat, q)
        or round(stored_lng, q) != round(fresh_lng, q)
    )


async def _select_candidates(db: AsyncSession, now: datetime) -> list[Event]:
    """Future events with a URL, not synced within REFETCH_MIN_INTERVAL_DAYS.

    Ordered oldest-synced-first so a capped run prioritizes the
    least-recently-synced events. Organizer submissions are excluded twice,
    on independent signals: refetch reconciles third-party scraped detail
    pages, but an organizer owns their row and edits it directly via PATCH —
    never fetching an organizer-controlled url is what lets the submit path
    drop the host allowlist (see adapter.py::insert_normalized_event, which
    decides that same drop off `source.kind`). Excluding only by
    `submitted_by_organizer_id` would leave the two guards coupled by
    convention alone: a future insert against a user_submission-kind source
    that forgot to set `submitted_by_organizer_id` would still pass this
    filter and get its host-unchecked url fetched here. The `NOT EXISTS`
    clause below excludes by the same `source.kind` adapter.py keys off,
    independent of whether the organizer attribution column got set.
    """
    due_before = now - timedelta(days=REFETCH_MIN_INTERVAL_DAYS)
    from_user_submission_source = exists(
        select(1)
        .select_from(EventSource)
        .join(Source, Source.id == EventSource.source_id)
        .where(
            EventSource.event_id == Event.id,
            Source.kind == SOURCE_KIND_USER_SUBMISSION,
        )
    )
    rows = await db.scalars(
        select(Event)
        .where(
            Event.url.is_not(None),
            Event.starts_at > now,
            Event.submitted_by_organizer_id.is_(None),
            ~from_user_submission_source,
            or_(
                Event.detail_refetched_at.is_(None),
                Event.detail_refetched_at < due_before,
            ),
        )
        .order_by(Event.detail_refetched_at.asc().nulls_first())
        .limit(REFETCH_MAX_PER_RUN)
    )
    return list(rows.all())


def _allowed_refetch_hosts(candidates: list[Event]) -> frozenset[str]:
    """Host allowlist for the run's SSRF guard.

    Built from candidate URLs intersected with the fixed ALLOWED_SOURCE_HOSTS
    allowlist — NOT from the raw candidate URLs alone. A candidate's event.url
    is untrusted (parsed from third-party content); deriving the guard purely
    from it would let a malicious stored URL allowlist itself. The intersection
    permits every legitimate source host while never widening the guard beyond
    known-good hosts. Hostnames are deduped before the host_is_allowed scan —
    up to 1,000 candidates typically share ~4 hostnames, so checking each
    candidate individually reruns the same ALLOWED_SOURCE_HOSTS scan for
    hosts already known good or already known bad.
    """
    candidate_hosts = {
        h for e in candidates if (h := urlsplit(e.url or "").hostname)
    }
    return frozenset(h for h in candidate_hosts if host_is_allowed(h))


async def _backfill_localized_text(
    client: httpx.AsyncClient,
    event: Event,
    soup: BeautifulSoup,
    url: str,
    normalized_host: str,
    summary: dict,
    dormant_event_ids: set[int],
) -> None:
    """Backfill missing locale keys of title/description from locale-variant pages.

    Gated per-locale (not per-column) and merged into the existing dicts, so a
    partially-filled column self-heals missing locales. A stored title that
    looks like site-level homepage content (see _is_suspect_locale_title)
    counts as missing and is re-fetched. A locale pinned via the claim-editing
    surface (#416/#417) is excluded regardless of missing/suspect state — an
    organizer's correction (including an intentional clear) must not be
    silently refilled from the source — UNLESS the covering claim has since
    gone dormant (#422: a dormant claim's pins stop applying), in which case
    the pin is treated as absent and the source value backfills normally.
    """
    existing_titles: dict[str, str] = (
        dict(event.title_localized) if event.title_localized else {}
    )
    existing_descs: dict[str, str] = (
        dict(event.description_localized) if event.description_localized else {}
    )
    # FAQ #claimed-edits describes this behaviour — update the copy (all locales) if it changes
    pinned = set() if event.id in dormant_event_ids else set(event.pinned_fields)
    missing_title_locales = {
        loc for loc in LOCALIZED_TEXT_FIENTA_LOCALES
        if pin_key("title", loc) not in pinned
        and (
            loc not in existing_titles
            or _is_suspect_locale_title(existing_titles[loc], normalized_host)
        )
    }
    missing_desc_locales = {
        loc for loc in LOCALIZED_TEXT_FIENTA_LOCALES
        if pin_key("description", loc) not in pinned and loc not in existing_descs
    }
    locales_to_fetch = missing_title_locales | missing_desc_locales
    if not locales_to_fetch:
        return

    # JSON-LD extractor for Fienta/Piletilevi; og:title + CSS selector for
    # KUMU/ECH whose pages carry no Event JSON-LD block.
    extract_text = _LOCALE_TEXT_EXTRACTORS.get(normalized_host, extract_jsonld_event_text)

    def _extract(
        page_soup: BeautifulSoup, _locale: str
    ) -> tuple[str | None, str | None, str | None]:
        title, desc = extract_text(page_soup)
        return title, desc, None

    base_locale = locale_from_url_path(
        url, LOCALIZED_TEXT_FIENTA_LOCALES
    ) or locale_from_html_lang(soup, LOCALIZED_TEXT_FIENTA_LOCALES)
    fetched_titles, fetched_descs, _ = await fetch_locale_variants(
        client,
        soup,
        url,
        LOCALIZED_TEXT_FIENTA_LOCALES,
        _extract,
        fetch=http_get,
        wait=lambda: asyncio.sleep(REFETCH_REQUEST_DELAY_SECONDS),
        source_label="refetch",
        base_locale=base_locale,
        wanted_locales=locales_to_fetch,
    )

    loc_titles = {
        loc: title
        for loc, title in fetched_titles.items()
        if loc in missing_title_locales
    }
    loc_descs: dict[str, str] = {}
    for loc, desc in fetched_descs.items():
        if loc in missing_desc_locales:
            sanitized = sanitize_html(desc)
            if sanitized:
                loc_descs[loc] = sanitized
    if loc_titles:
        existing_titles.update(loc_titles)
        event.title_localized = existing_titles
    if loc_descs:
        existing_descs.update(loc_descs)
        event.description_localized = existing_descs
    if loc_titles or loc_descs:
        summary["localized_text_backfilled"] += 1


async def _process_one(
    client: httpx.AsyncClient,
    event: Event,
    summary: dict,
    now: datetime,
    dormant_event_ids: set[int],
) -> bool:
    """Fetch one event's detail page, backfill locales, and reconcile fields.

    Returns False when the fetch itself failed (caller skips the pacing sleep
    and leaves detail_refetched_at untouched so the event retries next run).
    """
    url = event.url
    assert url is not None  # guaranteed by the candidate query
    try:
        response = await http_get(client, url)
    except (httpx.HTTPStatusError, httpx.RequestError, ValueError) as exc:
        # ValueError: host_guard_hook's SSRF guard — an expected per-item
        # rejection (e.g. a pre-guard row or off-host redirect), degrades like
        # any fetch failure.
        summary["failed"] += 1
        log.warning("refetch failed url=%s: %s", url, exc)
        return False

    summary["fetched"] += 1
    soup = BeautifulSoup(response.text, HTML_PARSER)
    normalized_host = normalized_hostname(url)
    jsonld_items = parse_jsonld_event_items(soup)
    location = location_from_jsonld_items(jsonld_items)
    price_min, price_max, currency, has_free_tier = offers_from_jsonld_items(jsonld_items)
    if price_min is None and price_max is None and currency is None and not has_free_tier:
        fallback = PRICE_FALLBACK_EXTRACTORS.get(normalized_host)
        if fallback is not None:
            price_min, price_max, currency, has_free_tier = fallback(soup)

    # Runs before the no_data gate so events whose JSON-LD has only text
    # (no location/offers) still receive localized titles/descriptions.
    await _backfill_localized_text(
        client, event, soup, url, normalized_host, summary, dormant_event_ids
    )

    parsed_anything = location is not None or any(
        v is not None for v in (price_min, price_max, currency)
    )
    if not parsed_anything:
        summary["no_data"] += 1
        _mark_synced(event, now)
        return True

    changed = _reconcile(
        event,
        summary,
        detail_name=location.get("venue_name") if location else None,
        detail_address=location.get("venue_address") if location else None,
        detail_lat=location.get("lat") if location else None,
        detail_lng=location.get("lng") if location else None,
        price_min=price_min,
        price_max=price_max,
        currency=currency,
        has_free_tier=has_free_tier,
    )
    if not changed:
        summary["unchanged"] += 1
    _mark_synced(event, now)
    return True


async def refetch_event_details(db: AsyncSession) -> dict:
    """Re-fetch detail pages for all future events and reconcile stored fields.

    Single pass, mirrors geocode_pending. No missing-field filter (all future
    events are candidates) and no attempt cap. Returns a summary dict; the
    caller commits (plus periodic mid-loop commits for Neon keep-alive).
    """
    now = datetime.now(TALLINN_TZ)
    candidates = await _select_candidates(db, now)
    dormant_event_ids = await bulk_dormant_pinned_event_ids(db, candidates)

    summary = {
        "candidates": len(candidates),
        "fetched": 0,
        "address_changed": 0,
        "coords_changed": 0,
        "venue_changed": 0,
        "price_changed": 0,
        "unchanged": 0,
        "no_data": 0,
        "failed": 0,
        "flagged_explicit": 0,
        "flagged_non_event": 0,
        "localized_text_backfilled": 0,
    }
    if not candidates:
        return summary

    last_commit = time.monotonic()
    run_deadline = time.monotonic() + REFETCH_MAX_RUN_SECONDS
    # The politeness delay protects each *source host*, not the whole run, so
    # candidates are grouped by host: each host is walked sequentially at the
    # REFETCH_REQUEST_DELAY_SECONDS pace while different hosts proceed in
    # parallel (Big-O audit #14). Candidate order (oldest sync first) is kept
    # within every host group.
    by_host: dict[str, list[Event]] = {}
    for event in candidates:
        by_host.setdefault(normalized_hostname(event.url), []).append(event)
    host_semaphore = asyncio.Semaphore(REFETCH_HOST_CONCURRENCY)
    commit_lock = asyncio.Lock()

    async def _refetch_host(client: httpx.AsyncClient, host_events: list[Event]) -> None:
        nonlocal last_commit
        async with host_semaphore:
            for event in host_events:
                if time.monotonic() >= run_deadline:
                    # detail_refetched_at ordering (_select_candidates) means
                    # the events left unprocessed here sort first next run.
                    summary["deadline_stopped"] = True
                    break
                fetched = await _process_one(client, event, summary, now, dormant_event_ids)
                if fetched:
                    await asyncio.sleep(REFETCH_REQUEST_DELAY_SECONDS)
                if time.monotonic() - last_commit >= REFETCH_COMMIT_INTERVAL_SECONDS:
                    # One committer at a time: hosts share the AsyncSession.
                    # Workers issue no queries on it (only attribute writes on
                    # already-loaded rows, expire_on_commit=False), so a write
                    # racing the flush is at worst picked up by the next
                    # commit or re-reconciled by the next run.
                    async with commit_lock:
                        await db.commit()
                        last_commit = time.monotonic()

    # Follow Fienta's locale 302-redirects with a host-pinning SSRF guard
    # (see _allowed_refetch_hosts for why the allowlist is intersected).
    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT_SECONDS,
        follow_redirects=True,
        event_hooks={"request": [host_guard_hook(_allowed_refetch_hosts(candidates))]},
    ) as client:
        outcomes = await asyncio.gather(
            *(_refetch_host(client, host_events) for host_events in by_host.values()),
            return_exceptions=True,
        )
    failures = [o for o in outcomes if isinstance(o, BaseException)]
    for failure in failures:
        log.error("refetch host worker raised", exc_info=failure)
    if failures:
        raise failures[0]

    return summary


def _mark_synced(event: Event, now: datetime) -> None:
    """Bump the throttle fields, run regardless of whether any value changed."""
    event.detail_refetch_count = (event.detail_refetch_count or 0) + 1
    event.detail_refetched_at = now


def _reconcile_price(
    event: Event,
    summary: dict,
    price_min: float | None,
    price_max: float | None,
    currency: str | None,
    has_free_tier: bool,
) -> bool:
    """Update each price field on drift, fill on empty, never clobber with nothing.

    Overrides the "ingest-set prices are authoritative" rule — a price change
    at the source should win — but a no-offers refetch leaves stored prices.
    Caller-supplied values come either from structured JSON-LD offers or,
    for a host with no offers block at all (PRICE_FALLBACK_EXTRACTORS, #424),
    a selector/regex heuristic over page text — both are treated as equally
    trustworthy here; the heuristic path (kumu_price_bounds) already strips
    fee clauses and truncates to the same window ingest/classify use to keep
    its false-positive rate low.
    """
    price_changed = False
    if price_min is not None and _price_differs(event.price_min, price_min):
        event.price_min = price_min  # type: ignore[assignment]
        price_changed = True
    if price_max is not None and _price_differs(event.price_max, price_max):
        event.price_max = price_max  # type: ignore[assignment]
        price_changed = True
    if currency is not None and event.currency != currency:
        event.currency = currency
        price_changed = True
    if has_free_tier and not event.has_free_tier:
        event.has_free_tier = True
        price_changed = True
    # A refetch can fill/update price_min/price_max above while leaving
    # currency NULL (detail page reports no currency) — default it so a
    # refetched free event doesn't reintroduce the priceCurrency-missing
    # state the JSON-LD prerender gate rejects (issue #236).
    if event.price_min is not None and event.currency is None:
        event.currency = DEFAULT_CURRENCY
        price_changed = True
    if price_changed:
        summary["price_changed"] += 1
    return price_changed


def _reconcile_location(
    event: Event,
    summary: dict,
    detail_address: str | None,
    detail_lat: float | None,
    detail_lng: float | None,
) -> bool:
    """Reconcile venue_address + lat/lng as one coupled unit, never
    field-independently, so the two can't drift apart (see geocode coexistence).
    """
    address_differs = (
        detail_address is not None and detail_address != event.venue_address
    )
    if address_differs:
        event.venue_address = detail_address
        summary["address_changed"] += 1
        if detail_lat is not None and detail_lng is not None:
            # Consistent triple straight from the source — beats Nominatim/sibling guess.
            if _coords_differ(event.lat, event.lng, detail_lat, detail_lng):
                summary["coords_changed"] += 1
            event.lat, event.lng = detail_lat, detail_lng
        elif event.lat is not None or event.lng is not None:
            # New address, no source coords — NULL the stale coords (derived from a
            # *different* address) so geocode_pending re-resolves them.
            event.lat, event.lng = None, None
            summary["coords_changed"] += 1
        return True
    if (
        detail_lat is not None
        and detail_lng is not None
        and _coords_differ(event.lat, event.lng, detail_lat, detail_lng)
    ):
        # Address absent/identical but source coords moved — direct geo update.
        event.lat, event.lng = detail_lat, detail_lng
        summary["coords_changed"] += 1
        return True
    return False


def _reconcile_venue_name(event: Event, summary: dict, detail_name: object) -> bool:
    """Take the JSON-LD location.name; re-run content-safety checks on change.

    A clean stored name is only overwritten by a clean (non-suspect) detail
    name — a glued/suspect name would undo extract_address_from_venue_name.
    The layer-1 explicit/non-event re-checks run here because a venue_name
    change is the only post-ingest write path that can land on an
    already-published event; a newly-flagged published event is demoted to
    classified so the publish gate keeps it out of the public feed.
    """
    name = detail_name.strip() if isinstance(detail_name, str) else None
    if not name:
        return False
    if _is_empty_venue_name(event.venue_name):
        if name == event.venue_name:
            return False
        event.venue_name = name[:VENUE_NAME_MAX_LEN]
    elif name != event.venue_name and not is_suspect_venue_name(name):
        event.venue_name = name[:VENUE_NAME_MAX_LEN]
    else:
        return False

    summary["venue_changed"] += 1
    if not event.is_explicit or not event.is_non_event:
        # Single pass over both flags (Big-O audit #5, item 2.3) — title and
        # venue_name would otherwise each be re-parsed by is_explicit_text and
        # is_non_event_text.
        newly_explicit, newly_non_event = content_flags(
            event.title_orig,
            event.description_orig,
            event.venue_name,
            event.important_info,
        )
        if not event.is_explicit and newly_explicit:
            event.is_explicit = True
            summary["flagged_explicit"] += 1
            if event.status == EVENT_STATUS_PUBLISHED:
                event.status = EVENT_STATUS_CLASSIFIED
        if not event.is_non_event and newly_non_event:
            event.is_non_event = True
            summary["flagged_non_event"] += 1
            if event.status == EVENT_STATUS_PUBLISHED:
                event.status = EVENT_STATUS_CLASSIFIED
    return True


def _reconcile(
    event: Event,
    summary: dict,
    *,
    detail_name: object,
    detail_address: str | None,
    detail_lat: float | None,
    detail_lng: float | None,
    price_min: float | None,
    price_max: float | None,
    currency: str | None,
    has_free_tier: bool = False,
) -> bool:
    """Apply the three reconciliation rules to one event in place. Returns True
    if any field was changed. Increments the matching ``summary`` counters."""
    price_changed = _reconcile_price(
        event, summary, price_min, price_max, currency, has_free_tier
    )
    location_changed = _reconcile_location(
        event, summary, detail_address, detail_lat, detail_lng
    )
    name_changed = _reconcile_venue_name(event, summary, detail_name)
    return price_changed or location_changed or name_changed
