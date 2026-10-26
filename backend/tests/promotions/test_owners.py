"""Bulk owning-Organizer resolver."""

import pytest

from app.constants.claims import CLAIM_STATUS_PENDING
from app.promotions.owners import resolve_owner_ids
from tests.conftest import count_statements


@pytest.mark.asyncio
async def test_submitter_owns_the_event(db, make) -> None:
    org = await make.organizer()
    ev = await make.event(submitted_by=org)
    assert await resolve_owner_ids(db, [ev]) == {ev.id: org.id}


@pytest.mark.asyncio
async def test_unowned_event_is_absent(db, make) -> None:
    ev = await make.event()
    assert await resolve_owner_ids(db, [ev]) == {}


@pytest.mark.asyncio
async def test_publisher_claim_owns_events_of_that_publisher(db, make) -> None:
    org = await make.organizer()
    ev = await make.event()
    await make.publisher_claim(ev, org)
    assert await resolve_owner_ids(db, [ev]) == {ev.id: org.id}


@pytest.mark.asyncio
async def test_series_claim_owns_matching_series_key(db, make) -> None:
    org = await make.organizer()
    ev = await make.event()
    await make.series_claim(ev, org)
    assert await resolve_owner_ids(db, [ev]) == {ev.id: org.id}


@pytest.mark.asyncio
async def test_dormant_and_unapproved_claims_do_not_own(db, make) -> None:
    org = await make.organizer()
    dormant_ev = await make.event()
    await make.publisher_claim(dormant_ev, org, dormant=True)
    pending_ev = await make.event()
    await make.publisher_claim(pending_ev, org, status=CLAIM_STATUS_PENDING)
    dormant_series = await make.event()
    await make.series_claim(dormant_series, org, dormant=True)
    got = await resolve_owner_ids(db, [dormant_ev, pending_ev, dormant_series])
    assert got == {}


@pytest.mark.asyncio
async def test_cancelled_or_submitted_events_are_not_series_covered(db, make) -> None:
    org = await make.organizer()
    other = await make.organizer()
    cancelled = await make.event(status="cancelled")
    await make.series_claim(cancelled, org)
    submitted = await make.event(submitted_by=other)
    await make.series_claim(submitted, org)
    got = await resolve_owner_ids(db, [cancelled, submitted])
    assert got == {submitted.id: other.id}


@pytest.mark.asyncio
async def test_submitter_wins_over_a_claim(db, make) -> None:
    submitter = await make.organizer()
    claimant = await make.organizer()
    ev = await make.event(submitted_by=submitter)
    await make.publisher_claim(ev, claimant)
    assert await resolve_owner_ids(db, [ev]) == {ev.id: submitter.id}


@pytest.mark.asyncio
async def test_query_count_is_fixed_whatever_the_event_count(db, make) -> None:
    org = await make.organizer()

    async def count_queries(events) -> int:
        with count_statements(db) as stmts:
            await resolve_owner_ids(db, events)
        return len(stmts)

    one = [await make.event()]
    await make.publisher_claim(one[0], org)
    many = []
    for _ in range(12):
        e = await make.event()
        if len(many) % 2:
            await make.publisher_claim(e, org)
        else:
            await make.series_claim(e, org)
        many.append(e)
    assert await count_queries(many) == await count_queries(one)
