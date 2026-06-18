"""Nominatim geocoding for events that have a venue_address but no lat/lng."""

import asyncio
import logging
import re
from collections import Counter

import httpx
from rapidfuzz.fuzz import ratio as fuzz_ratio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    ESTONIAN_STREET_TYPE_WORDS,
    GEOCODE_COUNTRY_SUFFIX,
    GEOCODE_COUNTY_RE,
    GEOCODE_FLOOR_RE,
    GEOCODE_INITIAL_RE,
    GEOCODE_MAX_PER_RUN,
    GEOCODE_REQUEST_DELAY_SECONDS,
    GEOCODE_SECONDARY_UNIT_RE,
    GEOCODE_UNIT_SUFFIX_RE,
    HTTP_TIMEOUT_SECONDS,
    NON_GEOCODABLE_VENUE_NAMES,
    NOMINATIM_BASE_URL,
    NOMINATIM_USER_AGENT,
    VENUE_NAME_PARENS_RE,
    VENUE_SIBLING_RATIO_THRESHOLD,
)
from app.ingestion.base import http_get
from app.models.models import Event

log = logging.getLogger(__name__)

# Pre-compiled patterns built from constants — avoids re-compiling per call.
_STREET_TYPE_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in ESTONIAN_STREET_TYPE_WORDS) + r")\b",
    re.IGNORECASE,
)
_INITIAL_RE = re.compile(GEOCODE_INITIAL_RE)
_UNIT_SUFFIX_RE = re.compile(GEOCODE_UNIT_SUFFIX_RE, re.IGNORECASE)
_FLOOR_RE = re.compile(GEOCODE_FLOOR_RE, re.IGNORECASE)
_COUNTY_RE = re.compile(GEOCODE_COUNTY_RE, re.IGNORECASE)
_SECONDARY_UNIT_RE = re.compile(GEOCODE_SECONDARY_UNIT_RE, re.IGNORECASE)
_VENUE_PARENS_PATTERN = re.compile(VENUE_NAME_PARENS_RE)


def canonical_venue_name(name: str) -> str:
    """Reduce a venue_name to its matchable core for sibling matching.

    Drops parenthetical segments ("(STL)"), keeps only the text before the first
    comma (sheds glued-on address tails like ", Kotzebue tänav, Tallinn, Eesti"),
    collapses whitespace, and lowercases. Returns "" when nothing survives.
    """
    core = _VENUE_PARENS_PATTERN.sub("", name)
    core = core.split(",", 1)[0]
    return re.sub(r"\s+", " ", core).strip().lower()


def _representative_address(
    rows: list[tuple[str | None, float | None, float | None]],
) -> str | None:
    """Pick a deterministic donor address: most common string, lexicographic tie-break."""
    counts = Counter(addr for addr, _lat, _lng in rows if addr is not None)
    if not counts:
        return None
    return min(counts, key=lambda a: (-counts[a], a))


def normalize_address_for_geocoding(address: str) -> str:
    """Return a Nominatim-friendly version of a Fienta venue_address.

    Strips Estonian street-type words entirely (OSM stores streets by bare name,
    so the type word is what makes the match fail), drops a leading personal-name
    initial, unit suffixes, floor notes, and county markers, then appends
    ", Estonia" to anchor country matching. The whitespace-collapse cleans up the
    gaps left by stripping. The stored venue_address is never mutated — query-only.
    """
    result = address
    result = _INITIAL_RE.sub("", result)
    result = _FLOOR_RE.sub("", result)
    result = _COUNTY_RE.sub("", result)
    result = _SECONDARY_UNIT_RE.sub("", result)
    result = _UNIT_SUFFIX_RE.sub("", result)
    result = _STREET_TYPE_PATTERN.sub("", result)
    result = re.sub(r"\s+", " ", result).strip().rstrip(",").strip()
    if not result.endswith(GEOCODE_COUNTRY_SUFFIX):
        result += GEOCODE_COUNTRY_SUFFIX
    return result


async def geocode_address(
    client: httpx.AsyncClient, address: str, original: str | None = None
) -> tuple[float, float] | None:
    """Look up an address via Nominatim, returning ``(lat, lng)`` or None if no match.

    ``address`` is the normalized query sent to Nominatim.
    ``original`` is the raw venue_address (used only in the no-match log line).
    """
    response = await http_get(
        client,
        NOMINATIM_BASE_URL,
        params={"q": address, "format": "json", "limit": 1},
        headers={"User-Agent": NOMINATIM_USER_AGENT},
    )
    try:
        results = response.json()
        if not results:
            log.warning(
                "geocode no match: query=%r original=%r",
                address,
                original or address,
            )
            return None
        return float(results[0]["lat"]), float(results[0]["lon"])
    except (KeyError, TypeError, ValueError):
        return None


async def copy_venue_from_siblings(db: AsyncSession) -> int:
    """Copy venue_address + coords onto address-less events from a sibling venue.

    Two queries (honors the no-N+1 batch rule): one for targets (venue_name set,
    venue_address NULL), one for all geocoded donors (distinct venue_name →
    address/coords where both are present). Matching is on the *canonical* venue
    core (parens + glued-on address tails stripped, see canonical_venue_name) via
    symmetric ``fuzz.ratio >= VENUE_SIBLING_RATIO_THRESHOLD``, so "Sõltumatu Tantsu
    Lava" matches a "Sõltumatu Tantsu Lava (STL)" donor (canonicalization makes the
    cores equal). A symmetric ratio is used rather than token_set_ratio so a short
    comma-split core can't score 100 against an unrelated longer donor. The ambiguity
    guard keys on
    distinct *coordinates*, not the full ``(address, lat, lng)`` tuple — one physical
    venue legitimately carries several address spellings at one coord, and only a
    genuine multi-location name (>1 distinct coord) is skipped + logged. Non-physical
    venue names (NON_GEOCODABLE_VENUE_NAMES) are skipped on both sides. venue_name
    itself is never altered. Returns the number of events updated; the caller commits.
    """
    targets = (
        await db.scalars(
            select(Event)
            .where(Event.venue_name.is_not(None), Event.venue_address.is_(None))
            .limit(GEOCODE_MAX_PER_RUN)
        )
    ).all()
    if not targets:
        return 0

    donor_rows = (
        await db.execute(
            select(Event.venue_name, Event.venue_address, Event.lat, Event.lng)
            .where(
                Event.venue_name.is_not(None),
                Event.venue_address.is_not(None),
                Event.lat.is_not(None),
                Event.lng.is_not(None),
            )
            .distinct()
        )
    ).all()

    # Group donor rows by canonical name (bounds the fuzzy loop to distinct cores);
    # drop non-physical donors so virtual events can't inherit their junk coords.
    donor_addrs_by_canon: dict[
        str, list[tuple[str | None, float | None, float | None]]
    ] = {}
    for name, address, lat, lng in donor_rows:
        if name is None:
            continue
        canon = canonical_venue_name(name)
        if not canon or canon in NON_GEOCODABLE_VENUE_NAMES:
            continue
        donor_addrs_by_canon.setdefault(canon, []).append((address, lat, lng))

    copied = 0
    warned_ambiguous: set[str] = set()
    for event in targets:
        name = event.venue_name
        if name is None:
            continue
        target_canon = canonical_venue_name(name)
        if not target_canon or target_canon in NON_GEOCODABLE_VENUE_NAMES:
            continue

        matched_rows: list[tuple[str | None, float | None, float | None]] = []
        for donor_canon, rows in donor_addrs_by_canon.items():
            if fuzz_ratio(target_canon, donor_canon) >= VENUE_SIBLING_RATIO_THRESHOLD:
                matched_rows.extend(rows)
        if not matched_rows:
            continue

        # The donor query filters lat/lng non-null, so this is defense-in-depth:
        # a null coord can't form a valid pin, so it's excluded rather than written.
        distinct_coords = {
            (lat, lng)
            for _addr, lat, lng in matched_rows
            if lat is not None and lng is not None
        }
        if not distinct_coords:
            continue
        if len(distinct_coords) > 1:
            # One warning per ambiguous venue_name, not per event sharing it.
            if name not in warned_ambiguous:
                warned_ambiguous.add(name)
                log.warning(
                    "venue copy skipped: %r matches %d distinct locations",
                    name,
                    len(distinct_coords),
                )
            continue

        lat, lng = next(iter(distinct_coords))
        event.venue_address = _representative_address(matched_rows)
        event.lat = lat
        event.lng = lng
        copied += 1

    if copied:
        log.info("copied venue data from siblings to %d events", copied)
    return copied


async def geocode_pending(db: AsyncSession) -> dict:
    """Backfill lat/lng for events with a venue_address but no coordinates.

    Two queries total regardless of row count: one for pending events (capped at
    GEOCODE_MAX_PER_RUN), one to seed a normalized-query→coords cache from events
    already geocoded — avoids re-hitting Nominatim for venues we already know.
    The cache is keyed by the *normalized* query so format variants of one venue
    (e.g. "60a/9" vs "60a / 9") share a single Nominatim call.
    Remaining distinct addresses are geocoded serially with a delay between calls
    per Nominatim's usage policy (max 1 req/s).

    First copies venue data between same-name siblings (copy_venue_from_siblings),
    so copied coords count toward the run; any copied row still missing coords
    falls through to the Nominatim pass below. The sibling copy makes no Nominatim
    calls and sets lat, so copied rows are excluded from the pending query — the
    Nominatim-call ceiling stays GEOCODE_MAX_PER_RUN even though total DB writes
    across both passes (copy + geocode) can reach 2x that on disjoint event sets.
    """
    copied = await copy_venue_from_siblings(db)

    pending = (
        await db.scalars(
            select(Event)
            .where(Event.venue_address.is_not(None), Event.lat.is_(None))
            .limit(GEOCODE_MAX_PER_RUN)
        )
    ).all()
    if not pending:
        return {"pending": 0, "geocoded": 0, "failed": 0, "copied": copied}

    addresses = {event.venue_address for event in pending}
    cached_rows = (
        await db.execute(
            select(Event.venue_address, Event.lat, Event.lng).where(
                Event.venue_address.in_(addresses), Event.lat.is_not(None)
            )
        )
    ).all()
    # Seed cache by normalized query so format variants of the same venue hit once.
    cache: dict[str, tuple[float, float] | None] = {
        normalize_address_for_geocoding(address): (lat, lng)
        for address, lat, lng in cached_rows
    }

    geocoded = 0
    failed = 0
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        for event in pending:
            raw_address = event.venue_address
            assert raw_address is not None  # guaranteed by the WHERE clause above
            query = normalize_address_for_geocoding(raw_address)

            if query not in cache:
                try:
                    cache[query] = await geocode_address(client, query, original=raw_address)
                except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                    log.warning("geocode failed address=%s: %s", raw_address, exc)
                    cache[query] = None
                await asyncio.sleep(GEOCODE_REQUEST_DELAY_SECONDS)

            coords = cache[query]
            if coords is None:
                failed += 1
                continue
            event.lat, event.lng = coords
            geocoded += 1

    return {
        "pending": len(pending),
        "geocoded": geocoded,
        "failed": failed,
        "copied": copied,
    }
