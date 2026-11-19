"""Organizer Promotion requests (#614) and per-day report (#616), end to end
through the HTTP API against a real Postgres. The clock is frozen at NOW."""

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth.dependencies import get_current_organizer
from app.config import settings
from app._generated.shared_constants import (
    CLAIM_STATUS_REVOKED,
    ORGANIZER_TERMS_VERSION,
)
from app.constants.promotions import PROMOTION_LIVE_CAP
from app.db import get_db
from app.models.promotions import Promotion, PromotionDailyStat, PromotionRequest
from app.promotions.grant import GrantRequest, grant_promotion
from app.promotions import requests as requests_module
from app.promotions.lifecycle import mark_paid
from app.routers import organizer_events as organizer_events_module
from app.routers import organizer_promotions as router_module
from tests.promotions.conftest import NOW, at_tallinn, d

VALID_CODE = "90000009"  # checksum-valid, synthetic 8-digit registry code
BAD_CHECKSUM = "10234958"


class Who:
    organizer: Any = None


@pytest.fixture
def notices(monkeypatch) -> list[int]:
    sent: list[int] = []

    async def fake(request, event, organizer) -> None:
        sent.append(request.id)

    monkeypatch.setattr(router_module, "send_request_notice", fake)
    return sent


@pytest_asyncio.fixture
async def oclient(db, make, monkeypatch, notices) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(settings, "PROMOTIONS_OFFER_ENABLED", True)
    monkeypatch.setattr(router_module, "now_tallinn", lambda: NOW)
    Who.organizer = await make.organizer(name="Acme Events")
    app = FastAPI()
    app.include_router(router_module.router)
    app.include_router(organizer_events_module.router)

    async def _db() -> AsyncIterator[Any]:
        yield db

    app.dependency_overrides[get_db] = _db
    async def _organizer() -> Any:
        # A refused request rolls the session back, which expires the row.
        await db.refresh(Who.organizer)
        return Who.organizer

    app.dependency_overrides[get_current_organizer] = _organizer
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def req_body(event_id: int, start: int = 10, end: int = 14, **kw: Any) -> dict:
    out: dict[str, Any] = {
        "event_id": event_id,
        "start_date": d(start).isoformat(),
        "end_date": d(end).isoformat(),
        "advertiser_legal_name": "Acme Events OÜ",
        "advertiser_registry_code": VALID_CODE,
        "business_attested": True,
        "terms_accepted": True,
    }
    out.update(kw)
    return out


async def own_event(make, **kw: Any):
    ev = await make.event(submitted_by=Who.organizer, **kw)
    # A refused request rolls back; commit so the fixture rows survive it.
    await make.db.commit()
    # Only the id: a refusal's rollback expires the ORM row.
    return SimpleNamespace(id=ev.id)


async def codes(resp) -> list[str]:
    return [e["code"] for e in resp.json()["detail"]["errors"]]


@pytest.mark.asyncio
async def test_endpoints_404_while_offer_flag_off(oclient, make, monkeypatch) -> None:
    ev = await own_event(make)
    monkeypatch.setattr(settings, "PROMOTIONS_OFFER_ENABLED", False)
    assert (await oclient.get("/organizer/promotions")).status_code == 404
    assert (await oclient.get(f"/organizer/promotions/context?event_id={ev.id}")).status_code == 404
    assert (await oclient.post("/organizer/promotions/requests", json=req_body(ev.id))).status_code == 404
    assert (await oclient.get("/organizer/promotions/1/report")).status_code == 404
    rows = (await oclient.get("/organizer/events")).json()["events"]
    assert all("promotion" not in r for r in rows)


@pytest.mark.asyncio
async def test_create_request_records_terms_and_notifies_admin(oclient, db, make, notices) -> None:
    ev = await own_event(make)
    resp = await oclient.post(
        "/organizer/promotions/requests", json=req_body(ev.id, note="  please  ")
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["status"] == "requested"
    assert data["days"] == 5
    assert data["price"] == {"net_cents": 2500, "vat_cents": 600, "gross_cents": 3100}
    assert data["billing_email"] == Who.organizer.email  # defaults to the account
    row = await db.get(PromotionRequest, data["id"])
    assert row is not None
    assert row.status == "pending"
    assert row.terms_version == ORGANIZER_TERMS_VERSION
    assert row.terms_accepted_at == NOW
    assert row.business_attested_at == NOW
    assert row.note == "please"
    assert notices == [row.id]


@pytest.mark.asyncio
async def test_request_refusals(oclient, make, notices) -> None:
    ev = await own_event(make)
    resp = await oclient.post(
        "/organizer/promotions/requests",
        json=req_body(
            ev.id,
            1,
            2,
            advertiser_registry_code=BAD_CHECKSUM,
            terms_accepted=False,
            business_attested=False,
        ),
    )
    assert resp.status_code == 422
    assert await codes(resp) == [
        "terms_not_accepted",
        "business_attestation_required",
        "registry_code_checksum",
        "window_too_short",
        "starts_too_early",
    ]
    resp = await oclient.post(
        "/organizer/promotions/requests", json=req_body(ev.id, advertiser_registry_code="123")
    )
    assert await codes(resp) == ["invalid_registry_code"]
    assert notices == []


@pytest.mark.asyncio
async def test_other_organizers_event_is_404(oclient, make) -> None:
    other = await make.organizer()
    ev = await make.event(submitted_by=other)
    assert (await oclient.post("/organizer/promotions/requests", json=req_body(ev.id))).status_code == 404
    assert (await oclient.get(f"/organizer/promotions/context?event_id={ev.id}")).status_code == 404


@pytest.mark.asyncio
async def test_dormant_claim_event_cannot_be_requested(oclient, make) -> None:
    ev = await make.event()
    await make.publisher_claim(ev, Who.organizer, dormant=True)
    assert (await oclient.post("/organizer/promotions/requests", json=req_body(ev.id))).status_code == 404


@pytest.mark.asyncio
async def test_one_pending_request_per_event(oclient, make) -> None:
    ev = await own_event(make)
    assert (await oclient.post("/organizer/promotions/requests", json=req_body(ev.id))).status_code == 201
    resp = await oclient.post("/organizer/promotions/requests", json=req_body(ev.id, 20, 24))
    assert resp.status_code == 409
    assert await codes(resp) == ["request_pending"]


@pytest.mark.asyncio
async def test_overlap_with_unpaid_promotion_is_refused(oclient, db, make) -> None:
    ev = await make.event(submitted_by=Who.organizer)
    await grant_promotion(db, ev, GrantRequest(d(12), d(16), "Acme OÜ", "12345678"), NOW)
    await db.commit()
    ev_id = ev.id
    resp = await oclient.post("/organizer/promotions/requests", json=req_body(ev_id, 10, 14))
    assert resp.status_code == 409
    assert "overlap" in await codes(resp)
    # Back-to-back is fine.
    assert (await oclient.post("/organizer/promotions/requests", json=req_body(ev_id, 17, 20))).status_code == 201


@pytest.mark.asyncio
async def test_sold_out_days_are_refused_and_listed_without_counts(oclient, db, make) -> None:
    for _ in range(PROMOTION_LIVE_CAP):
        other = await make.event(submitted_by=await make.organizer())
        await grant_promotion(db, other, GrantRequest(d(11), d(13), "X OÜ", "12345678"), NOW)
    ev = await own_event(make)
    validate = await oclient.get(
        f"/organizer/promotions/validate?event_id={ev.id}&start_date={d(10)}&end_date={d(14)}"
    )
    body = validate.json()
    assert body["valid"] is False
    cap_error = next(e for e in body["errors"] if e["code"] == "cap_exceeded")
    assert cap_error["dates"] == [d(11).isoformat(), d(12).isoformat(), d(13).isoformat()]
    assert "reserved" not in validate.text and "free" not in validate.text
    ctx = (await oclient.get(f"/organizer/promotions/context?event_id={ev.id}")).json()
    assert ctx["unavailable_dates"] == cap_error["dates"]
    resp = await oclient.post("/organizer/promotions/requests", json=req_body(ev.id, 10, 14))
    assert resp.status_code == 409
    assert "cap_exceeded" in await codes(resp)


@pytest.mark.asyncio
async def test_daily_request_cap_is_429(oclient, make, monkeypatch) -> None:
    # Lowered so the per-IP rate limit (10/minute) doesn't answer first.
    cap = 3
    monkeypatch.setattr(requests_module, "ORGANIZER_DAILY_PROMOTION_REQUEST_CAP", cap)
    for _ in range(cap):
        ev = await own_event(make)
        assert (await oclient.post("/organizer/promotions/requests", json=req_body(ev.id))).status_code == 201
    ev = await own_event(make)
    resp = await oclient.post("/organizer/promotions/requests", json=req_body(ev.id))
    assert resp.status_code == 429
    assert await codes(resp) == ["daily_request_limit"]


@pytest.mark.asyncio
async def test_withdraw_frees_the_event_and_is_own_only(oclient, make) -> None:
    ev = await own_event(make)
    rid = (await oclient.post("/organizer/promotions/requests", json=req_body(ev.id))).json()["id"]
    first = Who.organizer
    Who.organizer = await make.organizer()
    assert (await oclient.post(f"/organizer/promotions/requests/{rid}/withdraw")).status_code == 404
    Who.organizer = first
    assert (await oclient.post(f"/organizer/promotions/requests/{rid}/withdraw")).status_code == 200
    again = await oclient.post(f"/organizer/promotions/requests/{rid}/withdraw")
    assert again.status_code == 409
    assert (await oclient.post("/organizer/promotions/requests", json=req_body(ev.id))).status_code == 201
    # Withdrawn requests drop off the list; only the new one shows.
    items = (await oclient.get("/organizer/promotions")).json()["items"]
    assert [i["status"] for i in items] == ["requested"]


@pytest.mark.asyncio
async def test_list_statuses_newest_first_with_paused_reason(
    oclient, db, make, monkeypatch
) -> None:
    org = Who.organizer
    # Declined request.
    declined_ev = await own_event(make)
    rid = (await oclient.post("/organizer/promotions/requests", json=req_body(declined_ev.id))).json()["id"]
    req = await db.get(PromotionRequest, rid)
    req.status = "declined"
    req.decline_reason = "Not eligible"
    await db.flush()
    # Awaiting payment, scheduled (paid, future), live, paused, ended early, cancelled.
    async def promo(start: int, end: int, *, paid: bool = False, **ev_kw):
        ev = await make.event(submitted_by=Who.organizer, **ev_kw)
        p = await grant_promotion(db, ev, GrantRequest(d(start), d(end), "Acme OÜ", "12345678"), NOW)
        if paid:
            await mark_paid(db, p.id, NOW)
        return ev, p

    _, awaiting = await promo(20, 24)
    _, scheduled = await promo(20, 24, paid=True)
    live_ev = await own_event(make, promotion_restriction="none")
    live_p = Promotion(
        event_id=live_ev.id, organizer_id=org.id, status="paid", start_date=d(1), end_date=d(5),
        days=5, net_price_cents=2500, vat_rate_percent=24, advertiser_legal_name="Acme OÜ",
        advertiser_registry_code="12345678", paid_at=NOW,
    )
    paused_ev = await own_event(make, status="draft")
    paused_p = Promotion(
        event_id=paused_ev.id, organizer_id=org.id, status="paid", start_date=d(1), end_date=d(5),
        days=5, net_price_cents=2500, vat_rate_percent=24, advertiser_legal_name="Acme OÜ",
        advertiser_registry_code="12345678", paid_at=NOW,
    )
    ended_p = Promotion(
        event_id=live_ev.id, organizer_id=org.id, status="ended_early", start_date=d(20), end_date=d(24),
        days=5, net_price_cents=2500, vat_rate_percent=24, advertiser_legal_name="Acme OÜ",
        advertiser_registry_code="12345678", end_reason="admin",
    )
    void_p = Promotion(
        event_id=live_ev.id, organizer_id=org.id, status="void", start_date=d(26), end_date=d(28),
        days=3, net_price_cents=1500, vat_rate_percent=24, advertiser_legal_name="Acme OÜ",
        advertiser_registry_code="12345678",
    )
    db.add_all([live_p, paused_p, ended_p, void_p])
    await db.flush()
    # The clock for the list is the router's: freeze it inside the live windows.
    monkeypatch.setattr(router_module, "now_tallinn", lambda: at_tallinn(2090, 1, 3, 12))
    items = (await oclient.get("/organizer/promotions")).json()["items"]
    by_id = {(i["kind"], i["id"]): i for i in items}
    assert by_id[("request", rid)]["status"] == "declined"
    assert by_id[("request", rid)]["decline_reason"] == "Not eligible"
    assert by_id[("promotion", awaiting.id)]["status"] == "awaiting_payment"
    assert by_id[("promotion", scheduled.id)]["status"] == "scheduled"
    assert by_id[("promotion", live_p.id)]["status"] == "live"
    assert by_id[("promotion", live_p.id)]["paused_reason"] is None
    assert by_id[("promotion", paused_p.id)]["status"] == "paused"
    assert by_id[("promotion", paused_p.id)]["paused_reason"] == "event_not_public"
    assert by_id[("promotion", ended_p.id)]["status"] == "ended_early"
    assert by_id[("promotion", void_p.id)]["status"] == "cancelled"
    created = [i["created_at"] for i in items]
    assert created == sorted(created, reverse=True)


@pytest.mark.asyncio
async def test_event_list_flags_promotable_and_badge(oclient, db, make) -> None:
    free = await own_event(make)
    asked = await own_event(make)
    unowned_claim_ev = await make.event()
    await oclient.post("/organizer/promotions/requests", json=req_body(asked.id))
    ended = await own_event(
        make, starts_at=at_tallinn(2020, 1, 1), ends_at=at_tallinn(2020, 1, 2)
    )
    rows = {r["id"]: r["promotion"] for r in (await oclient.get("/organizer/events")).json()["events"]}
    assert rows[free.id] == {"promotable": True, "badge": None}
    assert rows[asked.id] == {"promotable": False, "badge": "requested"}
    assert rows[ended.id] == {"promotable": False, "badge": None}
    assert unowned_claim_ev.id not in rows


async def paid_promo(db, make, org, start=10, end=14):
    ev = await make.event(submitted_by=org)
    p = await grant_promotion(db, ev, GrantRequest(d(start), d(end), "Acme OÜ", "12345678"), NOW)
    await mark_paid(db, p.id, NOW)
    return ev, p


@pytest.mark.asyncio
async def test_report_shows_complete_days_only_and_no_viewer_data(oclient, db, make, monkeypatch) -> None:
    _, p = await paid_promo(db, make, Who.organizer)
    db.add_all(
        [
            PromotionDailyStat(
                promotion_id=p.id, day=d(10), gate_outcome="shown", explore_served=7,
                daily5_placed=3, digest_sent=2, web_opens=4, digest_opens=1, slot_dislikes=9,
            ),
            PromotionDailyStat(
                promotion_id=p.id, day=d(11), gate_outcome="paused", gate_reason="organizer_not_owner",
            ),
            PromotionDailyStat(promotion_id=p.id, day=d(12), gate_outcome="shown", explore_served=5),
        ]
    )
    p.daily5_reach = 3
    await db.flush()
    monkeypatch.setattr(router_module, "now_tallinn", lambda: at_tallinn(2090, 1, 12, 9))
    data = (await oclient.get(f"/organizer/promotions/{p.id}/report")).json()
    assert [row["day"] for row in data["days"]] == [d(10).isoformat(), d(11).isoformat()]
    first, second = data["days"]
    assert first["shown"] is True and first["paused"] is False
    assert (first["explore_served"], first["daily5_placed"], first["digest_sent"]) == (7, 3, 2)
    assert (first["web_opens"], first["digest_opens"]) == (4, 1)
    assert "slot_dislikes" not in first
    assert second["paused"] is True and second["paused_reason"] == "organizer_not_owner"
    assert data["daily5_reach"] == 3
    assert data["updated"] == "daily"
    assert data["through"] == d(11).isoformat()


@pytest.mark.asyncio
async def test_report_survives_lost_ownership_and_hides_from_others(oclient, db, make) -> None:
    org = Who.organizer
    ev = await make.event()
    claim = await make.publisher_claim(ev, org)
    p = await grant_promotion(db, ev, GrantRequest(d(10), d(14), "Acme OÜ", "12345678"), NOW)
    await mark_paid(db, p.id, NOW)
    claim.status = CLAIM_STATUS_REVOKED
    await db.flush()
    assert (await oclient.get(f"/organizer/promotions/{p.id}/report")).status_code == 200
    listed = (await oclient.get("/organizer/promotions")).json()["items"]
    assert [i["id"] for i in listed] == [p.id]
    Who.organizer = await make.organizer()
    assert (await oclient.get(f"/organizer/promotions/{p.id}/report")).status_code == 404
    assert (await oclient.get("/organizer/promotions")).json()["items"] == []


def _promo(ev_id: int, org_id: int, status: str, start: int, end: int, **kw: Any) -> Promotion:
    return Promotion(
        event_id=ev_id, organizer_id=org_id, status=status, start_date=d(start), end_date=d(end),
        days=end - start + 1, net_price_cents=2500, vat_rate_percent=24,
        advertiser_legal_name="Acme OÜ", advertiser_registry_code="12345678", **kw,
    )


@pytest.mark.asyncio
async def test_list_card_checkout_holds_and_invoice_url(oclient, db, make) -> None:
    org = Who.organizer
    ev = await own_event(make)
    open_hold = _promo(ev.id, org.id, "unpaid", 20, 24, stripe_checkout_session_id="cs_open")
    abandoned = _promo(ev.id, org.id, "void", 26, 28, stripe_checkout_session_id="cs_gone")
    manual_void = _promo(ev.id, org.id, "void", 5, 6)
    manual_unpaid = _promo(ev.id, org.id, "unpaid", 7, 9, billing_email="pay@acme.example")
    paid_card = _promo(
        ev.id, org.id, "paid", 11, 13, paid_at=NOW, stripe_checkout_session_id="cs_paid",
        invoice_url="https://invoice.stripe.com/i/x",
    )
    paid_manual = _promo(ev.id, org.id, "paid", 15, 17, paid_at=NOW)
    db.add_all([open_hold, abandoned, manual_void, manual_unpaid, paid_card, paid_manual])
    await db.flush()
    items = (await oclient.get("/organizer/promotions")).json()["items"]
    by_id = {i["id"]: i for i in items if i["kind"] == "promotion"}
    assert abandoned.id not in by_id
    assert by_id[open_hold.id]["status"] == "awaiting_checkout"
    assert by_id[manual_void.id]["status"] == "cancelled"
    assert by_id[manual_unpaid.id]["status"] == "awaiting_payment"
    assert by_id[paid_card.id]["invoice_url"] == "https://invoice.stripe.com/i/x"
    assert by_id[paid_manual.id]["invoice_url"] is None
    assert by_id[open_hold.id]["invoice_url"] is None


@pytest.mark.asyncio
async def test_list_items_carry_billing_email(oclient, db, make) -> None:
    ev = await own_event(make)
    rid = (
        await oclient.post(
            "/organizer/promotions/requests", json=req_body(ev.id, billing_email="bill@acme.example")
        )
    ).json()["id"]
    unpaid = _promo(ev.id, Who.organizer.id, "unpaid", 20, 22, billing_email="pay@acme.example")
    db.add(unpaid)
    await db.flush()
    items = (await oclient.get("/organizer/promotions")).json()["items"]
    by = {(i["kind"], i["id"]): i for i in items}
    assert by[("request", rid)]["billing_email"] == "bill@acme.example"
    assert by[("promotion", unpaid.id)]["billing_email"] == "pay@acme.example"


@pytest.mark.asyncio
async def test_context_card_eligibility(oclient, make, monkeypatch) -> None:
    clear = await own_event(make, promotion_restriction="none")
    unassessed = await own_event(make)
    flagged = await own_event(make, promotion_restriction="alcohol")
    url = "/organizer/promotions/context?event_id="
    monkeypatch.setattr(settings, "PROMOTIONS_CHECKOUT_ENABLED", True)
    body = (await oclient.get(url + str(clear.id))).json()
    assert (body["checkout_available"], body["review_required"]) == (True, False)
    for ev in (unassessed, flagged):
        body = (await oclient.get(url + str(ev.id))).json()
        assert (body["checkout_available"], body["review_required"]) == (True, True)
    monkeypatch.setattr(settings, "PROMOTIONS_CHECKOUT_ENABLED", False)
    body = (await oclient.get(url + str(clear.id))).json()
    assert (body["checkout_available"], body["review_required"]) == (False, False)


@pytest.mark.asyncio
async def test_event_list_badge_for_open_card_checkout(oclient, db, make) -> None:
    ev = await own_event(make)
    db.add(_promo(ev.id, Who.organizer.id, "unpaid", 20, 24, stripe_checkout_session_id="cs_b"))
    await db.flush()
    rows = {r["id"]: r["promotion"] for r in (await oclient.get("/organizer/events")).json()["events"]}
    assert rows[ev.id]["badge"] == "awaiting_checkout"
