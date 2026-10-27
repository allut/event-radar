"""Rule-based deduplication pre-filter for Event Radar.

Stage 1 of the two-stage dedup pipeline:
  rule-based → LLM tiebreaker on candidate pairs only

Merge criteria (ALL three must pass):
  1. Title fuzzy match: rapidfuzz token_set_ratio > TITLE_RATIO_THRESHOLD
  2. Time proximity: |Δstart| < TIME_WINDOW_HOURS hours
  3. Venue compatibility: same venue name (fuzzy) OR either venue is unknown

On match: cluster the connected component (union-find over all candidate pairs)
and assign every member the same dedup_group_id, equal to the id of the
best-quality representative in the cluster (see ``_event_quality_rank``; ties
fall back to ``min(event_id)``).
"""

import logging
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta

from rapidfuzz.fuzz import token_set_ratio
from sqlalchemy import Integer, cast, column, func, or_, select, update, values
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, load_only, selectinload

from app.constants.claims import CLAIM_STATUS_APPROVED
from app.constants.core import SQL_IN_CHUNK_SIZE, SECONDS_PER_HOUR, TALLINN_TZ
from app.constants.dedup import (
    DEDUP_BULK_UPDATE_CHUNK_SIZE,
    DEDUP_CANDIDATE_PAIR_MAX,
    DEDUP_CANDIDATE_PAIR_WARN_THRESHOLD,
    DEDUP_LOOKAHEAD_DAYS,
    DEDUP_LOOKBACK_DAYS,
    DEDUP_UNFILTERED_FALLBACK_MAX_EVENTS,
    TIME_WINDOW_HOURS,
    TITLE_RATIO_THRESHOLD,
    TITLE_RATIO_VENUE_BYPASS_THRESHOLD,
    VENUE_RATIO_THRESHOLD,
)
from app.constants.events import (
    EVENT_STATUS_CANCELLED,
    EVENT_STATUS_CLASSIFIED,
    EVENT_STATUS_PUBLISHED,
)
from app.events.venue import (
    resolve_venue_address,
    resolve_venue_coords,
    resolve_venue_name_from_row,
)
from app.models.models import Claim, Event, EventSource, Venue
from app.events.queries import (
    event_series_key,
    normalized_title,
    serialize_event_series_key,
)

log = logging.getLogger(__name__)


def _venue_compatible(a: str | None, b: str | None) -> bool:
    """Fuzzy venue match on already-lowercased names; unknown is compatible."""
    if a is None or b is None:
        return True
    return token_set_ratio(a, b, score_cutoff=VENUE_RATIO_THRESHOLD) >= VENUE_RATIO_THRESHOLD


# event id -> (lowercased title, lowercased venue name or None)
LoweredText = dict[int, tuple[str, str | None]]


def _lower_text(event: Event) -> tuple[str, str | None]:
    venue = event.venue_name
    return event.title_orig.lower(), venue.lower() if venue is not None else None


def lowered_text(events: Iterable[Event]) -> LoweredText:
    """Each event's lowercased title and venue, built once per pass so the
    pair loop doesn't lowercase both sides of every pair again."""
    return {e.id: _lower_text(e) for e in events}


def is_candidate_pair(
    a: Event,
    b: Event,
    *,
    bypass_venue_on_near_exact_title: bool = False,
    bypass_title_on_exact_time_and_venue: bool = False,
    lowered: LoweredText | None = None,
) -> bool:
    """Return True when a and b pass all three rule-based criteria.

    With ``bypass_venue_on_near_exact_title=True``, a near-exact title match
    (``token_set_ratio >= TITLE_RATIO_VENUE_BYPASS_THRESHOLD``) skips the venue
    check entirely — used on the LLM path so cross-source duplicates whose venue
    is spelled differently per source (including cross-language spellings) still
    reach the LLM tiebreaker, which makes the final same/different call.

    With ``bypass_title_on_exact_time_and_venue=True``, an *exact* ``starts_at``
    match plus a compatible venue skips the title check entirely — used on the
    LLM path so same-language-listing-different-language-title duplicates (e.g.
    a Fienta organizer publishing one et/ru/en listing per language, each with a
    completely different ``title_orig`` string, same showing) still reach the
    LLM tiebreaker. This is deliberately narrower than the venue bypass above
    (exact time equality, not the ``TIME_WINDOW_HOURS`` window) because unlike a
    near-exact title match, "same venue + same instant" alone is a weak signal —
    plenty of venues legitimately sell several distinct products/sessions at the
    same advertised time (see LLM_DEDUP_PROMPT_TEMPLATE, which instructs the LLM
    to reject those). It therefore requires *both* venue names to be present and
    fuzzy-compatible — unlike ``_venue_compatible``'s normal "unknown venue is
    compatible" rule, a missing venue on either side has zero corroborating
    signal (no title match either) and must not alone turn an arbitrary
    identical-round-time pair into an LLM candidate. The rule-only path keeps
    the default (strict) behavior for both bypasses — it has no way to
    adjudicate the ambiguity a bypass admits.

    ``lowered`` is the pass's ``lowered_text()`` map; omitted, both events
    are lowercased here.
    """
    if (
        abs((a.starts_at - b.starts_at).total_seconds())
        > TIME_WINDOW_HOURS * SECONDS_PER_HOUR
    ):
        return False
    a_title, a_venue = lowered[a.id] if lowered is not None else _lower_text(a)
    b_title, b_venue = lowered[b.id] if lowered is not None else _lower_text(b)
    if (
        bypass_title_on_exact_time_and_venue
        and a.starts_at == b.starts_at
        and a_venue is not None
        and b_venue is not None
        and _venue_compatible(a_venue, b_venue)
    ):
        return True
    # score_cutoff: rapidfuzz short-circuits to 0 below the threshold, which
    # is rejected right after anyway — same result, less work on the many
    # non-matching pairs.
    title_ratio = token_set_ratio(a_title, b_title, score_cutoff=TITLE_RATIO_THRESHOLD)
    if title_ratio < TITLE_RATIO_THRESHOLD:
        return False
    if (
        bypass_venue_on_near_exact_title
        and title_ratio >= TITLE_RATIO_VENUE_BYPASS_THRESHOLD
    ):
        return True
    return _venue_compatible(a_venue, b_venue)


# ---------------------------------------------------------------------------
# Union-Find for clustering candidate pairs into groups
# ---------------------------------------------------------------------------


def _find(parent: dict[int, int], x: int) -> int:
    while parent[x] != x:
        parent[x] = parent[parent[x]]  # path compression
        x = parent[x]
    return x


def union(parent: dict[int, int], a: int, b: int) -> None:
    ra, rb = _find(parent, a), _find(parent, b)
    if ra != rb:
        # Smaller ID becomes the root. The root only drives connectivity now —
        # the canonical dedup_group_id is re-chosen by quality in
        # build_cluster_assignments — but keeping min-id roots makes the
        # equal-quality tie-break land on the historical min(event_id).
        if ra < rb:
            parent[rb] = ra
        else:
            parent[ra] = rb


def same_group(parent: dict[int, int], a_id: int, b_id: int) -> bool:
    """True if a_id and b_id already share a union-find cluster.

    Public wrapper over the private ``_find`` so other modules (the LLM
    tiebreaker) can skip pairs already collapsed by
    ``apply_same_day_title_unions`` without importing ``_find`` cross-module.
    """
    return _find(parent, a_id) == _find(parent, b_id)


def apply_same_day_title_unions(parent: dict[int, int], events: list[Event]) -> None:
    """Union events sharing a normalized title on the same Europe/Tallinn calendar
    day (and a compatible venue), deterministically and with no LLM call.

    Collapses timed-entry / session ticket slots (e.g. a museum's six same-day
    slots, or a long exhibition's per-day rows) into one dedup group, independent
    of the 12h LLM-candidate time window. Bucketing is on the exact normalized
    title (``normalized_title``) plus the Tallinn calendar date; members within a
    bucket are only unioned when ``_venue_compatible`` holds (an unknown venue is
    treated as compatible), so two genuinely different events that happen to share
    a generic title on the same day at different venues are NOT merged.

    Intentional residual: multi-day series are NOT collapsed across days — the
    bucket key includes the date, so each day stays one canonical event (per the
    same-day-only policy chosen for this feature).

    Within one (title, date) bucket of k members, comparing every pair directly is
    O(k^2) token_set_ratio calls — a generic/collision-prone title or an all-day
    (00:00) timestamp can make one bucket large. ``_venue_compatible(a, b)`` depends
    only on the two venue_name *strings*, not on which specific members carry them, so
    this groups members by exact venue_name first (union-find is transitive: unioning
    one representative pair per *distinct* venue-name pair reproduces the same final
    connected components as unioning every member pair — see ``_union_by_venue_group``)
    — collapsing the fuzzy comparison from O(k^2) member-pairs to O(d^2) distinct-name
    pairs, d = distinct venue-name values in the bucket (d <= k; d == 1 in the common
    timed-entry-slot case, where every slot shares one venue_name).
    """
    buckets: dict[tuple[str, date], list[Event]] = {}
    for e in events:
        key = (
            normalized_title(e.title_orig),
            e.starts_at.astimezone(TALLINN_TZ).date(),
        )
        buckets.setdefault(key, []).append(e)
    for members in buckets.values():
        if len(members) < 2:
            continue
        _union_by_venue_group(parent, members)


def _union_by_venue_group(parent: dict[int, int], members: list[Event]) -> None:
    """Union a same-day-title bucket's members using ``_venue_compatible``, without
    comparing every member pair directly (see ``apply_same_day_title_unions``).

    1. Group members by exact ``venue_name`` (a dedicated ``None`` group holds every
       "unknown venue" member — trivially compatible with everything, same as
       ``_venue_compatible``'s own `a is None or b is None` rule) and union each
       group's members together linearly (exact-string members are always mutually
       compatible: ``token_set_ratio(x, x) == 100``).
    2. If a ``None`` group exists, union its representative with one representative of
       every named group — reproducing ``_venue_compatible``'s "unknown venue bridges
       to anything" rule, which old code applied pairwise (any member pair involving a
       None venue was unioned directly, transitively merging the whole bucket).
    3. For every remaining pair of distinct *named* groups, run ``_venue_compatible``
       once on the group keys (not once per member pair) and union one representative
       from each compatible pair.
    """
    groups: dict[str | None, list[Event]] = {}
    for m in members:
        groups.setdefault(m.venue_name, []).append(m)

    for group_members in groups.values():
        first_id = group_members[0].id
        for m in group_members[1:]:
            union(parent, first_id, m.id)

    representatives = {key: group_members[0] for key, group_members in groups.items()}
    none_rep = representatives.pop(None, None)
    if none_rep is not None:
        for rep in representatives.values():
            union(parent, none_rep.id, rep.id)

    named_keys = list(representatives.keys())
    for i in range(len(named_keys)):
        for j in range(i + 1, len(named_keys)):
            if _venue_compatible(named_keys[i], named_keys[j]):
                union(
                    parent,
                    representatives[named_keys[i]].id,
                    representatives[named_keys[j]].id,
                )


def _representative_status_rank(event: Event) -> int:
    """Pin the representative to a member that has already advanced past draft.

    Quality-driven re-selection (``_event_quality_rank``) must never flip the
    canonical event away from one already classified or published — the
    classifier only classifies *canonical drafts* and the publish gate is
    dedup-unaware, so a flip would orphan a stale published row alongside a
    newly-promoted sibling (two published events for one real event). Ordering:
    published (2) > classified (1) > draft/other (0). Among members at the same
    status, data quality (then ``min(event_id)``) decides — so a fresh all-draft
    cluster, the common case since dedup runs before classify/publish, still
    picks the best-data representative.
    """
    if event.status == EVENT_STATUS_PUBLISHED:
        return 2
    if event.status == EVENT_STATUS_CLASSIFIED:
        return 1
    return 0


def _event_quality_rank(
    event: Event, desc_len_by_id: dict[int, int] | None = None
) -> tuple[bool, bool, bool, int]:
    """Sortable data-completeness rank for picking a cluster representative.

    Higher tuple → better. Mirrors the ingestion-authority signals the pipeline
    already treats as "better details": price, address, coordinates, and
    description length. Title/venue presence is omitted — every clustered member
    already passed the fuzzy title match, so it is a fixed cost across the group.

    Raw (un-stripped) length is used for the description tie-break rather than
    a full HTML-to-text parse per member per pass — only the relative ordering
    matters here, not the exact stripped-text length.

    ``desc_len_by_id`` (from ``load_description_lengths``) is the production
    path — ``event.description_orig`` isn't loaded on events fetched via
    ``load_dedup_candidate_events`` (Big-O audit M3), and an async session
    would raise ``MissingGreenlet`` on a lazy-load attempt. Falling back to
    ``event.description_orig`` when no map is supplied keeps this working for
    callers (tests) that build plain in-memory Event objects directly.
    """
    if desc_len_by_id is not None:
        desc_len = desc_len_by_id.get(event.id, 0)
    else:
        desc_len = len(event.description_orig or "")
    return (
        event.price_min is not None,
        resolve_venue_address(event) is not None,
        None not in resolve_venue_coords(event),
        desc_len,
    )


def build_cluster_assignments(
    parent: dict[int, int],
    ids: list[int],
    events_by_id: dict[int, Event],
    desc_len_by_id: dict[int, int] | None = None,
    claimed_event_ids: frozenset[int] | None = None,
) -> dict[int, int]:
    """Resolve union-find roots → {event_id: group_id} for groups with ≥2 members.

    The group_id is the id of the representative chosen per cluster by, in order:
    publish-status pin (``_representative_status_rank``, so an already
    classified/published member is never demoted), then claimed-beats-unclaimed
    (``claimed_event_ids``, #418 — a claimed event outranks an unclaimed one at
    the same publish-status, but never overrides the status pin itself), then
    data completeness (``_event_quality_rank``), then ``-eid`` (so equal-rank
    clusters keep the historical ``min(event_id)`` root). The representative is
    itself a member, so it maps to its own id — leaving exactly one canonical
    event per group (``dedup_group_id == id``), as the classifier / publish /
    feed paths assume.
    """
    claimed_event_ids = claimed_event_ids or frozenset()
    roots: dict[int, list[int]] = {}
    for eid in ids:
        root = _find(parent, eid)
        roots.setdefault(root, []).append(eid)
    assignments: dict[int, int] = {}
    for members in roots.values():
        if len(members) > 1:
            representative_id = max(
                members,
                key=lambda eid: (
                    _representative_status_rank(events_by_id[eid]),
                    eid in claimed_event_ids,
                    _event_quality_rank(events_by_id[eid], desc_len_by_id),
                    -eid,
                ),
            )
            for eid in members:
                assignments[eid] = representative_id
    return assignments


def resolve_claim_dormancy(
    assignments: Mapping[int, int], claims_by_event_id: Mapping[int, Claim]
) -> tuple[set[int], set[int]]:
    """Claimed-vs-claimed collision resolution (#418).

    Within a cluster, the chosen representative's own claim (if any)
    reactivates; every other clustered member's claim, if claimed, goes
    dormant — its pins stop applying while dormant, but the row is never
    deleted or revoked (unlike ``status``, which still gates duplicate-claim
    creation regardless of dormancy).

    A claim can appear in only one of the two returned sets *per cluster*,
    but the same claim id can independently reactivate in one cluster while
    going dormant in another within the same pass (e.g. two distinct future
    occurrences of one claimed series, one colliding with a duplicate and one
    not) — callers apply dormant last so it wins on write, erring toward a
    claim's pins not applying rather than silently overwriting content.

    ``build_cluster_assignments`` only returns entries for clusters with ≥2
    members — a claimed event with no (or no longer any) colliding duplicate
    this pass is a singleton and never appears in ``assignments`` at all. Such
    an event is trivially its own canonical representative, so every claimed
    event absent from ``assignments`` also reactivates here — this is what
    clears a previously dormant claim once its collision resolves (the
    colliding duplicate gets cancelled, ages out of the window, etc.).
    """
    members_by_group: dict[int, list[int]] = {}
    for eid, gid in assignments.items():
        members_by_group.setdefault(gid, []).append(eid)

    dormant_claim_ids: set[int] = set()
    reactivate_claim_ids: set[int] = set()
    clustered_event_ids: set[int] = set()
    for gid, members in members_by_group.items():
        clustered_event_ids.update(members)
        rep_claim = claims_by_event_id.get(gid)
        if rep_claim is not None:
            reactivate_claim_ids.add(rep_claim.id)
        for eid in members:
            if eid == gid:
                continue
            claim = claims_by_event_id.get(eid)
            if claim is not None and (rep_claim is None or claim.id != rep_claim.id):
                dormant_claim_ids.add(claim.id)

    for eid, claim in claims_by_event_id.items():
        if eid not in clustered_event_ids:
            reactivate_claim_ids.add(claim.id)

    return dormant_claim_ids, reactivate_claim_ids


async def apply_claim_dormancy(
    db: AsyncSession, dormant_claim_ids: set[int], reactivate_claim_ids: set[int]
) -> None:
    """Persist ``resolve_claim_dormancy``'s verdict in two bulk UPDATEs
    (independent of cluster count). Dormant wins over reactivate for a claim
    id present in both sets — see ``resolve_claim_dormancy``."""
    reactivate_only = reactivate_claim_ids - dormant_claim_ids
    if reactivate_only:
        await db.execute(
            update(Claim).where(Claim.id.in_(reactivate_only)).values(dormant=False)
        )
    if dormant_claim_ids:
        await db.execute(
            update(Claim).where(Claim.id.in_(dormant_claim_ids)).values(dormant=True)
        )


async def load_claims_for_events(
    db: AsyncSession, events: list[Event]
) -> dict[int, Claim]:
    """Bulk-resolve each event's APPROVED claim, if any, for dedup's claimed
    tiebreak (#418) — matched via the same durable keys ``create_claim()``
    used to create it: a resolved ``EventSource.publisher_id`` (itself keyed
    on the durable Fienta ``organizer_id`` / KUMU-ECH ``source_id`` via
    ``Publisher``), or, absent a Publisher, a freshly re-computed Piletilevi
    ``event_series_key`` from *this row's own* ``title_orig`` and resolved
    venue name — never the event's primary key. This is what makes claims
    durable across re-ingestion: a brand-new occurrence row re-matches its
    claim by key exactly like the original row did, with no reference back
    to any specific prior Event id. Organizer retirement/revival and source
    disablement need no special-casing here — they change ``Publisher.status``
    /``Source.enabled``, neither of which this lookup joins against.

    Venue name for the series-key fallback is resolved the same way
    ``resolve_claim_target()`` resolved it at claim-creation time
    (``resolve_venue_name()``'s locale-default column, preferring a linked
    ``Venue`` over the bare ``Event.venue_name``) via a bulk outer join,
    rather than reading ``Event.venue_name`` off the passed-in rows directly
    — those come from ``load_dedup_candidate_events()``, which doesn't load
    ``venue_id``/the ``Venue`` relationship, and a mismatch here would mean a
    venue-linked claimed event never re-matches its own claim.

    One EventSource query + one Venue-name query + one Claim query,
    independent of ``len(events)`` (batch-job discipline).
    """
    if not events:
        return {}
    event_ids = [e.id for e in events]
    # Every IN list below is chunked at SQL_IN_CHUNK_SIZE: SQLAlchemy
    # expands IN to one bind param per value, past Postgres's ~32k-param cap
    # on a large window (Big-O audit M4; same rationale as
    # load_description_lengths).
    publisher_rows: list = []
    for i in range(0, len(event_ids), SQL_IN_CHUNK_SIZE):
        publisher_rows += (
            await db.execute(
                select(EventSource.event_id, EventSource.publisher_id).where(
                    EventSource.event_id.in_(event_ids[i : i + SQL_IN_CHUNK_SIZE]),
                    EventSource.publisher_id.is_not(None),
                )
            )
        ).all()
    publisher_ids_by_event: dict[int, set[int]] = {}
    for eid, pid in publisher_rows:
        publisher_ids_by_event.setdefault(eid, set()).add(pid)

    no_publisher_ids = [e.id for e in events if e.id not in publisher_ids_by_event]
    resolved_venue_name_by_event: dict[int, str | None] = {}
    venue_rows: list = []
    for i in range(0, len(no_publisher_ids), SQL_IN_CHUNK_SIZE):
        venue_rows += (
            await db.execute(
                select(Event.id, Event.venue_name, Venue.name, Venue.name_en)
                .outerjoin(Venue, Event.venue_id == Venue.id)
                .where(Event.id.in_(no_publisher_ids[i : i + SQL_IN_CHUNK_SIZE]))
            )
        ).all()
    if venue_rows:
        for eid, bare_venue_name, venue_name, venue_name_en in venue_rows:
            resolved_venue_name_by_event[eid] = resolve_venue_name_from_row(
                bare_venue_name, venue_name, venue_name_en
            )

    series_key_by_event: dict[int, str] = {
        e.id: serialize_event_series_key(
            event_series_key(e.title_orig, resolved_venue_name_by_event.get(e.id, e.venue_name))
        )
        for e in events
        if e.id not in publisher_ids_by_event
    }

    all_publisher_ids = {pid for pids in publisher_ids_by_event.values() for pid in pids}
    all_series_keys = set(series_key_by_event.values())
    if not all_publisher_ids and not all_series_keys:
        return {}

    publisher_id_list = sorted(all_publisher_ids)
    series_key_list = sorted(all_series_keys)
    claims: list[Claim] = []
    for i in range(0, len(publisher_id_list), SQL_IN_CHUNK_SIZE):
        claims += (
            await db.scalars(
                select(Claim).where(
                    Claim.status == CLAIM_STATUS_APPROVED,
                    Claim.publisher_id.in_(
                        publisher_id_list[i : i + SQL_IN_CHUNK_SIZE]
                    ),
                )
            )
        ).all()
    for i in range(0, len(series_key_list), SQL_IN_CHUNK_SIZE):
        claims += (
            await db.scalars(
                select(Claim).where(
                    Claim.status == CLAIM_STATUS_APPROVED,
                    Claim.event_series_key.in_(
                        series_key_list[i : i + SQL_IN_CHUNK_SIZE]
                    ),
                )
            )
        ).all()
    claim_by_publisher = {c.publisher_id: c for c in claims if c.publisher_id is not None}
    claim_by_series = {c.event_series_key: c for c in claims if c.event_series_key is not None}

    result: dict[int, Claim] = {}
    for event in events:
        pids = publisher_ids_by_event.get(event.id)
        if pids:
            for pid in pids:
                claim = claim_by_publisher.get(pid)
                if claim is not None:
                    result[event.id] = claim
                    break
            continue
        key = series_key_by_event.get(event.id)
        claim = claim_by_series.get(key) if key is not None else None
        if claim is not None:
            result[event.id] = claim
    return result


def cluster_events(
    events: list[Event],
    candidate_pair_ids: Iterable[tuple[int, int]] | None = None,
    desc_len_by_id: dict[int, int] | None = None,
    claimed_event_ids: frozenset[int] | None = None,
) -> dict[int, int]:
    """Return {event_id: dedup_group_id} for events that share a group.

    Events with no duplicates are NOT included in the result.

    If ``candidate_pair_ids`` is provided, only those (a_id, b_id) tuples are
    fuzzy-checked (typically pre-filtered by SQL on the time window). Without
    it, falls back to the original O(N²) Python enumeration.

    ``desc_len_by_id``/``claimed_event_ids`` are forwarded to
    ``build_cluster_assignments`` — see ``_event_quality_rank``/its own
    docstring for why the production caller supplies them.
    """
    n = len(events)
    if n < 2:
        return {}

    ids = [e.id for e in events]
    parent: dict[int, int] = {eid: eid for eid in ids}
    events_by_id: dict[int, Event] = {e.id: e for e in events}

    # Deterministic same-day session collapse — seeds the rule-only path so it
    # degrades with the same grouping behavior as the LLM path (which calls this
    # helper too). Independent of the candidate-pair time window.
    apply_same_day_title_unions(parent, events)

    pair_count = 0
    lowered = lowered_text(events)
    if candidate_pair_ids is None:
        # Unfiltered O(N²) path — both production callers pass candidate_pair_ids
        # (pre-filtered via candidate_pair_ids_in_window). This branch exists for
        # white-box tests; hard-capped so a future caller invoking it on a large
        # unfiltered event list fails loudly instead of silently re-introducing the
        # quadratic scan this module was built to avoid.
        if n > DEDUP_UNFILTERED_FALLBACK_MAX_EVENTS:
            raise ValueError(
                f"cluster_events: unfiltered fallback called with {n} events "
                f"(max {DEDUP_UNFILTERED_FALLBACK_MAX_EVENTS}) — pass "
                "candidate_pair_ids (e.g. from candidate_pair_ids_in_window) instead "
                "of running the O(N^2) fallback on a large event list"
            )
        log.warning(
            "cluster_events: running unfiltered O(N^2) fallback on %d events", n
        )
        for i in range(n):
            for j in range(i + 1, n):
                if is_candidate_pair(events[i], events[j], lowered=lowered):
                    union(parent, events[i].id, events[j].id)
                    pair_count += 1
    else:
        for a_id, b_id in candidate_pair_ids:
            a = events_by_id.get(a_id)
            b = events_by_id.get(b_id)
            if a is None or b is None:
                continue
            if is_candidate_pair(a, b, lowered=lowered):
                union(parent, a.id, b.id)
                pair_count += 1

    if pair_count:
        log.debug("dedup: found %d candidate pair(s) among %d events", pair_count, n)

    return build_cluster_assignments(
        parent, ids, events_by_id, desc_len_by_id, claimed_event_ids
    )


# ---------------------------------------------------------------------------
# DB-level pass
# ---------------------------------------------------------------------------


def dedup_window_cutoff() -> datetime:
    """Lower bound for the dedup window.

    Extends the lookback by TIME_WINDOW_HOURS so boundary pairs (events within
    the time window of the cutoff) are loaded together — neither is ever
    evaluated without its potential partner.
    """
    return (
        datetime.now(tz=TALLINN_TZ)
        - timedelta(days=DEDUP_LOOKBACK_DAYS)
        - timedelta(hours=TIME_WINDOW_HOURS)
    )


async def candidate_pair_ids_in_window(
    db: AsyncSession, cutoff: datetime
) -> list[tuple[int, int]]:
    """SQL pre-filter: non-cancelled event id pairs within TIME_WINDOW_HOURS.

    Stage-1 *time* pre-filter shared by ``run_dedup_pass`` (rule-only) and
    ``llm_tiebreaker.run_dedup_pass_llm`` (rule + LLM). Returned pairs always
    satisfy ``a_id < b_id`` and are ordered by ``(a_id, b_id)`` for determinism.

    The fuzzy title/venue check runs in Python on these pairs via
    ``is_candidate_pair`` — never push that into SQL, and never push this time
    check into Python (docs/pipeline.md "Pipeline Code Rules"). The self-join is bounded by the existing
    (starts_at, status) B-tree: the planner can range-scan ``b`` on a sargable
    BETWEEN around ``a.starts_at``.

    Also requires a loose title trigram overlap (``%``, backed by
    ``ix_events_title_orig_trgm``) OR an exact ``starts_at`` match. This is a
    superset prefilter, not a replacement for ``is_candidate_pair``'s fuzzy
    check: the default ``pg_trgm.similarity_threshold`` (0.3) is far looser
    than ``TITLE_RATIO_THRESHOLD`` (70), so it only prunes pairs
    ``is_candidate_pair`` could never accept on title grounds. The exact-time
    arm exists so it doesn't also prune out
    ``is_candidate_pair(bypass_title_on_exact_time_and_venue=True)`` pairs —
    same showing, different-language titles at an identical instant — which
    the LLM tiebreaker deliberately admits without any title match at all.
    """
    a = aliased(Event)
    b = aliased(Event)
    window = timedelta(seconds=TIME_WINDOW_HOURS * SECONDS_PER_HOUR)
    # Same upper bound as load_dedup_candidate_events: pairs past it would be
    # fetched here and then discarded for lack of loaded events.
    lookahead_cutoff = datetime.now(tz=TALLINN_TZ) + timedelta(
        days=DEDUP_LOOKAHEAD_DAYS
    )
    pair_rows = (
        await db.execute(
            select(a.id, b.id)
            .join(
                b,
                (a.id < b.id)
                & (b.starts_at >= a.starts_at - window)
                & (b.starts_at <= a.starts_at + window),
            )
            .where(
                a.status != EVENT_STATUS_CANCELLED,
                b.status != EVENT_STATUS_CANCELLED,
                a.starts_at >= cutoff,
                b.starts_at >= cutoff,
                a.starts_at <= lookahead_cutoff,
                b.starts_at <= lookahead_cutoff,
                or_(
                    a.title_orig.op("%")(b.title_orig),
                    a.starts_at == b.starts_at,
                ),
            )
            # Newest-first: when the cap truncates, the dropped tail is the
            # oldest pairs (already seen by earlier passes), never the
            # freshly ingested events (Big-O audit M3).
            .order_by(a.id.desc(), b.id)
            .limit(DEDUP_CANDIDATE_PAIR_MAX)
        )
    ).all()
    pairs = sorted((row[0], row[1]) for row in pair_rows)
    if len(pairs) > DEDUP_CANDIDATE_PAIR_WARN_THRESHOLD:
        log.warning(
            "candidate_pair_ids_in_window: %d candidate pairs (warn threshold %d)%s "
            "— same-window listing density is high, dedup pass will take longer",
            len(pairs),
            DEDUP_CANDIDATE_PAIR_WARN_THRESHOLD,
            " (TRUNCATED at cap — oldest pairs dropped; newest-first ordering "
            "keeps fresh events in every pass)"
            if len(pairs) >= DEDUP_CANDIDATE_PAIR_MAX
            else "",
        )
    return pairs


async def load_dedup_candidate_events(
    db: AsyncSession, cutoff: datetime
) -> list[Event]:
    """Non-cancelled events inside the dedup lookback/lookahead window, ordered
    by id.

    Shared by ``run_dedup_pass`` and ``llm_tiebreaker.run_dedup_pass_llm`` so
    both passes always cluster the same population.

    Upper-bounded at DEDUP_LOOKAHEAD_DAYS from now — events rows are never
    deleted, so without this an event scheduled arbitrarily far in the future
    would be loaded on every pass. ``load_only`` restricts the SELECT to the
    columns dedup actually reads/writes (fuzzy title/venue matching, and
    dedup_group_id itself) rather than every Event column, including the large
    description_orig/description_localized/important_info/price_hint text and
    JSONB fields this pass never touches. Description *length* (for the
    quality-rank tie-break) is fetched separately by ``load_description_lengths``
    — a `func.length()` projection, not the TEXT itself (Big-O audit M3).
    """
    lookahead_cutoff = datetime.now(tz=TALLINN_TZ) + timedelta(days=DEDUP_LOOKAHEAD_DAYS)
    rows = await db.scalars(
        select(Event)
        .where(Event.status != EVENT_STATUS_CANCELLED)
        .where(Event.starts_at >= cutoff)
        .where(Event.starts_at <= lookahead_cutoff)
        .order_by(Event.id)
        .options(
            load_only(
                Event.id,
                Event.starts_at,
                Event.status,
                Event.title_orig,
                Event.venue_id,
                Event.venue_name,
                Event.venue_address,
                Event.lat,
                Event.lng,
                Event.price_min,
                Event.dedup_group_id,
            ),
            # Venue-linked events leave venue_name/venue_address/lat/lng NULL;
            # the resolvers read the joined Venue, and a lazy load on an async
            # session would raise MissingGreenlet.
            selectinload(Event.venue),
        )
    )
    return list(rows.all())


async def load_description_lengths(
    db: AsyncSession, event_ids: list[int]
) -> dict[int, int]:
    """{event_id: len(description_orig or "")} for ``event_ids`` — a
    `func.length()` projection so only integers cross the wire, never the
    (kilobytes-per-row) description text itself. Feeds the
    ``_event_quality_rank`` tie-break without ``load_dedup_candidate_events``
    having to hydrate every in-window event's full description (Big-O audit M3).

    Chunked at SQL_IN_CHUNK_SIZE — the dedup window has no row-count
    LIMIT, and SQLAlchemy expands ``IN`` to one bind param per id, which would
    hit Postgres's per-statement parameter limit past ~32k events (Big-O
    audit #5, item 1.1; same rationale as score.py's chunked shown-events load).
    """
    if not event_ids:
        return {}
    lengths: dict[int, int] = {}
    for i in range(0, len(event_ids), SQL_IN_CHUNK_SIZE):
        chunk = event_ids[i : i + SQL_IN_CHUNK_SIZE]
        rows = await db.execute(
            select(Event.id, func.length(Event.description_orig)).where(
                Event.id.in_(chunk)
            )
        )
        lengths.update({eid: (length or 0) for eid, length in rows.all()})
    return lengths


async def clear_stale_dedup_groups(db: AsyncSession, cutoff: datetime) -> None:
    """NULL out dedup_group_id on events that have aged out of the window.

    Without this, an event excluded from the load query would keep a stale
    group id after its partner was recomputed. ``synchronize_session=False``
    is safe: aged-out rows (``starts_at < cutoff``) are never loaded by
    ``load_dedup_candidate_events``, so no identity-map objects are affected.
    Shared by both dedup passes.
    """
    await db.execute(
        update(Event)
        .where(Event.starts_at < cutoff)
        .where(Event.status != EVENT_STATUS_CANCELLED)
        .where(Event.dedup_group_id.is_not(None))
        .values(dedup_group_id=None),
        execution_options={"synchronize_session": False},
    )


async def bulk_assign_dedup_groups(
    db: AsyncSession, events: list[Event], assignments: Mapping[int, int | None]
) -> int:
    """Write ``assignments`` onto ``events`` with one bulk
    ``UPDATE ... FROM (VALUES (id, group_id), ...)`` per
    ``DEDUP_BULK_UPDATE_CHUNK_SIZE`` changed rows — the query count follows
    the number of changed rows, not the number of distinct groups (Big-O
    audit #5, item 2.8; chunked to stay under the driver's bind-parameter cap).

    Also updates each changed event's in-memory ``dedup_group_id`` directly —
    deliberately *not* going through the ORM's dirty-tracking (no later flush
    should re-issue a per-row UPDATE for a value the bulk UPDATE above already
    wrote), so this sets the attribute via ``__dict__`` rather than normal
    attribute assignment. Returns the number of events whose group id changed.
    """
    changed: list[tuple[Event, int | None]] = []
    for event in events:
        new_gid = assignments.get(event.id)
        if event.dedup_group_id != new_gid:
            changed.append((event, new_gid))

    for start in range(0, len(changed), DEDUP_BULK_UPDATE_CHUNK_SIZE):
        chunk = changed[start : start + DEDUP_BULK_UPDATE_CHUNK_SIZE]
        new_groups = values(
            column("id", Integer), column("group_id", Integer), name="new_groups"
        ).data([(event.id, new_gid) for event, new_gid in chunk])
        await db.execute(
            update(Event)
            .where(Event.id == new_groups.c.id)
            # cast: an all-NULL chunk would otherwise type the VALUES column as text.
            .values(dedup_group_id=cast(new_groups.c.group_id, Integer)),
            execution_options={"synchronize_session": False},
        )
        for event, new_gid in chunk:
            event.__dict__["dedup_group_id"] = new_gid

    return len(changed)


async def run_dedup_pass(db: AsyncSession) -> dict:
    """Find duplicate events and assign dedup_group_id.

    Loads all non-cancelled events, clusters them, and writes group IDs for
    any newly discovered or changed groups. Returns a summary dict.
    """
    cutoff = dedup_window_cutoff()
    events = await load_dedup_candidate_events(db, cutoff)

    if not events:
        return {"total": 0, "grouped": 0, "groups": 0, "updated": 0}

    candidate_pair_ids = await candidate_pair_ids_in_window(db, cutoff)
    desc_len_by_id = await load_description_lengths(db, [e.id for e in events])
    claims_by_event_id = await load_claims_for_events(db, events)

    assignments = cluster_events(
        events,
        candidate_pair_ids=candidate_pair_ids,
        desc_len_by_id=desc_len_by_id,
        claimed_event_ids=frozenset(claims_by_event_id),
    )

    dormant_ids, reactivate_ids = resolve_claim_dormancy(assignments, claims_by_event_id)
    await apply_claim_dormancy(db, dormant_ids, reactivate_ids)

    updated = await bulk_assign_dedup_groups(db, events, assignments)

    await clear_stale_dedup_groups(db, cutoff)

    group_count = len({gid for gid in assignments.values()})
    log.info(
        "dedup pass: %d events, %d grouped into %d group(s), %d updated",
        len(events),
        len(assignments),
        group_count,
        updated,
    )
    return {
        "total": len(events),
        "grouped": len(assignments),
        "groups": group_count,
        "updated": updated,
    }
