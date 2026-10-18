"""Admin request queue (#615): list, grant, decline, and request expiry."""

from typing import Any

import pytest
from sqlalchemy import select

from app.constants.admin import (
    ADMIN_ACTION_PROMOTION_REQUEST_DECLINE,
    ADMIN_ACTION_PROMOTION_REQUEST_GRANT,
)
from app.constants.claims import CLAIM_STATUS_REVOKED
from app.constants.promotions import PROMOTION_LIVE_CAP
from app.models.models import AdminAction, Event, Promotion, PromotionRequest
from app.promotions.grant import GrantRequest, grant_promotion
from app.promotions.requests import RequestInput, create_request
from app.promotions.sweep import sweep_promotions
from tests.promotions.conftest import NOW, at_tallinn, d

LATER = at_tallinn(2090, 1, 5, 12)


async def make_request(db, make, org=None, start=10, end=14, ev=None, **ev_kw) -> PromotionRequest:
    org = org or await make.organizer()
    ev = ev or await make.event(submitted_by=org, **ev_kw)
    return await create_request(
        db,
        org.id,
        ev,
        RequestInput(d(start), d(end), "Acme OÜ", "10234957", None, "hello", True),
        NOW,
    )


def grant_body(start: int = 10, end: int = 14, **kw: Any) -> dict:
    out: dict[str, Any] = {
        "start_date": d(start).isoformat(),
        "end_date": d(end).isoformat(),
        "advertiser_legal_name": "Acme OÜ",
        "advertiser_registry_code": "10234957",
    }
    out.update(kw)
    return out


@pytest.fixture
def declined_mail(monkeypatch) -> list[tuple]:
    from app.routers import admin as admin_module

    sent: list[tuple] = []

    async def fake(to_email, event_title, start, end, reason, locale, http_client=None):
        sent.append((to_email, reason, locale))

    monkeypatch.setattr(admin_module, "send_promotion_request_declined_email", fake)
    return sent


@pytest.mark.asyncio
async def test_queue_lists_pending_with_count_reason_and_restriction(client, db, make) -> None:
    ok = await make_request(db, make, promotion_restriction="alcohol")
    owner_lost = await make_request(db, make)
    ev = await db.get(Event, owner_lost.event_id)
    ev.submitted_by_organizer_id = None
    await db.flush()
    done = await make_request(db, make)
    done.status = "withdrawn"
    await db.flush()
    resp = await client.get("/admin/promotion-requests")
    assert resp.status_code == 200
    data = resp.json()
    by_id = {r["id"]: r for r in data["requests"]}
    assert data["pending_count"] == data["total"] == 2
    assert done.id not in by_id
    assert by_id[ok.id]["not_eligible_reason"] is None
    assert by_id[ok.id]["promotion_restriction"] == "alcohol"
    assert by_id[ok.id]["advertiser_registry_code"] == "10234957"
    assert by_id[owner_lost.id]["not_eligible_reason"] == "organizer_not_owner"


@pytest.mark.asyncio
async def test_queue_flags_requests_whose_dates_are_sold_out(client, db, make) -> None:
    for _ in range(PROMOTION_LIVE_CAP):
        other = await make.event(submitted_by=await make.organizer())
        await grant_promotion(db, other, GrantRequest(d(10), d(14), "X OÜ", "12345678"), NOW)
    asked = await make_request(db, make, start=20, end=24)
    # Fill the days after the request was made.
    for _ in range(PROMOTION_LIVE_CAP):
        other = await make.event(submitted_by=await make.organizer())
        await grant_promotion(db, other, GrantRequest(d(20), d(24), "X OÜ", "12345678"), NOW)
    data = (await client.get("/admin/promotion-requests")).json()
    assert {r["id"]: r["not_eligible_reason"] for r in data["requests"]}[asked.id] == "cap_exceeded"


@pytest.mark.asyncio
async def test_grant_creates_promotion_marks_granted_and_audits(client, db, make) -> None:
    req = await make_request(db, make)
    resp = await client.post(
        f"/admin/promotion-requests/{req.id}/grant",
        json=grant_body(11, 15, billing_email="pay@example.com"),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "unpaid"
    assert data["start_date"] == d(11).isoformat()  # dates are editable
    assert data["request_id"] == req.id
    await db.refresh(req)
    assert req.status == "granted"
    assert req.resolved_by == "admin"
    promotion = await db.get(Promotion, data["id"])
    assert promotion is not None
    assert promotion.source_request_id == req.id
    rows = (
        await db.scalars(
            select(AdminAction).where(AdminAction.action == ADMIN_ACTION_PROMOTION_REQUEST_GRANT)
        )
    ).all()
    mine = [r for r in rows if r.target == str(req.id)]
    assert len(mine) == 1
    assert mine[0].result["promotion_id"] == promotion.id


@pytest.mark.asyncio
async def test_refused_grant_leaves_request_pending_and_writes_nothing(client, db, make) -> None:
    req = await make_request(db, make)
    await db.commit()
    resp = await client.post(
        f"/admin/promotion-requests/{req.id}/grant", json=grant_body(1, 2)  # too short, too early
    )
    assert resp.status_code == 422
    await db.refresh(req)
    assert req.status == "pending"
    assert (await db.scalars(select(Promotion).where(Promotion.event_id == req.event_id))).all() == []
    assert not [
        r
        for r in (await db.scalars(select(AdminAction).where(AdminAction.target == str(req.id)))).all()
    ]


@pytest.mark.asyncio
async def test_grant_refused_when_not_pending_or_unknown(client, db, make) -> None:
    req = await make_request(db, make)
    req.status = "declined"
    await db.commit()
    resp = await client.post(f"/admin/promotion-requests/{req.id}/grant", json=grant_body())
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "request_not_pending"
    assert (await client.post("/admin/promotion-requests/999999999/grant", json=grant_body())).status_code == 404


@pytest.mark.asyncio
async def test_decline_needs_reason_emails_organizer_and_audits(
    client, db, make, declined_mail
) -> None:
    org = await make.organizer()
    org.locale = "ru"
    req = await make_request(db, make, org=org)
    await db.commit()
    blank = await client.post(f"/admin/promotion-requests/{req.id}/decline", json={"reason": "  "})
    assert blank.status_code == 422
    assert blank.json()["detail"]["code"] == "reason_required"
    await db.refresh(req)
    assert req.status == "pending"
    assert declined_mail == []

    resp = await client.post(
        f"/admin/promotion-requests/{req.id}/decline", json={"reason": "Not a registered business"}
    )
    assert resp.status_code == 200, resp.text
    await db.refresh(req)
    assert req.status == "declined"
    assert req.decline_reason == "Not a registered business"
    assert declined_mail == [(org.email, "Not a registered business", "ru")]
    rows = (
        await db.scalars(
            select(AdminAction).where(AdminAction.action == ADMIN_ACTION_PROMOTION_REQUEST_DECLINE)
        )
    ).all()
    assert [r.result["reason"] for r in rows if r.target == str(req.id)] == [
        "Not a registered business"
    ]


@pytest.mark.asyncio
async def test_request_expires_when_event_cancelled(db, make) -> None:
    req = await make_request(db, make)
    ev = await db.get(Event, req.event_id)
    ev.status = "cancelled"
    await db.flush()
    result = await sweep_promotions(db, LATER)
    assert result["requests_expired"] == 1
    assert req.status == "expired"


@pytest.mark.asyncio
async def test_request_expires_when_claim_revoked(db, make) -> None:
    org = await make.organizer()
    ev = await make.event()
    claim = await make.publisher_claim(ev, org)
    req = await make_request(db, make, org=org, ev=ev)
    claim.status = CLAIM_STATUS_REVOKED
    await db.flush()
    await sweep_promotions(db, LATER)
    assert req.status == "expired"


@pytest.mark.asyncio
async def test_request_expires_at_its_start_date_not_before(db, make) -> None:
    req = await make_request(db, make, start=10, end=14)
    await sweep_promotions(db, at_tallinn(2090, 1, 9, 23, 59, 59))
    assert req.status == "pending"
    await sweep_promotions(db, at_tallinn(2090, 1, 10, 0, 0, 0))
    assert req.status == "expired"


@pytest.mark.asyncio
async def test_request_stays_pending_through_dormant_claim_and_shrunk_event(db, make) -> None:
    org = await make.organizer()
    ev = await make.event()
    claim = await make.publisher_claim(ev, org)
    req = await make_request(db, make, org=org, ev=ev, start=10, end=14)
    claim.dormant = True
    ev.ends_at = at_tallinn(2090, 1, 11, 22)  # dates no longer fit the event
    await db.flush()
    await sweep_promotions(db, LATER)
    assert req.status == "pending"


@pytest.mark.asyncio
async def test_expiry_sends_no_email(db, make, monkeypatch) -> None:
    from app.promotions import sweep as sweep_module

    calls: list[Any] = []

    async def fake(*a: Any, **k: Any) -> None:
        calls.append(a)

    monkeypatch.setattr(sweep_module, "send_promotion_ended_email", fake)
    await make_request(db, make, start=2, end=6)
    await sweep_promotions(db, LATER)
    assert calls == []
