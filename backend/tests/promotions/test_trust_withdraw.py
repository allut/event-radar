"""Trust panel counts, the complaint logger and Withdraw (#620), against a
real Postgres."""

from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.config import settings
from app.constants.admin import (
    ADMIN_ACTION_PROMOTION_COMPLAINT,
    ADMIN_ACTION_PROMOTION_END,
    ADMIN_ACTION_PROMOTION_REFUND,
)
from app.constants.promotions import (
    PROMOTION_END_REASON_FEATURE_WITHDRAWN,
    PROMOTION_STATUS_ENDED_EARLY,
)
from app.models.models import (
    AdminAction,
    EmailAdConsentLog,
    EventReport,
    PromotionDailyStat,
    User,
)
from app.promotions.grant import GrantRequest, grant_promotion
from app.promotions.lifecycle import mark_paid
from app.promotions.trust import trust_panel
from app.promotions.withdraw import withdraw_all, withdraw_promotion
from tests.promotions.conftest import NOW, at_tallinn, d
from tests.promotions.test_lifecycle_api import audit_rows, mails, promo  # noqa: F401


async def make_user(db, n: int, *, consent: bool = False) -> User:
    user = User(email=f"trust-{n}-{id(db)}@example.com", email_ad_consent=consent)
    db.add(user)
    await db.flush()
    return user


async def paid_promo(db, make, start, end, *, complimentary=False):
    org = await make.organizer()
    ev = await make.event(submitted_by=org)
    p = await grant_promotion(
        db,
        ev,
        GrantRequest(
            d(start), d(end), "Acme OÜ", "12345678",
            is_complimentary=complimentary, complimentary_note="pilot" if complimentary else None,
        ),
        NOW,
    )
    if not complimentary:  # a complimentary grant is created paid
        await mark_paid(db, p.id, NOW)
    return org, ev, p


async def baseline(db) -> dict:
    return await trust_panel(db, at_tallinn(2090, 1, 20, 12))


# --- Trust panel -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_trust_panel_counts_both_periods(db, make) -> None:
    before = await baseline(db)
    _, ev, p = await paid_promo(db, make, 10, 20)
    now = at_tallinn(2090, 1, 20, 12)
    users = [await make_user(db, i) for i in range(4)]
    old = now - timedelta(days=40)
    recent = now - timedelta(days=2)
    # Reports: one inside the window (recent), one before the Promotion started.
    db.add(EventReport(user_id=users[0].id, event_id=ev.id, reason="spam", created_at=recent))
    db.add(EventReport(user_id=users[1].id, event_id=ev.id, reason="spam", created_at=at_tallinn(2090, 1, 5)))
    # Consent log: a grant, a recent settings withdrawal, an old link withdrawal.
    db.add(EmailAdConsentLog(user_id=users[0].id, granted=True, wording_version=1, source="settings", locale="et", created_at=recent))
    db.add(EmailAdConsentLog(user_id=users[0].id, granted=False, wording_version=1, source="settings", locale="et", created_at=recent))
    db.add(EmailAdConsentLog(user_id=users[1].id, granted=False, wording_version=1, source="email_link", locale="et", created_at=old))
    db.add(EmailAdConsentLog(user_id=users[1].id, granted=True, wording_version=1, source="email_link_undo", locale="et", created_at=old))
    # Delivery: one day inside the rolling window, one before it.
    db.add(PromotionDailyStat(promotion_id=p.id, day=d(18), explore_served=10, daily5_placed=4, digest_sent=2, web_opens=3, slot_dislikes=1))
    db.add(PromotionDailyStat(promotion_id=p.id, day=date(2089, 12, 1), explore_served=5, web_opens=1, slot_dislikes=2))
    # Complaints.
    for when in (recent, old):
        db.add(AdminAction(action=ADMIN_ACTION_PROMOTION_COMPLAINT, target="promotion_ads",
                           result={"note": "too many ads", "source": "email"}, created_at=when))
    users[2].email_ad_consent = True
    await db.flush()

    panel = await trust_panel(db, now)
    cur = panel["current"]
    assert cur["live_promotions"] - before["current"]["live_promotions"] == 1
    assert cur["consenters"] - before["current"]["consenters"] == 1

    def delta(period: str, *path: str) -> int:
        a, b = panel["periods"][period], before["periods"][period]
        for key in path:
            a, b = a[key], b[key]
        return a - b

    assert delta("since_launch", "reports_on_promoted") == 1
    assert delta("rolling_4_weeks", "reports_on_promoted") == 1
    assert delta("since_launch", "consent_withdrawals", "total") == 2
    assert delta("rolling_4_weeks", "consent_withdrawals", "total") == 1
    assert delta("since_launch", "consent_withdrawals", "by_source", "settings") == 1
    assert delta("since_launch", "consent_withdrawals", "by_source", "email_link") == 1
    assert delta("rolling_4_weeks", "consent_withdrawals", "by_source", "email_link") == 0
    assert delta("since_launch", "consents_granted") == 1  # the undo is not a new consent
    assert delta("since_launch", "slots_served") == 21
    assert delta("rolling_4_weeks", "slots_served") == 16
    assert delta("rolling_4_weeks", "slot_dislikes") == 1
    assert delta("since_launch", "slot_dislikes") == 3
    assert delta("since_launch", "web_opens") == 4
    assert delta("since_launch", "slots_served_by_surface", "explore") == 15
    assert delta("since_launch", "complaints") == 2
    assert delta("rolling_4_weeks", "complaints") == 1
    assert panel["recent_complaints"][0]["note"] == "too many ads"
    assert panel["window_days"] == 28


@pytest.mark.asyncio
async def test_trust_panel_query_count_is_fixed(db, make, engine) -> None:
    from sqlalchemy import event as sa_event

    # Compare the count with zero then with several Promotions: it must not grow.
    seen: list[str] = []

    def listener(conn, cursor, statement, *rest):
        seen.append(statement)

    sync_engine = engine.sync_engine
    sa_event.listen(sync_engine, "before_cursor_execute", listener)
    try:
        await baseline(db)
        seen.clear()  # the first call also opens the transaction
        await baseline(db)
        first = len(seen)
        for i in range(3):
            await paid_promo(db, make, 22 + i * 3, 24 + i * 3)
        seen.clear()
        await baseline(db)
        assert len(seen) == first
    finally:
        sa_event.remove(sync_engine, "before_cursor_execute", listener)


@pytest.mark.asyncio
async def test_trust_endpoint_and_complaint_logger(client, db) -> None:
    before = (await client.get("/admin/promotions/trust")).json()
    resp = await client.post(
        "/admin/promotions/complaints",
        json={"note": "  Ad shown too often  ", "source": "contact_form", "complainant": "Mari"},
    )
    assert resp.status_code == 201
    assert resp.json() == {
        "logged": True, "note": "Ad shown too often", "source": "contact_form", "complainant": "Mari",
    }
    rows = (await db.scalars(select(AdminAction).where(AdminAction.action == ADMIN_ACTION_PROMOTION_COMPLAINT))).all()
    assert rows[-1].result["note"] == "Ad shown too often"
    after = (await client.get("/admin/promotions/trust")).json()
    # The row is stamped with the real clock, so only "since launch" sees it
    # under the fake 2090 "now".
    launch = "since_launch"
    assert after["periods"][launch]["complaints"] == before["periods"][launch]["complaints"] + 1
    assert after["recent_complaints"][0]["complainant"] == "Mari"


@pytest.mark.asyncio
async def test_complaint_needs_note_and_known_source(client) -> None:
    assert (await client.post("/admin/promotions/complaints", json={"note": "   "})).status_code == 422
    assert (await client.post("/admin/promotions/complaints", json={})).status_code == 422
    bad = await client.post("/admin/promotions/complaints", json={"note": "x", "source": "carrier-pigeon"})
    assert bad.status_code == 422


# --- Withdraw ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_withdraw_scheduled_refunds_everything(db, make) -> None:
    _, _, p = await paid_promo(db, make, 10, 14)  # 5 days, 500 net, VAT 24%
    result = await withdraw_promotion(db, p.id, at_tallinn(2090, 1, 5))
    assert result.unused_days == 5
    assert p.status == PROMOTION_STATUS_ENDED_EARLY
    assert p.end_reason == PROMOTION_END_REASON_FEATURE_WITHDRAWN
    assert p.refunded_cents == 3100  # 2500 net + 600 VAT, the full charge
    assert result.refund_cents == 3100


@pytest.mark.asyncio
async def test_withdraw_live_refunds_days_after_today(db, make) -> None:
    _, _, p = await paid_promo(db, make, 10, 14)
    result = await withdraw_promotion(db, p.id, at_tallinn(2090, 1, 11, 9))
    assert result.unused_days == 3  # 12, 13, 14; today (the 11th) counts as used
    assert p.refunded_cents == 1860  # 1500 net + 360 VAT


@pytest.mark.asyncio
async def test_withdraw_last_day_and_complimentary_refund_nothing(db, make) -> None:
    _, _, last = await paid_promo(db, make, 10, 14)
    assert (await withdraw_promotion(db, last.id, at_tallinn(2090, 1, 14))).refund_cents == 0
    assert last.status == PROMOTION_STATUS_ENDED_EARLY and last.refunded_cents == 0
    _, _, free = await paid_promo(db, make, 20, 24, complimentary=True)
    assert (await withdraw_promotion(db, free.id, at_tallinn(2090, 1, 5))).refund_cents == 0
    assert free.end_reason == PROMOTION_END_REASON_FEATURE_WITHDRAWN


@pytest.mark.asyncio
async def test_withdraw_all_skips_unpaid_and_finished(db, make) -> None:
    _, _, a = await paid_promo(db, make, 10, 14)
    _, _, b = await paid_promo(db, make, 16, 20)
    org = await make.organizer()
    ev = await make.event(submitted_by=org)
    unpaid = await grant_promotion(db, ev, GrantRequest(d(22), d(26), "Acme OÜ", "12345678"), NOW)
    outcome = await withdraw_all(db, at_tallinn(2090, 1, 12))
    ids = {r.promotion.id for r in outcome.withdrawn}
    assert {a.id, b.id} <= ids and unpaid.id not in ids
    assert outcome.skipped == []
    assert unpaid.status == "unpaid"


@pytest.mark.asyncio
async def test_withdraw_endpoint_requires_slots_off_and_audits(client, db, make, mails, monkeypatch) -> None:  # noqa: F811
    org, ev, p = await promo(db, make, 10, 14, paid=True)
    monkeypatch.setattr(settings, "PROMOTIONS_SLOTS_ENABLED", True)
    blocked = await client.post(f"/admin/promotions/{p.id}/withdraw")
    assert blocked.status_code == 409 and blocked.json()["detail"] == "slots_still_enabled"
    assert (await client.post("/admin/promotions/withdraw-all")).status_code == 409

    monkeypatch.setattr(settings, "PROMOTIONS_SLOTS_ENABLED", False)
    resp = await client.post(f"/admin/promotions/{p.id}/withdraw")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ended_early" and body["end_reason"] == "feature_withdrawn"
    assert body["refunded_cents"] == 3100
    assert len(await audit_rows(db, ADMIN_ACTION_PROMOTION_END, p.id)) == 1
    assert len(await audit_rows(db, ADMIN_ACTION_PROMOTION_REFUND, p.id)) == 1
    ended, _ = mails
    ended.assert_awaited_once()
    again = await client.post(f"/admin/promotions/{p.id}/withdraw")
    assert again.status_code == 409
    assert (await client.post("/admin/promotions/999999999/withdraw")).status_code == 404


@pytest.mark.asyncio
async def test_withdraw_all_endpoint(client, db, make, mails, monkeypatch) -> None:  # noqa: F811
    _, _, p1 = await promo(db, make, 10, 14, paid=True)
    _, _, p2 = await promo(db, make, 16, 20, paid=True)
    monkeypatch.setattr(settings, "PROMOTIONS_SLOTS_ENABLED", False)
    resp = await client.post("/admin/promotions/withdraw-all")
    assert resp.status_code == 200
    body = resp.json()
    by_id = {w["id"]: w for w in body["withdrawn"]}
    assert by_id[p1.id]["refund_cents"] == 3100 and by_id[p2.id]["unused_days"] == 5
    assert body["skipped"] == []
    ended, _ = mails
    assert ended.await_count >= 2
