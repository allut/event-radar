"""DB-level dedup pass helpers for Event Radar.

The window, loaders and bulk writes shared by ``run_dedup_pass`` (rule-only)
and ``llm_tiebreaker.run_dedup_pass_llm`` (rule + LLM). The pure merge rules
and clustering live in ``app.dedup.rules``.
"""

import logging
from collections.abc import Mapping
from datetime import datetime, timedelta

from sqlalchemy import Integer, cast, column, func, or_, select, update, values
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, load_only, selectinload

from app.claims.dormancy import (
    apply_claim_dormancy,
    load_claims_for_events,
    resolve_claim_dormancy,
)
from app.constants.core import SECONDS_PER_HOUR, SQL_IN_CHUNK_SIZE, TALLINN_TZ
from app.constants.dedup import (
    DEDUP_BULK_UPDATE_CHUNK_SIZE,
    DEDUP_CANDIDATE_PAIR_MAX,
    DEDUP_CANDIDATE_PAIR_WARN_THRESHOLD,
    DEDUP_LOOKAHEAD_DAYS,
    DEDUP_LOOKBACK_DAYS,
    TIME_WINDOW_HOURS,
)
from app.constants.events import EVENT_STATUS_CANCELLED
from app.dedup.rules import cluster_events
from app.models.events import Event

log = logging.getLogger(__name__)


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
    check into Python. The self-join is bounded by the existing
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
    audit #5, item 1.1; same rationale as daily_feed.py's chunked shown-events load).
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
