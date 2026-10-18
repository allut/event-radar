"""Owning-Organizer resolution for Promotions.

An event's owner is the Organizer who submitted it, or the Organizer holding
an approved, non-dormant claim over it. Resolved in bulk with a fixed query
count (two), because the fill gate reuses it per candidate set.
"""

from collections.abc import Sequence

from sqlalchemy import false, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.claims import (
    CLAIM_KIND_PUBLISHER,
    CLAIM_KIND_SERIES,
    CLAIM_STATUS_APPROVED,
)
from app.constants.events import EVENT_STATUS_CANCELLED
from app.models.models import Claim, Event, EventSource


async def resolve_owner_ids(db: AsyncSession, events: Sequence[Event]) -> dict[int, int]:
    """Map event id to owning Organizer id; unowned events are absent.

    Submitters win over claimants. A Publisher claim covers every event with a
    listing from that Publisher. A Series claim covers events carrying its
    series key, limited (like the claim-editing surface) to ingested,
    dedup-canonical, not-cancelled events.
    """
    owners: dict[int, int] = {}
    unresolved: list[Event] = []
    for event in events:
        if event.submitted_by_organizer_id is not None:
            owners[event.id] = event.submitted_by_organizer_id
        else:
            unresolved.append(event)
    if not unresolved:
        return owners

    unresolved_ids = [e.id for e in unresolved]
    publisher_rows = (
        await db.execute(
            select(EventSource.event_id, EventSource.publisher_id).where(
                EventSource.event_id.in_(unresolved_ids),
                EventSource.publisher_id.is_not(None),
            )
        )
    ).all()
    publishers_by_event: dict[int, set[int]] = {}
    for event_id, publisher_id in publisher_rows:
        publishers_by_event.setdefault(event_id, set()).add(publisher_id)

    series_events: dict[str, list[int]] = {}
    for event in unresolved:
        if (
            event.series_key is not None
            and event.status != EVENT_STATUS_CANCELLED
            and (event.dedup_group_id is None or event.dedup_group_id == event.id)
        ):
            series_events.setdefault(event.series_key, []).append(event.id)

    publisher_ids = {p for ids in publishers_by_event.values() for p in ids}
    claims = (
        await db.execute(
            select(Claim.id, Claim.kind, Claim.organizer_id, Claim.publisher_id, Claim.event_series_key)
            .where(
                Claim.status == CLAIM_STATUS_APPROVED,
                Claim.dormant == false(),
                (Claim.publisher_id.in_(publisher_ids))
                | (Claim.event_series_key.in_(series_events.keys())),
            )
            .order_by(Claim.id)
        )
    ).all()

    # Oldest claim wins when more than one covers the same event.
    for claim in claims:
        covered: list[int] = []
        if claim.kind == CLAIM_KIND_PUBLISHER:
            covered = [
                event_id
                for event_id, pids in publishers_by_event.items()
                if claim.publisher_id in pids
            ]
        elif claim.kind == CLAIM_KIND_SERIES and claim.event_series_key is not None:
            covered = series_events.get(claim.event_series_key, [])
        for event_id in covered:
            owners.setdefault(event_id, claim.organizer_id)
    return owners
