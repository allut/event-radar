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
from collections.abc import Iterable
from datetime import date, datetime, timedelta

from rapidfuzz.fuzz import token_set_ratio
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, load_only

from app.constants import (
    DEDUP_LOOKAHEAD_DAYS,
    DEDUP_LOOKBACK_DAYS,
    DEDUP_UNFILTERED_FALLBACK_MAX_EVENTS,
    EVENT_STATUS_CANCELLED,
    EVENT_STATUS_CLASSIFIED,
    EVENT_STATUS_PUBLISHED,
    SECONDS_PER_HOUR,
    TALLINN_TZ,
    TIME_WINDOW_HOURS,
    TITLE_RATIO_THRESHOLD,
    TITLE_RATIO_VENUE_BYPASS_THRESHOLD,
    VENUE_RATIO_THRESHOLD,
)
from app.models.models import Event
from app.routers.utils import normalized_title

log = logging.getLogger(__name__)


def _venue_compatible(a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return True
    return token_set_ratio(a.lower(), b.lower()) >= VENUE_RATIO_THRESHOLD


def is_candidate_pair(
    a: Event,
    b: Event,
    *,
    bypass_venue_on_near_exact_title: bool = False,
    bypass_title_on_exact_time_and_venue: bool = False,
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
    """
    if (
        abs((a.starts_at - b.starts_at).total_seconds())
        > TIME_WINDOW_HOURS * SECONDS_PER_HOUR
    ):
        return False
    if (
        bypass_title_on_exact_time_and_venue
        and a.starts_at == b.starts_at
        and a.venue_name is not None
        and b.venue_name is not None
        and _venue_compatible(a.venue_name, b.venue_name)
    ):
        return True
    title_ratio = token_set_ratio(a.title_orig.lower(), b.title_orig.lower())
    if title_ratio < TITLE_RATIO_THRESHOLD:
        return False
    if (
        bypass_venue_on_near_exact_title
        and title_ratio >= TITLE_RATIO_VENUE_BYPASS_THRESHOLD
    ):
        return True
    return _venue_compatible(a.venue_name, b.venue_name)


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


def _event_quality_rank(event: Event) -> tuple[bool, bool, bool, int]:
    """Sortable data-completeness rank for picking a cluster representative.

    Higher tuple → better. Mirrors the ingestion-authority signals the pipeline
    already treats as "better details": price, address, coordinates, and
    description length. Title/venue presence is omitted — every clustered member
    already passed the fuzzy title match, so it is a fixed cost across the group.

    Raw (un-stripped) length is used for the description tie-break rather than
    a full HTML-to-text parse per member per pass — only the relative ordering
    matters here, not the exact stripped-text length.
    """
    return (
        event.price_min is not None,
        event.venue_address is not None,
        event.lat is not None and event.lng is not None,
        len(event.description_orig or ""),
    )


def build_cluster_assignments(
    parent: dict[int, int], ids: list[int], events_by_id: dict[int, Event]
) -> dict[int, int]:
    """Resolve union-find roots → {event_id: group_id} for groups with ≥2 members.

    The group_id is the id of the representative chosen per cluster by, in order:
    publish-status pin (``_representative_status_rank``, so an already
    classified/published member is never demoted), then data completeness
    (``_event_quality_rank``), then ``-eid`` (so equal-rank clusters keep the
    historical ``min(event_id)`` root). The representative is itself a member, so
    it maps to its own id — leaving exactly one canonical event per group
    (``dedup_group_id == id``), as the classifier / publish / feed paths assume.
    """
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
                    _event_quality_rank(events_by_id[eid]),
                    -eid,
                ),
            )
            for eid in members:
                assignments[eid] = representative_id
    return assignments


def cluster_events(
    events: list[Event],
    candidate_pair_ids: Iterable[tuple[int, int]] | None = None,
) -> dict[int, int]:
    """Return {event_id: dedup_group_id} for events that share a group.

    Events with no duplicates are NOT included in the result.

    If ``candidate_pair_ids`` is provided, only those (a_id, b_id) tuples are
    fuzzy-checked (typically pre-filtered by SQL on the time window). Without
    it, falls back to the original O(N²) Python enumeration.
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
                if is_candidate_pair(events[i], events[j]):
                    union(parent, events[i].id, events[j].id)
                    pair_count += 1
    else:
        for a_id, b_id in candidate_pair_ids:
            a = events_by_id.get(a_id)
            b = events_by_id.get(b_id)
            if a is None or b is None:
                continue
            if is_candidate_pair(a, b):
                union(parent, a.id, b.id)
                pair_count += 1

    if pair_count:
        log.debug("dedup: found %d candidate pair(s) among %d events", pair_count, n)

    return build_cluster_assignments(parent, ids, events_by_id)


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
    ``is_candidate_pair`` — per CLAUDE.md, never push that into SQL, and never
    push this time check into Python. The self-join is bounded by the existing
    (starts_at, status) B-tree: the planner can range-scan ``b`` on a sargable
    BETWEEN around ``a.starts_at``.
    """
    a = aliased(Event)
    b = aliased(Event)
    window = timedelta(seconds=TIME_WINDOW_HOURS * SECONDS_PER_HOUR)
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
            )
            .order_by(a.id, b.id)
        )
    ).all()
    return [(row[0], row[1]) for row in pair_rows]


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
    columns dedup actually reads/writes (fuzzy title/venue matching, the
    quality-rank tie-break, and dedup_group_id itself) rather than every Event
    column, including the large description_localized/important_info/
    price_hint text and JSONB fields this pass never touches.
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
                Event.venue_name,
                Event.venue_address,
                Event.lat,
                Event.lng,
                Event.price_min,
                Event.description_orig,
                Event.dedup_group_id,
            )
        )
    )
    return list(rows.all())


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

    assignments = cluster_events(events, candidate_pair_ids=candidate_pair_ids)

    updated = 0
    for event in events:
        new_gid = assignments.get(event.id)
        if event.dedup_group_id != new_gid:
            event.dedup_group_id = new_gid
            updated += 1

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
