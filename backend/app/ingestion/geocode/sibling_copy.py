"""Copy venue_address + coords onto under-located events from same-venue siblings."""

import logging
import re
from collections import Counter
from datetime import datetime, timedelta

from rapidfuzz.fuzz import ratio as fuzz_ratio
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    GEOCODE_COORD_QUANT_DECIMALS,
    GEOCODE_DONOR_LOOKBACK_DAYS,
    GEOCODE_MAX_PER_RUN,
    NON_GEOCODABLE_VENUE_NAMES,
    VENUE_NAME_PARENS_RE,
    VENUE_SIBLING_RATIO_THRESHOLD,
)
from app.models.models import Event

log = logging.getLogger(__name__)

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


_DonorRow = tuple[str | None, float | None, float | None]


async def _load_donor_rows_by_canon(
    db: AsyncSession, now: datetime
) -> dict[str, list[_DonorRow]]:
    """Recently-geocoded donors, grouped by canonical venue name.

    Grouping bounds the fuzzy loop to distinct cores; non-physical donors
    (NON_GEOCODABLE_VENUE_NAMES) are dropped so virtual events can't donate
    junk coords. Legitimately out-of-area donors are excluded in SQL — the
    self-heal pass never fixes them, so their coord must not propagate onto a
    fuzzy-matched in-area sibling.

    Bounded to the last GEOCODE_DONOR_LOOKBACK_DAYS (events rows are never
    deleted, so an unbounded scan here grows with all-time ingestion volume;
    venue coordinates don't change, so this trades a little donor coverage
    for a bounded query, same rationale as _build_geocode_cache). `now` is
    threaded in from the caller (mirroring _build_geocode_cache) rather than
    read locally, for testability and a single consistent cutoff per run.
    """
    cutoff = now - timedelta(days=GEOCODE_DONOR_LOOKBACK_DAYS)
    donor_rows = (
        await db.execute(
            select(Event.venue_name, Event.venue_address, Event.lat, Event.lng)
            .where(
                Event.venue_name.is_not(None),
                Event.venue_address.is_not(None),
                Event.lat.is_not(None),
                Event.lng.is_not(None),
                Event.is_out_of_area.is_(False),
                Event.starts_at >= cutoff,
            )
            .distinct()
        )
    ).all()
    donor_addrs_by_canon: dict[str, list[_DonorRow]] = {}
    for name, address, lat, lng in donor_rows:
        if name is None:
            continue
        canon = canonical_venue_name(name)
        if not canon or canon in NON_GEOCODABLE_VENUE_NAMES:
            continue
        donor_addrs_by_canon.setdefault(canon, []).append((address, lat, lng))
    return donor_addrs_by_canon


def _bucket_donor_canons_by_length(
    donor_addrs_by_canon: dict[str, list[_DonorRow]],
) -> dict[int, list[str]]:
    """Group donor canonical names by exact character length, for `_matched_donor_rows`'s
    length-band block."""
    buckets: dict[int, list[str]] = {}
    for canon in donor_addrs_by_canon:
        buckets.setdefault(len(canon), []).append(canon)
    return buckets


def _max_length_delta(length: int) -> int:
    """Widest |len(a) - len(b)| that could still clear VENUE_SIBLING_RATIO_THRESHOLD.

    rapidfuzz's ratio is `(1 - dist / (len(a) + len(b))) * 100`, and the edit
    distance is always >= |len(a) - len(b)| (you need at least that many
    insertions/deletions just to equalize length). Solving
    `|len(a)-len(b)| <= (1 - threshold/100) * (len(a) + len(b))` for the worst
    case (len(b) = length + delta) gives this bound. It is a safe **superset**
    filter — a donor outside the band provably cannot clear the threshold, so
    skipping it changes zero matches; +1 covers integer-division rounding.
    """
    return (length * 2 * (100 - VENUE_SIBLING_RATIO_THRESHOLD)) // VENUE_SIBLING_RATIO_THRESHOLD + 1


def _matched_donor_rows(
    target_canon: str,
    donor_addrs_by_canon: dict[str, list[_DonorRow]],
    donor_canons_by_length: dict[int, list[str]],
) -> list[_DonorRow]:
    """All donor rows whose canonical name fuzzy-matches the target's.

    Only donors within `_max_length_delta` of the target's length are even
    compared (see that function for why this never drops a true match) —
    bounds the number of fuzz_ratio calls to a length-neighborhood of the
    donor catalogue instead of its full size. score_cutoff additionally lets
    rapidfuzz prove "below cutoff" from a cheap length-bound check and skip
    the full edit-distance DP for the surviving-but-still-dissimilar pairs.
    """
    matched: list[_DonorRow] = []
    delta = _max_length_delta(len(target_canon))
    for length in range(len(target_canon) - delta, len(target_canon) + delta + 1):
        for donor_canon in donor_canons_by_length.get(length, ()):
            if (
                fuzz_ratio(
                    target_canon,
                    donor_canon,
                    score_cutoff=VENUE_SIBLING_RATIO_THRESHOLD,
                )
                >= VENUE_SIBLING_RATIO_THRESHOLD
            ):
                matched.extend(donor_addrs_by_canon[donor_canon])
    return matched


def _distinct_coords(matched: list[_DonorRow]) -> set[tuple[float, float]]:
    """Rounded distinct coords for the ambiguity count — one physical venue can
    be stored as two sub-meter-apart doubles, which must not read as two
    locations."""
    return {
        (
            round(lat, GEOCODE_COORD_QUANT_DECIMALS),
            round(lng, GEOCODE_COORD_QUANT_DECIMALS),
        )
        for _addr, lat, lng in matched
        if lat is not None and lng is not None
    }


def _fill_from_donors(event: Event, matched_rows: list[_DonorRow]) -> bool:
    """Fill whichever location field the target is missing; True when written.

    When the target has no coords, its address (if any) never geocoded →
    unreliable → overwrite with the house-numbered sibling address; when it
    already has coords (set at ingest) keep them, only backfill the address.
    """
    if event.lat is None or event.lng is None:
        event.lat, event.lng = next(
            (la, ln)
            for _addr, la, ln in matched_rows
            if la is not None and ln is not None
        )
        event.venue_address = _representative_address(matched_rows)
        return True
    if event.venue_address is None:
        event.venue_address = _representative_address(matched_rows)
        return True
    return False


async def copy_venue_from_siblings(db: AsyncSession, now: datetime) -> int:
    """Copy venue_address + coords onto under-located events from a sibling venue.

    Two queries (no-N+1): targets (venue_name set, lat or address NULL) and
    donors (see _load_donor_rows_by_canon). Matching is on the *canonical*
    venue core (canonical_venue_name) via symmetric fuzz.ratio — so "Sõltumatu
    Tantsu Lava" matches a "Sõltumatu Tantsu Lava (STL)" donor — memoized per
    distinct target name. The ambiguity guard keys on distinct *coordinates*:
    one physical venue legitimately carries several address spellings at one
    coord; only a genuine multi-location name (>1 distinct coord) is skipped.
    venue_name itself is never altered here (extract_address_from_venue_name
    runs earlier and may rewrite it). Returns events updated; caller commits.
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

    donor_addrs_by_canon = await _load_donor_rows_by_canon(db, now)
    donor_canons_by_length = _bucket_donor_canons_by_length(donor_addrs_by_canon)

    copied = 0
    warned_ambiguous: set[str] = set()
    # Memoized per distinct target canon — many targets share one venue_name,
    # so the fuzzy scan (and the coord set derived from it) runs once per name.
    matched_by_canon: dict[str, list[_DonorRow]] = {}
    coords_by_canon: dict[str, set[tuple[float, float]]] = {}
    for event in targets:
        name = event.venue_name
        if name is None:
            continue
        target_canon = canonical_venue_name(name)
        if not target_canon or target_canon in NON_GEOCODABLE_VENUE_NAMES:
            continue

        if target_canon not in matched_by_canon:
            matched_by_canon[target_canon] = _matched_donor_rows(
                target_canon, donor_addrs_by_canon, donor_canons_by_length
            )
            coords_by_canon[target_canon] = _distinct_coords(
                matched_by_canon[target_canon]
            )

        matched_rows = matched_by_canon[target_canon]
        distinct_coords = coords_by_canon[target_canon]
        if not matched_rows or not distinct_coords:
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

        if _fill_from_donors(event, matched_rows):
            copied += 1

    if copied:
        log.info("copied venue data from siblings to %d events", copied)
    return copied
