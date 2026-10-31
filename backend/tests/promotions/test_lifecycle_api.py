"""The /admin promotion lifecycle JSON API: status codes, response shape,
audit rows, cap release and the Organizer email, against a real Postgres."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.constants.admin import (
    ADMIN_ACTION_PROMOTION_EDIT,
    ADMIN_ACTION_PROMOTION_END,
    ADMIN_ACTION_PROMOTION_MARK_PAID,
    ADMIN_ACTION_PROMOTION_REFUND,
    ADMIN_ACTION_PROMOTION_REPOINT,
    ADMIN_ACTION_PROMOTION_VOID,
)
from app.models.audit import AdminAction
from app.promotions.cap import cap_strip
from app.promotions.grant import GrantRequest, grant_promotion
from app.promotions.lifecycle import mark_paid
from tests.promotions.conftest import NOW, Clock, at_tallinn, d


@pytest.fixture
def mails(monkeypatch):
    from app.routers.utils import promotions as notify_module

    ended = AsyncMock()
    voided = AsyncMock()
    monkeypatch.setattr(notify_module, "send_promotion_ended_email", ended)
    monkeypatch.setattr(notify_module, "send_promotion_void_email", voided)
    return ended, voided


async def promo(db, make, start=10, end=14, *, paid=False, locale="en", **event_kw):
    org = await make.organizer()
    org.locale = locale
    ev = await make.event(submitted_by=org, **event_kw)
    p = await grant_promotion(db, ev, GrantRequest(d(start), d(end), "Acme OÜ", "12345678"), NOW)
    if paid:
        await mark_paid(db, p.id, NOW)
    await db.commit()  # a refused command rolls the shared session back to here
    # A refused command rolls the shared test session back, which expires ORM
    # objects; the tests only need the id afterwards.
    return org, ev, SimpleNamespace(id=p.id)


async def audit_rows(db, action: str, promotion_id: int) -> list[AdminAction]:
    rows = (await db.scalars(select(AdminAction).where(AdminAction.action == action))).all()
    return [r for r in rows if r.target == str(promotion_id)]


async def reserved_on(db, day: date) -> int:
    strip = await cap_strip(db, NOW.date())
    for cap_day in strip:
        if cap_day.day == day:
            return cap_day.reserved
    raise AssertionError(day)


@pytest.mark.asyncio
async def test_detail_shape(client, db, make) -> None:
    org, ev, p = await promo(db, make, paid=True)
    data = (await client.get(f"/admin/promotions/{p.id}")).json()
    assert data["id"] == p.id
    assert data["status"] == "paid" and data["state"] == "scheduled"
    assert data["event"]["id"] == ev.id and data["event"]["last_day"] == "2090-02-28"
    assert data["actions"] == {
        "mark_paid": False,
        "edit": True,
        "edit_scope": "full",
        "repoint": True,
        "end": True,
        "void": False,
        "refund": True,
        "refundable_cents": 3100,
        "clear_restriction": False,
    }
    assert [s["trigger"] for s in data["snapshots"]] == ["mark_paid"]
    snap = data["snapshots"][0]
    assert set(snap) >= {"title", "description_excerpt", "image_url", "venue_name", "label_text"}
    assert snap["title"].keys() == {"et", "en", "ru"}
    assert data["repoint_candidates"] == []
    assert data["audit"] == []
    assert (await client.get("/admin/promotions/999999999")).status_code == 404


@pytest.mark.asyncio
async def test_actions_follow_the_clock(client, db, make) -> None:
    _, _, p = await promo(db, make, 10, 14, paid=True)
    Clock.now = at_tallinn(2090, 1, 12)
    live = (await client.get(f"/admin/promotions/{p.id}")).json()
    assert live["state"] == "live"
    assert live["actions"]["edit_scope"] == "end_date" and live["actions"]["end"] is True
    Clock.now = at_tallinn(2090, 1, 15)
    done = (await client.get(f"/admin/promotions/{p.id}")).json()
    assert done["state"] == "finished"
    assert (done["actions"]["edit"], done["actions"]["end"], done["actions"]["edit_scope"]) == (False, False, None)


@pytest.mark.asyncio
async def test_mark_paid_endpoint_audits_and_snapshots(client, db, make) -> None:
    _, _, p = await promo(db, make)
    resp = await client.post(f"/admin/promotions/{p.id}/mark-paid", json={"invoice_reference": "ER-M-2090-5"})
    assert resp.status_code == 200
    data = resp.json()
    assert (data["status"], data["invoice_reference"]) == ("paid", "ER-M-2090-5")
    assert len(data["snapshots"]) == 1
    (row,) = await audit_rows(db, ADMIN_ACTION_PROMOTION_MARK_PAID, p.id)
    assert row.result["status"] == "paid"
    assert [a["action"] for a in data["audit"]] == [ADMIN_ACTION_PROMOTION_MARK_PAID]


@pytest.mark.asyncio
async def test_mark_paid_refused_after_start_is_409_without_audit(client, db, make) -> None:
    _, _, p = await promo(db, make, 10, 14)
    Clock.now = at_tallinn(2090, 1, 10, 0, 0, 0)
    resp = await client.post(f"/admin/promotions/{p.id}/mark-paid", json={})
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "already_started"
    assert await audit_rows(db, ADMIN_ACTION_PROMOTION_MARK_PAID, p.id) == []


@pytest.mark.asyncio
async def test_edit_endpoint_and_error_statuses(client, db, make) -> None:
    _, _, p = await promo(db, make, 10, 14)
    resp = await client.patch(f"/admin/promotions/{p.id}", json={"end_date": "2090-01-16", "billing_email": "x@example.com"})
    assert resp.status_code == 200
    assert (resp.json()["end_date"], resp.json()["net_price_cents"]) == ("2090-01-16", 3500)
    (row,) = await audit_rows(db, ADMIN_ACTION_PROMOTION_EDIT, p.id)
    assert row.result["changes"] == {"end_date": "2090-01-16", "billing_email": "x@example.com"}
    assert (await client.patch(f"/admin/promotions/{p.id}", json={"end_date": "2090-01-11"})).status_code == 422
    assert (await client.patch(f"/admin/promotions/{p.id}", json={"start_date": None})).status_code == 422
    assert (await client.patch(f"/admin/promotions/{p.id}", json={})).status_code == 422
    cleared = await client.patch(f"/admin/promotions/{p.id}", json={"billing_email": None})
    assert cleared.status_code == 200 and cleared.json()["billing_email"] is None
    assert (await client.patch("/admin/promotions/999999999", json={"end_date": "2090-01-16"})).status_code == 404


@pytest.mark.asyncio
async def test_live_edit_through_the_api(client, db, make) -> None:
    _, _, p = await promo(db, make, 10, 16, paid=True)
    Clock.now = at_tallinn(2090, 1, 12)
    bad = await client.patch(f"/admin/promotions/{p.id}", json={"advertiser_legal_name": "X"})
    assert (bad.status_code, bad.json()["detail"]["code"]) == (422, "live_edit_end_date_only")
    ok = await client.patch(f"/admin/promotions/{p.id}", json={"end_date": "2090-01-13"})
    assert ok.status_code == 200 and ok.json()["days"] == 4


@pytest.mark.asyncio
async def test_repoint_endpoint(client, db, make) -> None:
    org = await make.organizer()
    canon = await make.event(submitted_by=org)
    canon.dedup_group_id = canon.id
    dupe = await make.event(submitted_by=org, dedup_group_id=canon.id)
    pid = (await grant_promotion(db, dupe, GrantRequest(d(10), d(14), "A", "12345678"), NOW)).id
    other = await make.event(submitted_by=org)
    canon_id, other_id = canon.id, other.id
    detail = (await client.get(f"/admin/promotions/{pid}")).json()
    assert [c["event_id"] for c in detail["repoint_candidates"]] == [canon_id]
    resp = await client.post(f"/admin/promotions/{pid}/repoint", json={"event_id": canon_id})
    assert resp.status_code == 200 and resp.json()["event_id"] == canon_id
    assert len(await audit_rows(db, ADMIN_ACTION_PROMOTION_REPOINT, pid)) == 1
    refused = await client.post(f"/admin/promotions/{pid}/repoint", json={"event_id": other_id})
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "repoint_not_same_dedup_group"


@pytest.mark.asyncio
async def test_end_early_emails_the_reason_in_the_organizer_locale_and_releases_days(client, db, make, mails) -> None:
    ended, voided = mails
    org, ev, p = await promo(db, make, 4, 8, paid=True, locale="et")
    Clock.now = at_tallinn(2090, 1, 1, 12)
    assert await reserved_on(db, d(7)) == 1
    resp = await client.post(f"/admin/promotions/{p.id}/end", json={"reason": "  Event moved  "})
    assert resp.status_code == 200
    assert (resp.json()["status"], resp.json()["end_note"]) == ("ended_early", "Event moved")
    assert await reserved_on(db, d(7)) == 0
    ended.assert_awaited_once()
    args = ended.await_args.args
    assert args[0] == org.email
    assert args[1] == ev.title_orig
    assert (args[2], args[3], args[4], args[5]) == (d(4), d(8), "Event moved", "et")
    voided.assert_not_awaited()
    (row,) = await audit_rows(db, ADMIN_ACTION_PROMOTION_END, p.id)
    assert row.result["reason"] == "Event moved"


@pytest.mark.asyncio
async def test_end_requires_a_reason_and_sends_nothing_when_refused(client, db, make, mails) -> None:
    ended, _ = mails
    _, _, p = await promo(db, make, paid=True)
    assert (await client.post(f"/admin/promotions/{p.id}/end", json={})).status_code == 422
    blank = await client.post(f"/admin/promotions/{p.id}/end", json={"reason": "   "})
    assert (blank.status_code, blank.json()["detail"]["code"]) == (422, "reason_required")
    _, _, unpaid = await promo(db, make)
    assert (await client.post(f"/admin/promotions/{unpaid.id}/end", json={"reason": "x"})).status_code == 409
    ended.assert_not_awaited()
    assert await audit_rows(db, ADMIN_ACTION_PROMOTION_END, p.id) == []


@pytest.mark.asyncio
async def test_a_failing_email_does_not_undo_the_command(client, db, make, mails) -> None:
    ended, _ = mails
    ended.side_effect = RuntimeError("resend down")
    _, _, p = await promo(db, make, paid=True)
    resp = await client.post(f"/admin/promotions/{p.id}/end", json={"reason": "x"})
    assert resp.status_code == 200 and resp.json()["status"] == "ended_early"


@pytest.mark.asyncio
async def test_void_emails_the_reason_and_releases_all_days(client, db, make, mails) -> None:
    ended, voided = mails
    org, _, p = await promo(db, make, 10, 14, locale="ru")
    assert await reserved_on(db, d(10)) == 1
    resp = await client.post(f"/admin/promotions/{p.id}/void", json={"reason": "Unpaid"})
    assert resp.status_code == 200 and resp.json()["status"] == "void"
    assert await reserved_on(db, d(10)) == 0
    voided.assert_awaited_once()
    assert voided.await_args.args[4:] == ("Unpaid", "ru")
    ended.assert_not_awaited()
    assert len(await audit_rows(db, ADMIN_ACTION_PROMOTION_VOID, p.id)) == 1
    assert (await client.post(f"/admin/promotions/{p.id}/void", json={"reason": "again"})).status_code == 409


@pytest.mark.asyncio
async def test_refund_endpoint(client, db, make) -> None:
    _, _, p = await promo(db, make, 10, 14, paid=True)
    resp = await client.post(f"/admin/promotions/{p.id}/refund", json={"amount_cents": 1000, "note": "wire 1"})
    assert resp.status_code == 200
    assert (resp.json()["refunded_cents"], resp.json()["refund_note"]) == (1000, "wire 1")
    assert resp.json()["actions"]["refundable_cents"] == 2100
    assert len(await audit_rows(db, ADMIN_ACTION_PROMOTION_REFUND, p.id)) == 1
    over = await client.post(f"/admin/promotions/{p.id}/refund", json={"amount_cents": 5000, "note": "x"})
    assert (over.status_code, over.json()["detail"]["code"]) == (409, "refund_exceeds_paid")
    zero = await client.post(f"/admin/promotions/{p.id}/refund", json={"amount_cents": 0, "note": "x"})
    assert (zero.status_code, zero.json()["detail"]["code"]) == (422, "refund_amount_invalid")
    assert (await client.post(f"/admin/promotions/{p.id}/refund", json={"amount_cents": 1})).status_code == 422
