"""The /admin promotions JSON API, end to end against a real Postgres."""

from typing import Any

import pytest
from sqlalchemy import select

from app.constants.admin import ADMIN_ACTION_PROMOTION_GRANT
from app.constants.promotions import PROMOTION_LIVE_CAP
from app.models.audit import AdminAction
from app.models.promotions import Promotion
from app.promotions.grant import GrantRequest, grant_promotion
from tests.promotions.conftest import NOW, Clock, at_tallinn, d


def body(start: int, end: int, **kw: Any) -> dict:
    out: dict[str, Any] = {
        "start_date": d(start).isoformat(),
        "end_date": d(end).isoformat(),
        "advertiser_legal_name": "Acme Events OÜ",
        "advertiser_registry_code": "12345678",
    }
    out.update(kw)
    return out


async def grant(db, make, start: int, end: int) -> None:
    ev = await make.event(submitted_by=await make.organizer())
    await grant_promotion(
        db,
        ev,
        GrantRequest(d(start), d(end), "X OÜ", "12345678"),
        NOW,
    )


@pytest.mark.asyncio
async def test_grant_creates_promotion_and_one_audit_row(client, db, make) -> None:
    org = await make.organizer(name="Acme Events")
    ev = await make.event(submitted_by=org)
    resp = await client.post(
        f"/admin/events/{ev.id}/promotions",
        json=body(10, 14, invoice_reference="ER-M-2090-7", billing_email="pay@example.com"),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "unpaid"
    assert data["state"] == "scheduled"
    assert data["organizer_id"] == org.id
    assert data["net_price_cents"] == 2500
    assert data["vat_cents"] == 600
    assert data["gross_price_cents"] == 3100
    assert data["vat_rate_percent"] == "24.00"
    rows = (await db.scalars(select(AdminAction).where(AdminAction.action == ADMIN_ACTION_PROMOTION_GRANT))).all()
    mine = [r for r in rows if r.target == str(data["id"])]
    assert len(mine) == 1
    assert mine[0].result["event_id"] == ev.id
    assert mine[0].result["net_price_cents"] == 2500


@pytest.mark.asyncio
async def test_refused_grant_writes_no_audit_row_and_lists_all_errors(client, db, make) -> None:
    ev = await make.event()  # no owner
    before = len((await db.scalars(select(AdminAction))).all())
    resp = await client.post(f"/admin/events/{ev.id}/promotions", json=body(10, 14))
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "no_owner"
    assert len((await db.scalars(select(AdminAction))).all()) == before
    assert (await db.scalars(select(Promotion).where(Promotion.event_id == ev.id))).all() == []


@pytest.mark.asyncio
async def test_window_error_is_422_with_every_error(client, make) -> None:
    ev = await make.event(submitted_by=await make.organizer())
    resp = await client.post(f"/admin/events/{ev.id}/promotions", json=body(1, 2))
    assert resp.status_code == 422
    codes = [e["code"] for e in resp.json()["detail"]["errors"]]
    assert codes == ["window_too_short", "starts_too_early"]


@pytest.mark.asyncio
async def test_cap_refusal_is_409(client, db, make) -> None:
    for _ in range(PROMOTION_LIVE_CAP):
        await grant(db, make, 10, 12)
    ev = await make.event(submitted_by=await make.organizer())
    resp = await client.post(f"/admin/events/{ev.id}/promotions", json=body(10, 12))
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "cap_exceeded"
    assert resp.json()["detail"]["errors"][0]["dates"] == ["2090-01-10", "2090-01-11", "2090-01-12"]


@pytest.mark.asyncio
async def test_unknown_event_is_404(client) -> None:
    assert (await client.post("/admin/events/999999999/promotions", json=body(10, 14))).status_code == 404


@pytest.mark.asyncio
async def test_validate_live_reports_errors_and_price(client, db, make) -> None:
    ev = await make.event(submitted_by=await make.organizer())
    for _ in range(PROMOTION_LIVE_CAP):
        await grant(db, make, 20, 22)
    ok = (await client.get(f"/admin/events/{ev.id}/promotions/validate", params={"start_date": "2090-01-10", "end_date": "2090-01-12"})).json()
    assert ok["valid"] is True
    assert ok["days"] == 3
    assert ok["price"] == {"net_cents": 1500, "vat_cents": 360, "gross_cents": 1860}
    bad = (await client.get(f"/admin/events/{ev.id}/promotions/validate", params={"start_date": "2090-01-21", "end_date": "2090-01-23"})).json()
    assert bad["valid"] is False
    assert [e["code"] for e in bad["errors"]] == ["cap_exceeded"]
    comp = (await client.get(f"/admin/events/{ev.id}/promotions/validate", params={"start_date": "2090-01-10", "end_date": "2090-01-12", "is_complimentary": "true"})).json()
    assert comp["price"]["net_cents"] == 0


@pytest.mark.asyncio
async def test_cap_strip_counts_reserved_and_live_with_frozen_midnight(client, db, make) -> None:
    ev = await make.event(submitted_by=await make.organizer())
    comp = await grant_promotion(
        db, ev, GrantRequest(d(2), d(4), "X OÜ", "12345678", is_complimentary=True, complimentary_note="pilot"), NOW
    )
    await grant(db, make, 3, 5)  # unpaid
    assert comp.status == "paid"

    Clock.now = at_tallinn(2090, 1, 1, 23, 59, 59)
    strip = (await client.get("/admin/promotions/cap-strip")).json()
    assert strip["today"] == "2090-01-01"
    assert strip["cap"] == 5
    assert len(strip["days"]) == 14
    by = {x["date"]: x for x in strip["days"]}
    assert by["2090-01-01"]["reserved"] == 0
    assert by["2090-01-02"] == {"date": "2090-01-02", "reserved": 1, "paid": 1, "unpaid": 0, "live": 0, "cap": 5, "free": 4}
    assert by["2090-01-03"]["reserved"] == 2 and by["2090-01-03"]["live"] == 0

    Clock.now = at_tallinn(2090, 1, 3, 0, 0, 0)
    strip = (await client.get("/admin/promotions/cap-strip")).json()
    by = {x["date"]: x for x in strip["days"]}
    assert strip["days"][0]["date"] == "2090-01-03"
    assert by["2090-01-03"]["reserved"] == 2
    assert by["2090-01-03"]["live"] == 1  # only the paid one is live
    assert by["2090-01-05"]["reserved"] == 1


@pytest.mark.asyncio
async def test_list_computes_state_and_filters(client, db, make) -> None:
    org = await make.organizer()
    ev = await make.event(submitted_by=org)
    for s, e in ((2, 4), (6, 8), (10, 12)):
        await grant_promotion(db, ev, GrantRequest(d(s), d(e), "X OÜ", "12345678"), NOW)
    Clock.now = at_tallinn(2090, 1, 7, 12)

    def mine(resp) -> list[dict]:
        return [p for p in resp.json()["promotions"] if p["event_id"] == ev.id]

    allp = mine(await client.get("/admin/promotions", params={"limit": 500}))
    assert {p["start_date"]: p["state"] for p in allp} == {
        "2090-01-02": "finished",
        "2090-01-06": "live",
        "2090-01-10": "scheduled",
    }
    live = await client.get("/admin/promotions", params={"state": "live", "limit": 500})
    assert [p["start_date"] for p in mine(live)] == ["2090-01-06"]
    assert live.json()["total"] >= 1
    assert (await client.get("/admin/promotions", params={"state": "bogus"})).status_code == 422


@pytest.mark.asyncio
async def test_context_for_owned_and_unowned_events(client, make) -> None:
    org = await make.organizer(name="Acme Events")
    owned = await make.event(submitted_by=org)
    ctx = (await client.get(f"/admin/events/{owned.id}/promotion-context")).json()
    assert ctx["owner"]["organizer_id"] == org.id
    assert ctx["prefill"]["advertiser_legal_name"] == "Acme Events"
    assert ctx["earliest_start"] == "2090-01-02"
    assert ctx["event_last_day"] == "2090-02-28"
    assert ctx["rules"] == {"min_days": 3, "max_days": 14, "cap": 5, "cap_strip_days": 14}
    assert ctx["pricing"] == {"day_price_cents": 500, "vat_rate_percent": "24.00"}
    unowned = await make.event()
    assert (await client.get(f"/admin/events/{unowned.id}/promotion-context")).json()["owner"] is None
