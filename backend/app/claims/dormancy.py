"""Claim dormancy for deduplicated events (#418).

When dedup clusters two claimed events, the representative's claim stays
active and every other member's claim goes dormant: its pins stop applying,
but the row is never deleted or revoked.
"""

from collections.abc import Mapping

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app._generated.shared_constants import CLAIM_STATUS_APPROVED
from app.constants.core import SQL_IN_CHUNK_SIZE
from app.events.queries import event_series_key, serialize_event_series_key
from app.events.venue import resolve_venue_name_from_row
from app.models.claims import Claim
from app.models.events import Event, EventSource
from app.models.organizers import Venue


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
