"""Copy venue_address + coords onto under-located events from same-venue siblings."""

import logging
import re
from collections import Counter

from rapidfuzz.fuzz import ratio as fuzz_ratio
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    GEOCODE_COORD_QUANT_DECIMALS,
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
    distinct_coords_by_target_canon: dict[str, set[tuple[float, float]]] = {}
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
                # score_cutoff lets rapidfuzz's C implementation prove "below cutoff"
                # from a cheap length-bound check and skip the full edit-distance DP
                # for clearly-dissimilar pairs — it never changes whether the *true*
                # ratio is >= VENUE_SIBLING_RATIO_THRESHOLD (a below-cutoff pair comes
                # back as 0.0 instead of its real, still-below-threshold score, which
                # compares identically against the threshold below). This does NOT
                # skip the scan on an exact match: a different, non-identical donor
                # bucket can independently clear the threshold too (see docstring
                # above), so every bucket is still checked — only the per-comparison
                # cost drops for the many pairs that are nowhere close to matching.
                if (
                    fuzz_ratio(
                        target_canon,
                        donor_canon,
                        score_cutoff=VENUE_SIBLING_RATIO_THRESHOLD,
                    )
                    >= VENUE_SIBLING_RATIO_THRESHOLD
                ):
                    matched.extend(rows)
            matched_rows_by_target_canon[target_canon] = matched
            # distinct_coords (and the ambiguity-vs-representative outcome derived from
            # it below) is a pure function of matched_rows, which is itself memoized
            # per target_canon — memoize this derived value too so events sharing a
            # venue_name don't recompute the same set comprehension repeatedly.
            # Coords are *rounded* for the distinct-count only: one physical venue can
            # be stored as two sub-meter-apart doubles (e.g. 59.43793509999999 vs
            # 59.4379351), which must not read as two locations.
            distinct_coords_by_target_canon[target_canon] = {
                (
                    round(lat, GEOCODE_COORD_QUANT_DECIMALS),
                    round(lng, GEOCODE_COORD_QUANT_DECIMALS),
                )
                for _addr, lat, lng in matched
                if lat is not None and lng is not None
            }

        matched_rows = matched_rows_by_target_canon[target_canon]
        if not matched_rows:
            continue

        distinct_coords = distinct_coords_by_target_canon[target_canon]
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
