"""The Explore Sponsored slot (#603), end to end against a real Postgres.

Every event carries one unique `q` token and every request filters on it, so
rows other tests leave in a shared database can never reach the result set.
`now` is frozen at 2090-01-01 (the cap fixtures' era), so only the 2090 events
these tests create are live.
"""

from collections import Counter
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app._generated.shared_constants import VALID_VIBES
from app.auth.dependencies import get_optional_user
from app.config import settings
from app.constants.promotions import (
    PROMOTION_NOT_SHOWING_BOT,
    PROMOTION_NOT_SHOWING_EVENT_ENDED,
    PROMOTION_NOT_SHOWING_EVENT_NOT_CANONICAL,
    PROMOTION_NOT_SHOWING_EVENT_NOT_PUBLIC,
    PROMOTION_NOT_SHOWING_FILTERS_MISMATCH,
    PROMOTION_NOT_SHOWING_NOT_OWNED,
    PROMOTION_NOT_SHOWING_NOT_PAID,
    PROMOTION_NOT_SHOWING_OUTSIDE_WINDOW,
    PROMOTION_NOT_SHOWING_RESTRICTION_FLAGGED,
    PROMOTION_NOT_SHOWING_RESTRICTION_UNASSESSED,
    PROMOTION_NOT_SHOWING_SLOTS_DISABLED,
    PROMOTION_STATUS_PAID,
    PROMOTION_STATUS_UNPAID,
)
from app.db import get_db
from app.events.queries import facet_conditions
from app.constants.ranking import SIGNAL_BOOKMARK, SIGNAL_DISLIKE, SIGNAL_LIKE
from app.models.models import EventClassification, EventReport, Promotion, User, UserEventFeedback
from app.promotions.fill import evaluate_gate, gate_closed_reason
from app.rate_limit import limiter
from app.routers import browse
from tests.conftest import count_statements
from tests.conftest import EVENT_END, EVENT_START
from tests.promotions.conftest import NOW, at_tallinn, d

TOKEN = "zqx603"
PAGE = 24


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    limiter.reset()
    browse._score_cache.clear()
    monkeypatch.setattr(browse, "now_tallinn", lambda: NOW)
    monkeypatch.setattr(settings, "PROMOTIONS_SLOTS_ENABLED", True)
    yield
    browse._score_cache.clear()
    limiter.reset()


class Viewer:
    user: User | None = None


@pytest_asyncio.fixture
async def client(db) -> AsyncIterator[AsyncClient]:
    app = FastAPI()
    app.include_router(browse.router)

    async def _db() -> AsyncIterator[Any]:
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_optional_user] = lambda: Viewer.user
    Viewer.user = None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def classified(make, i: int = 0, *, org=None, **kw: Any):
    """A published event matching `q=TOKEN`, with the classification Explore joins."""
    kw.setdefault("title", f"{TOKEN} show")
    kw.setdefault("starts_at", EVENT_START + timedelta(hours=i))
    kw.setdefault("ends_at", EVENT_START + timedelta(hours=i + 2))
    ev = await make.event(submitted_by=org, **kw)
    make.db.add(EventClassification(event_id=ev.id, categories=["music"], vibes=[]))
    await make.db.flush()
    return ev


async def promote(db, event, org, **kw: Any) -> Promotion:
    fields: dict[str, Any] = dict(
        event_id=event.id,
        organizer_id=org.id,
        status=PROMOTION_STATUS_PAID,
        start_date=d(1),
        end_date=d(5),
        days=5,
        net_price_cents=0,
        vat_rate_percent=24,
        is_complimentary=True,
        complimentary_note="pilot",
        advertiser_legal_name=f"{org.name} OÜ",
        advertiser_registry_code="12345678",
    )
    fields.update(kw)
    p = Promotion(**fields)
    db.add(p)
    await db.flush()
    return p


async def clear(db, event, restriction: str | None = "none") -> None:
    event.promotion_restriction = restriction
    await db.flush()


async def get(client, *, offset: int = 0, slot: bool = True, ua: str | None = None, **params: Any) -> dict:
    query: dict[str, Any] = {
        "q": TOKEN,
        "for_you": "false",
        "sort": "date",
        "limit": PAGE,
        "offset": offset,
    }
    if slot:
        query["sponsored_slot"] = "true"
    query.update(params)
    headers = {"user-agent": ua} if ua else {}
    resp = await client.get("/explore", params=query, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def ids(page: dict) -> list[int]:
    return [e["id"] for e in page["events"]]


async def world(db, make, n: int = 30):
    """n organic events (the last one is the one that gets promoted, so it sits
    past page 1 in date order) plus its owner, cleared for promotion."""
    org = await make.organizer("Acme")
    events = [await classified(make, i, org=org) for i in range(n)]
    await clear(db, events[-1])
    return org, events


@pytest.mark.asyncio
async def test_page_one_carries_slot_at_tile_four_with_23_organic(client, db, make) -> None:
    org, events = await world(db, make)
    await promote(db, events[-1], org)
    page = await get(client)
    assert len(page["events"]) == PAGE - 1
    assert page["page1_has_slot"] is True
    slot = page["sponsored_slot"]
    assert slot["id"] == events[-1].id
    assert slot["tile"] == 4
    assert slot["advertiser"] == "Acme OÜ"
    assert slot["explanation"] == "filters"
    assert slot["title"]  # the standard card data rides along


@pytest.mark.asyncio
async def test_without_promotion_page_one_is_24_and_flag_false(client, db, make) -> None:
    await world(db, make)
    page = await get(client)
    assert len(page["events"]) == PAGE
    assert page["page1_has_slot"] is False
    assert "sponsored_slot" not in page


@pytest.mark.asyncio
async def test_later_pages_shift_one_and_total_is_unchanged(client, db, make) -> None:
    org, events = await world(db, make, n=60)
    base1 = await get(client, slot=False)
    base2 = await get(client, slot=False, offset=PAGE)
    base3 = await get(client, slot=False, offset=2 * PAGE)
    await promote(db, events[-1], org)
    p1 = await get(client)
    p2 = await get(client, offset=PAGE)
    p3 = await get(client, offset=2 * PAGE)
    # Concatenated organic results are identical, only the page seams moved.
    assert ids(p1) + ids(p2) + ids(p3) == ids(base1) + ids(base2) + ids(base3)
    assert ids(p2)[0] == ids(base1)[PAGE - 1]
    assert p1["total"] == p2["total"] == base1["total"] == 60
    assert p2["page1_has_slot"] is True and "sponsored_slot" not in p2
    assert p2["offset"] == PAGE and p2["limit"] == PAGE


@pytest.mark.asyncio
@pytest.mark.parametrize("params", [{}, {"for_you": "true", "sort": "relevance"}])
async def test_organic_order_is_identical_with_and_without_live_promotions(
    client, db, make, params
) -> None:
    org, events = await world(db, make)
    before = await get(client, slot=False, **params)
    full_before = [await get(client, slot=False, offset=o, **params) for o in (0, PAGE)]
    # Promote whatever ranks last, so it is never visible on page 1.
    promoted = next(e for e in events if e.id == full_before[-1]["events"][-1]["id"])
    await clear(db, promoted)
    await promote(db, promoted, org)
    after = await get(client, slot=False, **params)
    assert after == before  # byte-identical when the client doesn't opt in
    with_slot = await get(client, **params)
    assert ids(with_slot) == ids(before)[: PAGE - 1]  # same order, one row to the slot
    assert with_slot["sponsored_slot"]["id"] == promoted.id


@pytest.mark.asyncio
async def test_fewer_than_six_organic_means_no_slot(client, db, make) -> None:
    org, events = await world(db, make, n=6)
    await promote(db, events[0], org)  # visible on page 1 anyway
    thin = await classified(make, 99, org=org, title=f"{TOKEN} thin")
    await clear(db, thin)
    await promote(db, thin, org)
    page = await get(client, q=f"{TOKEN} thin")  # 1 organic result
    assert page["page1_has_slot"] is False
    assert len(page["events"]) == 1


@pytest.mark.asyncio
async def test_six_organic_on_page_one_is_the_floor(client, db, make) -> None:
    org, events = await world(db, make, n=20)
    await promote(db, events[-1], org)
    # limit 7: the slot takes one tile, leaving the 6 organic results the floor needs.
    page = await get(client, limit=7)
    assert page["page1_has_slot"] is True
    assert len(page["events"]) == 6
    # limit 6: only 5 organic would remain, so the slot collapses.
    page = await get(client, limit=6)
    assert page["page1_has_slot"] is False
    assert len(page["events"]) == 6


@pytest.mark.asyncio
async def test_flag_off_and_bots_get_no_slot(client, db, make, monkeypatch) -> None:
    org, events = await world(db, make)
    await promote(db, events[-1], org)
    assert (await get(client, ua="Mozilla/5.0 (compatible; Googlebot/2.1)"))["page1_has_slot"] is False
    assert len((await get(client, ua="curl/8"))["events"]) == PAGE - 1
    monkeypatch.setattr(settings, "PROMOTIONS_SLOTS_ENABLED", False)
    page = await get(client)
    assert page["page1_has_slot"] is False
    assert len(page["events"]) == PAGE


@pytest.mark.asyncio
async def test_no_opt_in_means_no_slot_key(client, db, make) -> None:
    org, events = await world(db, make)
    await promote(db, events[-1], org)
    page = await get(client, slot=False)
    assert "page1_has_slot" not in page and "sponsored_slot" not in page
    assert len(page["events"]) == PAGE


@pytest.mark.asyncio
async def test_every_facet_and_q_gate_the_slot(client, db, make) -> None:
    org, events = await world(db, make)
    await promote(db, events[-1], org)
    assert (await get(client))["page1_has_slot"] is True
    assert (await get(client, category="music"))["page1_has_slot"] is True
    assert (await get(client, category="theater"))["page1_has_slot"] is False
    assert (await get(client, vibe=sorted(VALID_VIBES)[0]))["page1_has_slot"] is False
    assert (await get(client, free="true"))["page1_has_slot"] is False
    assert (await get(client, date_to="2089-12-31"))["page1_has_slot"] is False
    assert (await get(client, q="nomatch"))["page1_has_slot"] is False
    assert (await get(client, date_from="2090-01-01", date_to="2090-12-31"))["page1_has_slot"] is True


@pytest.mark.asyncio
async def test_event_already_on_page_one_is_not_repeated_as_the_slot(client, db, make) -> None:
    org, events = await world(db, make)
    await clear(db, events[0])
    await promote(db, events[0], org)  # first in date order: organic tile #1
    page = await get(client)
    assert page["page1_has_slot"] is False
    assert len(page["events"]) == PAGE


@pytest.mark.asyncio
async def test_series_sibling_on_page_one_excludes_the_slot(client, db, make) -> None:
    org = await make.organizer("Acme")
    for i in range(29):
        await classified(make, i, org=org, title=f"{TOKEN} s{i}")
    same_series = await classified(make, 0, org=org, title=f"{TOKEN} series", venue_name="Hall A")
    promoted = await classified(make, 40, org=org, title=f"{TOKEN} series", venue_name="Hall A")
    promoted.title_orig = same_series.title_orig
    await db.flush()
    await db.refresh(promoted)  # series_key is trigger-maintained
    assert same_series.series_key == promoted.series_key
    await clear(db, promoted)
    await promote(db, promoted, org)
    assert (await get(client))["page1_has_slot"] is False


@pytest.mark.asyncio
async def test_signed_in_rotation_is_stable_for_a_user_day(client, db, make) -> None:
    org, events = await world(db, make, n=40)
    for e in events[-4:]:
        await clear(db, e)
        await promote(db, e, org)
    user = User(email="slot603@example.com")
    db.add(user)
    await db.flush()
    Viewer.user = user
    picks = {(await get(client))["sponsored_slot"]["id"] for _ in range(6)}
    assert len(picks) == 1


@pytest.mark.asyncio
async def test_anonymous_rotation_shares_equally(client, db, make) -> None:
    org, events = await world(db, make, n=40)
    for e in events[-2:]:
        await clear(db, e)
        await promote(db, e, org)
    seen = Counter([(await get(client))["sponsored_slot"]["id"] for _ in range(60)])
    assert set(seen) == {events[-1].id, events[-2].id}
    assert min(seen.values()) >= 10  # a fair split, with room for chance


@pytest.mark.asyncio
async def test_page_two_status_ignores_which_promotion_a_random_pick_would_choose(
    client, db, make
) -> None:
    org, events = await world(db, make, n=60)
    for e in events[-2:]:
        await clear(db, e)
        await promote(db, e, org)
    flags = {(await get(client, offset=PAGE))["page1_has_slot"] for _ in range(12)}
    assert flags == {True}


class TestGateReasons:
    """Each failing clause is named; evaluate_gate is the one place they live."""

    async def reason(self, db, make, *, now=NOW, facet=None, **setup: Any) -> str | None:
        org = await make.organizer("Acme")
        owner = setup.pop("owner", org)
        ev_kw = setup.pop("event", {})
        restriction = setup.pop("restriction", "none")
        ev = await classified(make, org=org, **ev_kw)
        await clear(db, ev, restriction)
        promo = await promote(db, ev, owner, **setup)
        [result] = await evaluate_gate(db, [promo], now, facet)
        return result.reason

    @pytest.mark.asyncio
    async def test_all_clear(self, db, make) -> None:
        assert await self.reason(db, make) is None

    @pytest.mark.asyncio
    async def test_unpaid(self, db, make) -> None:
        assert await self.reason(db, make, status=PROMOTION_STATUS_UNPAID) == PROMOTION_NOT_SHOWING_NOT_PAID

    @pytest.mark.asyncio
    async def test_outside_window(self, db, make) -> None:
        assert (
            await self.reason(db, make, start_date=d(2), end_date=d(5))
            == PROMOTION_NOT_SHOWING_OUTSIDE_WINDOW
        )

    @pytest.mark.asyncio
    async def test_not_public(self, db, make) -> None:
        assert (
            await self.reason(db, make, event={"status": "draft"})
            == PROMOTION_NOT_SHOWING_EVENT_NOT_PUBLIC
        )
        assert (
            await self.reason(db, make, event={"is_explicit": True})
            == PROMOTION_NOT_SHOWING_EVENT_NOT_PUBLIC
        )

    @pytest.mark.asyncio
    async def test_not_canonical(self, db, make) -> None:
        other = await classified(make)
        assert (
            await self.reason(db, make, event={"dedup_group_id": other.id})
            == PROMOTION_NOT_SHOWING_EVENT_NOT_CANONICAL
        )

    @pytest.mark.asyncio
    async def test_ended(self, db, make) -> None:
        late = at_tallinn(2090, 3, 1)
        assert await self.reason(db, make, now=late, start_date=d(1, 3), end_date=d(5, 3)) == PROMOTION_NOT_SHOWING_EVENT_ENDED

    @pytest.mark.asyncio
    async def test_not_owned(self, db, make) -> None:
        stranger = await make.organizer("Stranger")
        assert await self.reason(db, make, owner=stranger) == PROMOTION_NOT_SHOWING_NOT_OWNED

    @pytest.mark.asyncio
    async def test_dormant_claim_pauses(self, db, make) -> None:
        claimant = await make.organizer("Claimant")
        ev = await classified(make)
        await make.publisher_claim(ev, claimant, dormant=True)
        await clear(db, ev)
        promo = await promote(db, ev, claimant)
        [result] = await evaluate_gate(db, [promo], NOW)
        assert result.reason == PROMOTION_NOT_SHOWING_NOT_OWNED

    @pytest.mark.asyncio
    async def test_restriction(self, db, make) -> None:
        assert (
            await self.reason(db, make, restriction=None)
            == PROMOTION_NOT_SHOWING_RESTRICTION_UNASSESSED
        )
        assert (
            await self.reason(db, make, restriction="gambling")
            == PROMOTION_NOT_SHOWING_RESTRICTION_FLAGGED
        )

    @pytest.mark.asyncio
    async def test_facet_mismatch(self, db, make) -> None:
        conds = facet_conditions([], [], False, "nomatch", None, None, NOW)
        assert await self.reason(db, make, facet=conds) == PROMOTION_NOT_SHOWING_FILTERS_MISMATCH

    def test_slots_flag_and_bot(self, monkeypatch) -> None:
        assert gate_closed_reason("Mozilla/5.0") is None
        assert gate_closed_reason(None) is None
        assert gate_closed_reason("Googlebot/2.1") == PROMOTION_NOT_SHOWING_BOT
        monkeypatch.setattr(settings, "PROMOTIONS_SLOTS_ENABLED", False)
        assert gate_closed_reason("Mozilla/5.0") == PROMOTION_NOT_SHOWING_SLOTS_DISABLED


@pytest.mark.asyncio
async def test_gate_query_count_is_fixed(db, make) -> None:
    org = await make.organizer("Acme")
    made = []
    for i in range(6):
        ev = await classified(make, i, org=org)
        await clear(db, ev)
        made.append(await promote(db, ev, org))
    with count_statements(db) as statements:
        await evaluate_gate(db, made[:1], NOW, facet_conditions([], [], False, None, None, None, NOW))
        one = len(statements)
        statements.clear()
        await evaluate_gate(db, made, NOW, facet_conditions([], [], False, None, None, None, NOW))
        many = len(statements)
    assert one == many


# --- Viewer exclusions (#604) -------------------------------------------------


async def viewer(db, n: int = 0) -> User:
    user = User(email=f"slot604-{n}@example.com")
    db.add(user)
    await db.flush()
    Viewer.user = user
    return user


async def two_promoted(db, make):
    org, events = await world(db, make, n=40)
    a, b = events[-1], events[-2]
    await clear(db, b)
    await promote(db, a, org)
    await promote(db, b, org)
    return org, a, b


def mark(db, user, event, signal: str) -> None:
    db.add(UserEventFeedback(user_id=user.id, event_id=event.id, signal=signal, created_at=NOW))


async def duplicate_of(make, event):
    return await make.event(
        title=f"{TOKEN} dup", dedup_group_id=event.id, starts_at=EVENT_START, ends_at=EVENT_END
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["dislike", "dislike_duplicate", "report", "bookmark", "like"])
async def test_each_exclusion_falls_through_to_the_next_in_rotation(
    client, db, make, kind
) -> None:
    _, a, b = await two_promoted(db, make)
    user = await viewer(db)
    first = (await get(client))["sponsored_slot"]["id"]
    picked, other = (a, b) if first == a.id else (b, a)

    if kind == "dislike":
        mark(db, user, picked, SIGNAL_DISLIKE)
    elif kind == "dislike_duplicate":
        mark(db, user, await duplicate_of(make, picked), SIGNAL_DISLIKE)
    elif kind == "report":
        db.add(EventReport(user_id=user.id, event_id=picked.id, reason="spam"))
    else:
        mark(db, user, picked, kind)
    await db.flush()

    page = await get(client)
    assert page["sponsored_slot"]["id"] == other.id
    assert page["page1_has_slot"] is True


@pytest.mark.asyncio
async def test_slot_collapses_when_every_promotion_is_excluded(client, db, make) -> None:
    _, a, b = await two_promoted(db, make)
    user = await viewer(db)
    mark(db, user, a, SIGNAL_LIKE)
    mark(db, user, b, SIGNAL_BOOKMARK)
    await db.flush()
    page = await get(client)
    assert page["page1_has_slot"] is False
    assert "sponsored_slot" not in page
    assert len(page["events"]) == PAGE


@pytest.mark.asyncio
async def test_disliked_category_does_not_exclude_the_slot(client, db, make) -> None:
    await two_promoted(db, make)
    user = await viewer(db)
    sibling = await classified(make, 90)  # same "music" category as both Promotions
    mark(db, user, sibling, SIGNAL_DISLIKE)
    await db.flush()
    assert (await get(client))["page1_has_slot"] is True


@pytest.mark.asyncio
async def test_disliking_the_slot_card_hides_it_from_organic_results_too(
    client, db, make
) -> None:
    org, events = await world(db, make, n=40)
    await promote(db, events[-1], org)
    user = await viewer(db)
    params = {"for_you": "true", "sort": "relevance"}
    assert (await get(client, **params))["sponsored_slot"]["id"] == events[-1].id
    mark(db, user, events[-1], SIGNAL_DISLIKE)
    browse._score_cache.clear()  # the ranked-id cache has a short TTL
    await db.flush()
    page = await get(client, **params)
    assert page["page1_has_slot"] is False
    assert events[-1].id not in ids(page)
    assert events[-1].id not in ids(await get(client, offset=PAGE, **params))


@pytest.mark.asyncio
async def test_pick_is_an_equal_share_and_blind_to_feedback(client, db, make) -> None:
    await two_promoted(db, make)
    unrelated = await classified(make, 91)
    picks: dict[int, int] = {}
    for n in range(40):
        user = await viewer(db, n)
        picks[user.id] = (await get(client))["sponsored_slot"]["id"]
    assert min(Counter(picks.values()).values()) >= 8  # equal share across seeds
    # Liking an unrelated event moves nobody's pick.
    for uid in picks:
        db.add(UserEventFeedback(user_id=uid, event_id=unrelated.id, signal=SIGNAL_LIKE))
    await db.flush()
    for uid, expected in picks.items():
        Viewer.user = await db.get(User, uid)
        assert (await get(client))["sponsored_slot"]["id"] == expected


@pytest.mark.asyncio
async def test_explore_query_count_is_independent_of_live_promotions(client, db, make) -> None:
    org, events = await world(db, make, n=40)
    user = await viewer(db)
    for e in events[-2:]:
        await clear(db, e)
        await promote(db, e, org)
    await db.flush()
    with count_statements(db) as statements:
        await get(client)
        few = len(statements)
        for e in events[-8:-2]:
            await clear(db, e)
            await promote(db, e, org)
            mark(db, user, e, SIGNAL_BOOKMARK)
        await db.flush()
        statements.clear()
        await get(client)
        many = len(statements)
    assert few == many
