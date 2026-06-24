"""Nominatim geocoding for events that have a venue_address but no lat/lng."""

import asyncio
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import cast

import httpx
from rapidfuzz.fuzz import ratio as fuzz_ratio
from sqlalchemy import or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    ESTONIAN_STREET_TYPE_WORDS,
    GEOCODE_COORD_QUANT_DECIMALS,
    GEOCODE_COUNTRY_SUFFIX,
    GEOCODE_COUNTY_RE,
    GEOCODE_FLOOR_RE,
    GEOCODE_INITIAL_RE,
    GEOCODE_MAX_PER_RUN,
    GEOCODE_REQUEST_DELAY_SECONDS,
    GEOCODE_RETRY_INTERVAL_DAYS,
    GEOCODE_SECONDARY_UNIT_RE,
    GEOCODE_UNIT_SUFFIX_RE,
    HTTP_TIMEOUT_SECONDS,
    LLM_DEDUP_HASH_QUERY_CHUNK_SIZE,
    LLM_TASK_VENUE_EXTRACT,
    LLM_VENUE_EXTRACT_PROMPT_TEMPLATE,
    NON_GEOCODABLE_VENUE_NAMES,
    NOMINATIM_BASE_URL,
    NOMINATIM_USER_AGENT,
    TALLINN_REGION_BBOX,
    TALLINN_TZ,
    VENUE_EXTRACT_MAX_FRESH_LLM_CALLS_PER_RUN,
    VENUE_NAME_DIRECTION_KEYWORDS,
    VENUE_NAME_PROMPT_MAX_CHARS,
    VENUE_NAME_SUSPECT_MAX_LEN,
    VENUE_NAME_PARENS_RE,
    VENUE_SIBLING_RATIO_THRESHOLD,
)
from app.ingestion.base import coords_in_tallinn, http_get
from app.llm.router import LLMError, content_hash, llm_available, llm_json
from app.models.models import Event, LlmCall

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
_DIRECTION_KEYWORD_RE = re.compile(
    r"\b(" + "|".join(re.escape(kw) for kw in sorted(VENUE_NAME_DIRECTION_KEYWORDS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


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

    A result outside ``TALLINN_REGION_BBOX`` is treated as no match (logged +
    discarded, not stored) — a bare district/place name can collide with an
    identically-named place elsewhere in Estonia (e.g. Tallinn's Kopli district
    vs. a Kopli village on Saaremaa), and the publish gate's own bbox backstop
    would reject the wrong coord anyway. Leaving the event coords-less instead
    lets it through the publish gate's coords-less branch.
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
        lat, lng = float(results[0]["lat"]), float(results[0]["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not coords_in_tallinn(lat, lng):
        log.warning(
            "geocode out-of-bbox match discarded: query=%r original=%r lat=%s lng=%s",
            address,
            original or address,
            lat,
            lng,
        )
        return None
    return lat, lng


def is_suspect_venue_name(name: str) -> bool:
    """Return True if name likely contains an address or is a direction phrase.

    Flags when: contains a digit, contains a comma, matches a direction keyword,
    or exceeds VENUE_NAME_SUSPECT_MAX_LEN. Clean names like "KUMU" or
    "Sõltumatu Tantsu Lava (STL)" return False.
    """
    if any(ch.isdigit() for ch in name):
        return True
    if "," in name:
        return True
    if _DIRECTION_KEYWORD_RE.search(name):
        return True
    if len(name) > VENUE_NAME_SUSPECT_MAX_LEN:
        return True
    return False


async def _prefetch_venue_extract_cache(
    db: AsyncSession, hashes: list[str]
) -> dict[str, dict]:
    """Bulk-fetch cached venue-extract decisions for the given content hashes.

    One query per chunk (bounded by LLM_DEDUP_HASH_QUERY_CHUNK_SIZE), newest row
    per hash wins (dict overwrite with ascending order). Returns a map of
    content_hash → response_json dict. A row whose response_json is falsy is omitted
    so callers can treat absence as a cache miss.
    """
    cached: dict[str, dict] = {}
    unique_hashes = list(dict.fromkeys(hashes))
    for i in range(0, len(unique_hashes), LLM_DEDUP_HASH_QUERY_CHUNK_SIZE):
        chunk = unique_hashes[i : i + LLM_DEDUP_HASH_QUERY_CHUNK_SIZE]
        rows = (
            await db.execute(
                select(LlmCall.content_hash, LlmCall.response_json)
                .where(
                    LlmCall.task == LLM_TASK_VENUE_EXTRACT,
                    LlmCall.content_hash.in_(chunk),
                    LlmCall.response_json.is_not(None),
                )
                .order_by(LlmCall.created_at)
            )
        ).all()
        for row_hash, response_json in rows:
            if response_json:
                cached[row_hash] = response_json
    return cached


async def extract_address_from_venue_name(db: AsyncSession) -> int:
    """Mine street addresses out of venue_name into venue_address.

    Runs before copy_venue_from_siblings and Nominatim so a freshly-set
    venue_address becomes a geocoding target within the same run, and a NULLed
    junk name is excluded from sibling-copy donors/targets.

    Only processes events where venue_name IS NOT NULL and venue_address IS NULL.
    A Python prefilter skips clean names (no digit, no comma, no direction keyword,
    short) so the LLM only sees suspect strings. Decisions are grouped by the
    venue_name string and cached in llm_calls so identical strings are never
    re-called across runs. A fresh-call budget caps network calls per run.

    Returns the number of events mutated; the caller commits.
    """
    if not llm_available():
        return 0

    candidates = (
        await db.scalars(
            select(Event)
            .where(Event.venue_name.is_not(None), Event.venue_address.is_(None))
            .limit(GEOCODE_MAX_PER_RUN)
        )
    ).all()
    if not candidates:
        return 0

    # Group by venue_name string; only suspect names need LLM.
    by_name: dict[str, list[Event]] = {}
    for event in candidates:
        name = event.venue_name
        if name is None:
            continue
        if not is_suspect_venue_name(name):
            continue
        by_name.setdefault(name, []).append(event)

    if not by_name:
        return 0

    # Build prompts and hashes for bulk prefetch.
    prompts: dict[str, str] = {
        name: LLM_VENUE_EXTRACT_PROMPT_TEMPLATE.format(
            venue=name[:VENUE_NAME_PROMPT_MAX_CHARS]
        )
        for name in by_name
    }
    hashes: dict[str, str] = {name: content_hash(prompt) for name, prompt in prompts.items()}

    cached_decisions = await _prefetch_venue_extract_cache(
        db, list(hashes.values())
    )
    # Invert: hash → name for cache lookup
    fresh_calls = 0
    mutated = 0
    mutated_names = 0

    for name, events in by_name.items():
        prompt_hash = hashes[name]
        result: dict | None = cached_decisions.get(prompt_hash)

        if result is None:
            if fresh_calls >= VENUE_EXTRACT_MAX_FRESH_LLM_CALLS_PER_RUN:
                log.debug("venue-extract: fresh-call budget reached, deferring %r", name)
                continue
            try:
                result, _ = await llm_json(LLM_TASK_VENUE_EXTRACT, prompts[name], db)
                fresh_calls += 1
            except LLMError as exc:
                log.warning("venue-extract: LLM failed for %r: %s", name, exc)
                continue

        # Validate and apply.
        if not isinstance(result, dict):
            log.warning("venue-extract: malformed response for %r — skipping", name)
            continue

        raw_address = result.get("venue_address")
        raw_name = result.get("venue_name")

        new_address: str | None = (raw_address.strip() or None) if isinstance(raw_address, str) else None
        new_name: str | None = (raw_name.strip()[:255] or None) if isinstance(raw_name, str) else None

        # Only rewrite venue_name when an address was actually mined. Shortening or
        # NULLing the name with no address payoff buys nothing and can break canonical
        # sibling matching (it stranded event 482: "Katharienthal Kohviku" no longer
        # matched its full-named EN sibling). No address → leave the event untouched.
        if new_address is None:
            continue

        for event in events:
            event.venue_address = new_address
            event.venue_name = new_name
            mutated += 1
        mutated_names += 1

    if mutated:
        log.info("venue-extract: mutated %d event(s) across %d distinct name(s)", mutated, mutated_names)
    return mutated


async def copy_venue_from_siblings(db: AsyncSession) -> int:
    """Copy venue_address + coords onto under-located events from a sibling venue.

    Two queries (honors the no-N+1 batch rule): one for targets (venue_name set,
    and *either* lat NULL *or* venue_address NULL), one for all geocoded donors
    (distinct venue_name →
    address/coords where both are present). Matching is on the *canonical* venue
    core (parens + glued-on address tails stripped, see canonical_venue_name) via
    symmetric ``fuzz.ratio >= VENUE_SIBLING_RATIO_THRESHOLD``, so "Sõltumatu Tantsu
    Lava" matches a "Sõltumatu Tantsu Lava (STL)" donor (canonicalization makes the
    cores equal). A symmetric ratio is used rather than token_set_ratio so a short
    comma-split core can't score 100 against an unrelated longer donor. The matched
    donor set is memoized per distinct target_canon (an exact-equal donor bucket
    always clears the threshold via fuzz_ratio == 100, so it can't be shortcut without
    also dropping any other, non-identical bucket that happens to clear the threshold
    too) — this still collapses the scan from one-per-target to one-per-distinct-name,
    since many targets typically share the same venue_name. The ambiguity guard keys on
    distinct *coordinates*, not the full ``(address, lat, lng)`` tuple — one physical
    venue legitimately carries several address spellings at one coord, and only a
    genuine multi-location name (>1 distinct coord) is skipped + logged. Non-physical
    venue names (NON_GEOCODABLE_VENUE_NAMES) are skipped on both sides. venue_name
    itself is never altered by this function; the earlier extract_address_from_venue_name
    pass (run first in geocode_pending) may NULL or rewrite venue_name before this runs.
    Returns the number of events updated; the caller commits.
    """
    targets = (
        await db.scalars(
            select(Event)
            .where(
                Event.venue_name.is_not(None),
                or_(Event.lat.is_(None), Event.venue_address.is_(None)),
            )
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
                # A legitimately out-of-area donor (is_out_of_area True) is never
                # self-healed (that pass only targets in-area mis-geocodes), so it
                # must be excluded here directly — otherwise its coord can still
                # propagate onto a fuzzy-matched in-area sibling target.
                Event.is_out_of_area.is_(False),
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
    matched_rows_by_target_canon: dict[
        str, list[tuple[str | None, float | None, float | None]]
    ] = {}
    for event in targets:
        name = event.venue_name
        if name is None:
            continue
        target_canon = canonical_venue_name(name)
        if not target_canon or target_canon in NON_GEOCODABLE_VENUE_NAMES:
            continue

        if target_canon not in matched_rows_by_target_canon:
            matched: list[tuple[str | None, float | None, float | None]] = []
            for donor_canon, rows in donor_addrs_by_canon.items():
                if fuzz_ratio(target_canon, donor_canon) >= VENUE_SIBLING_RATIO_THRESHOLD:
                    matched.extend(rows)
            matched_rows_by_target_canon[target_canon] = matched

        matched_rows = matched_rows_by_target_canon[target_canon]
        if not matched_rows:
            continue

        # The donor query filters lat/lng non-null, so the None guard is
        # defense-in-depth. Coords are *rounded* for the distinct-count only:
        # one physical venue can be stored as two sub-meter-apart doubles (e.g.
        # 59.43793509999999 vs 59.4379351), which must not read as two locations.
        distinct_coords = {
            (round(lat, GEOCODE_COORD_QUANT_DECIMALS), round(lng, GEOCODE_COORD_QUANT_DECIMALS))
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

        # Fill whichever field the target is missing. When it has no coords the
        # address it carries (if any) never geocoded → unreliable → overwrite with
        # the house-numbered sibling address; when it already has coords (set at
        # ingest) keep them and only backfill a missing address.
        if event.lat is None or event.lng is None:
            event.lat, event.lng = next(
                (la, ln)
                for _addr, la, ln in matched_rows
                if la is not None and ln is not None
            )
            event.venue_address = _representative_address(matched_rows)
            copied += 1
        elif event.venue_address is None:
            event.venue_address = _representative_address(matched_rows)
            copied += 1

    if copied:
        log.info("copied venue data from siblings to %d events", copied)
    return copied


async def _self_heal_out_of_bbox_coords(db: AsyncSession) -> int:
    """NULL lat/lng (and reset the cooldown) for events mis-geocoded outside Tallinn.

    Targets only rows where ``is_out_of_area`` is False — the event genuinely
    belongs in the target city, so a stored coord outside ``TALLINN_REGION_BBOX``
    is a wrong match (e.g. a same-named place elsewhere in Estonia), not a
    legitimately out-of-area event (those have ``is_out_of_area`` True and never
    publish anyway, so are left untouched). One bulk UPDATE, no N+1. NULLing
    re-enters the row into the pending query below within the same run, where
    ``geocode_address``'s bbox gate now prevents re-storing the same wrong coord.
    """
    stmt = (
        update(Event)
        .where(
            Event.is_out_of_area.is_(False),
            Event.lat.is_not(None),
            Event.lng.is_not(None),
            or_(
                ~Event.lat.between(*TALLINN_REGION_BBOX[0:2]),
                ~Event.lng.between(*TALLINN_REGION_BBOX[2:4]),
            ),
        )
        .values(lat=None, lng=None, geocode_attempted_at=None)
    )
    result = await db.execute(stmt)
    healed = cast(CursorResult, result).rowcount
    if healed:
        log.info("self-healed %d event(s) with out-of-bbox coords", healed)
    return healed


async def geocode_pending(db: AsyncSession) -> dict:
    """Backfill lat/lng for events with a venue_address but no coordinates.

    The Nominatim pass itself is two queries regardless of row count: one for
    pending events (capped at GEOCODE_MAX_PER_RUN), one to seed a
    normalized-query→coords cache from **all** geocoded events (not just
    pending-address matches) — avoids re-hitting
    Nominatim for venues we already know, including spelling/unit variants of an
    address that some other event already resolved. The cache is keyed by the
    *normalized* query so format variants of one venue (e.g. "60a/9" vs "60a / 9")
    share a single Nominatim call.
    Remaining distinct addresses are geocoded serially with a delay between calls
    per Nominatim's usage policy (max 1 req/s).

    Before any of that, self-heals events whose stored coord is outside the
    Tallinn bbox despite being in-area (see _self_heal_out_of_bbox_coords) — done
    first so a bad donor coord can't propagate to copy_venue_from_siblings or the
    Nominatim cache below within the same run.

    First copies venue data between same-name siblings (copy_venue_from_siblings),
    so copied coords count toward the run; any copied row still missing coords
    falls through to the Nominatim pass below. The sibling copy makes no Nominatim
    calls and sets lat, so copied rows are excluded from the pending query — the
    Nominatim-call ceiling stays GEOCODE_MAX_PER_RUN even though total DB writes
    across both passes (copy + geocode) can reach 2x that on disjoint event sets.

    The pending query also excludes addresses that failed within the last
    GEOCODE_RETRY_INTERVAL_DAYS (geocode_attempted_at), so a permanently
    un-resolvable address isn't re-sent to Nominatim every run.
    """
    healed = await _self_heal_out_of_bbox_coords(db)
    extracted = await extract_address_from_venue_name(db)
    copied = await copy_venue_from_siblings(db)

    now = datetime.now(TALLINN_TZ)
    due_before = now - timedelta(days=GEOCODE_RETRY_INTERVAL_DAYS)
    pending = (
        await db.scalars(
            select(Event)
            .where(
                Event.venue_address.is_not(None),
                Event.lat.is_(None),
                or_(
                    Event.geocode_attempted_at.is_(None),
                    Event.geocode_attempted_at < due_before,
                ),
            )
            .order_by(Event.geocode_attempted_at.asc().nulls_first())
            .limit(GEOCODE_MAX_PER_RUN)
        )
    ).all()
    if not pending:
        return {
            "pending": 0,
            "geocoded": 0,
            "failed": 0,
            "copied": copied,
            "extracted": extracted,
            "healed": healed,
        }

    donor_rows = (
        await db.execute(
            select(Event.venue_address, Event.lat, Event.lng)
            .where(Event.venue_address.is_not(None), Event.lat.is_not(None))
            .distinct()
        )
    ).all()
    # Group geocoded coords by normalized query so spelling/unit variants of one
    # venue share coords; pick the most-common coord per key (lex tie-break) when a
    # key spans several near-identical Nominatim results. Donors outside the
    # Tallinn bbox are dropped so an already-bad stored coord can't seed the cache
    # for a sibling address (belt-and-suspenders alongside the self-heal above).
    coords_by_query: dict[str, Counter[tuple[float, float]]] = defaultdict(Counter)
    for address, lat, lng in donor_rows:
        if not coords_in_tallinn(lat, lng):
            continue
        coords_by_query[normalize_address_for_geocoding(address)][(lat, lng)] += 1
    cache: dict[str, tuple[float, float] | None] = {
        query: min(counter.most_common(), key=lambda kv: (-kv[1], kv[0]))[0]
        for query, counter in coords_by_query.items()
    }

    geocoded = 0
    failed = 0
    # Queries whose Nominatim call this run hit a transient HTTP error — these
    # must NOT start the cooldown (mirrors refetch.py not bumping its throttle
    # field on a fetch failure), unlike a definitive no-match/bbox-reject.
    transient_failure_queries: set[str] = set()
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
                    transient_failure_queries.add(query)
                await asyncio.sleep(GEOCODE_REQUEST_DELAY_SECONDS)

            coords = cache[query]
            if coords is None:
                failed += 1
                if query not in transient_failure_queries:
                    event.geocode_attempted_at = now
                continue
            event.lat, event.lng = coords
            event.geocode_attempted_at = now
            geocoded += 1

    return {
        "pending": len(pending),
        "geocoded": geocoded,
        "failed": failed,
        "copied": copied,
        "extracted": extracted,
        "healed": healed,
    }
