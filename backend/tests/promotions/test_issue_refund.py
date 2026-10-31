"""Issue refund for a Stripe-paid Promotion (#619): the prefill, the one-call
credit note and card refund, and the extended admin refund endpoint."""

import pytest
from sqlalchemy import select

from app.config import settings
from app.integrations.payments import PaymentProviderError
from app.integrations.providers import get_payment_gateway
from app.models.audit import AdminAction
from app.models.promotions import PromotionDailyStat
from app.promotions.grant import PromotionRefused
from app.promotions.lifecycle import edit_promotion, end_early, record_refund
from app.promotions.refunds import refund_prefill
from app.promotions.withdraw import withdraw_all, withdraw_promotion
from tests.promotions.conftest import NOW, Clock, at_tallinn, d
from tests.promotions.test_lifecycle_commands import make_promo


@pytest.fixture(autouse=True)
def tax_rate(monkeypatch):
    monkeypatch.setattr(settings, "STRIPE_TAX_RATE_ID", "txr_24")


async def stripe_paid(db, make, start=10, end=14):
    ev, promo = await make_promo(db, make, start, end, paid=True)
    promo.invoice_source = "stripe"
    promo.stripe_payment_intent_id = "pi_1"
    promo.stripe_invoice_id = "in_1"
    await db.flush()
    return ev, promo


async def pause_day(db, promo, day) -> None:
    db.add(PromotionDailyStat(promotion_id=promo.id, day=day, gate_outcome="paused", gate_reason="not_owned"))
    await db.flush()


# --- the command ---------------------------------------------------------


@pytest.mark.asyncio
async def test_stripe_refund_makes_credit_note_and_card_refund_in_one_call(db, make, gateway) -> None:
    _, promo = await stripe_paid(db, make)
    await record_refund(db, promo.id, 1240, "Operator fault", NOW, gateway=gateway)

    (call,) = gateway.refunds
    assert (call.payment_intent_id, call.invoice_id) == ("pi_1", "in_1")
    assert (call.net_cents, call.vat_cents, call.tax_rate_id) == (1000, 240, "txr_24")
    assert promo.refunded_cents == 1240
    assert promo.refund_note == "Operator fault (credit note cn_1, refund re_1)"


@pytest.mark.asyncio
async def test_off_platform_refund_is_only_recorded(db, make, gateway) -> None:
    _, promo = await make_promo(db, make, 10, 14, paid=True)
    await record_refund(db, promo.id, 1000, "wire", NOW, gateway=gateway)
    assert gateway.refunds == []
    assert (promo.refunded_cents, promo.refund_note) == (1000, "wire")


@pytest.mark.asyncio
async def test_invalid_stripe_refund_never_reaches_the_provider(db, make, gateway) -> None:
    _, promo = await stripe_paid(db, make)
    with pytest.raises(PromotionRefused) as exc:
        await record_refund(db, promo.id, 99999, "too much", NOW, gateway=gateway)
    assert exc.value.violations[0].code == "refund_exceeds_paid"
    with pytest.raises(PromotionRefused) as exc:
        await record_refund(db, promo.id, 100, "  ", NOW, gateway=gateway)
    assert exc.value.violations[0].code == "refund_note_required"
    assert gateway.refunds == []


@pytest.mark.asyncio
async def test_provider_failure_records_nothing(db, make, gateway) -> None:
    _, promo = await stripe_paid(db, make)
    gateway.fail_refund = True
    with pytest.raises(PaymentProviderError):
        await record_refund(db, promo.id, 500, "try", NOW, gateway=gateway)
    assert (promo.refunded_cents, promo.refund_note) == (0, None)


# --- the prefill ---------------------------------------------------------


@pytest.mark.asyncio
async def test_prefill_counts_unused_and_paused_days_at_the_price_paid_per_day(db, make) -> None:
    _, promo = await stripe_paid(db, make, 10, 14)
    await pause_day(db, promo, d(10))
    stored = {row.day: row for row in (await db.scalars(select(PromotionDailyStat))).all()}
    prefill = refund_prefill(promo, stored, d(12))
    # Days 13 and 14 are unused, day 10 was paused: 3 of 5 days of the 3100 paid.
    assert prefill == {
        "mode": "stripe",
        "unused_days": 2,
        "paused_days": 1,
        "gross_per_day_cents": 620,
        "suggested_cents": 1860,
        "remaining_cents": 3100,
    }


@pytest.mark.asyncio
async def test_prefill_for_a_scheduled_promotion_is_everything(db, make) -> None:
    _, promo = await stripe_paid(db, make, 10, 14)
    assert refund_prefill(promo, {}, d(1))["suggested_cents"] == 3100  # type: ignore[index]


@pytest.mark.asyncio
async def test_prefill_after_an_early_end_counts_from_the_end_day(db, make) -> None:
    _, promo = await stripe_paid(db, make, 10, 14)
    await end_early(db, promo.id, "operator fault", at_tallinn(2090, 1, 11, 9))
    prefill = refund_prefill(promo, {}, d(20))
    assert prefill is not None and (prefill["unused_days"], prefill["suggested_cents"]) == (3, 1860)


@pytest.mark.asyncio
async def test_prefill_is_capped_at_what_is_left_and_absent_when_not_refundable(db, make) -> None:
    _, promo = await stripe_paid(db, make, 10, 14)
    promo.refunded_cents = 3000
    capped = refund_prefill(promo, {}, d(1))
    assert capped is not None and capped["suggested_cents"] == 100
    _, unpaid = await make_promo(db, make, 10, 14)
    assert refund_prefill(unpaid, {}, d(1)) is None


# --- the endpoint --------------------------------------------------------


@pytest.fixture
def wired(client, gateway):
    client._transport.app.dependency_overrides[get_payment_gateway] = lambda: gateway
    return client


@pytest.mark.asyncio
async def test_endpoint_issues_a_stripe_refund_and_audits_it(wired, db, make, gateway) -> None:
    _, promo = await stripe_paid(db, make)
    await db.commit()
    Clock.now = at_tallinn(2090, 1, 12)
    detail = (await wired.get(f"/admin/promotions/{promo.id}")).json()
    assert detail["refund_prefill"]["mode"] == "stripe"
    resp = await wired.post(
        f"/admin/promotions/{promo.id}/refund", json={"amount_cents": 1860, "note": "paused days"}
    )
    assert resp.status_code == 200
    assert resp.json()["refunded_cents"] == 1860
    assert len(gateway.refunds) == 1
    rows = (await db.scalars(select(AdminAction).where(AdminAction.action == "promotion_refund"))).all()
    assert [r.result["amount_cents"] for r in rows if r.target == str(promo.id)] == [1860]


@pytest.mark.asyncio
async def test_endpoint_reports_a_provider_failure_as_502_and_records_nothing(wired, db, make, gateway) -> None:
    _, promo = await stripe_paid(db, make)
    await db.commit()
    url = f"/admin/promotions/{promo.id}"  # a refused command expires the ORM objects
    gateway.fail_refund = True
    resp = await wired.post(f"{url}/refund", json={"amount_cents": 500, "note": "x"})
    assert resp.status_code == 502
    assert (await wired.get(url)).json()["refunded_cents"] == 0


# --- withdraw refunds card-paid Promotions through the gateway (#620) ----------


@pytest.mark.asyncio
async def test_withdraw_refunds_a_card_paid_promotion_through_the_gateway(db, make, gateway) -> None:
    _, promo = await stripe_paid(db, make)
    result = await withdraw_promotion(db, promo.id, at_tallinn(2090, 1, 5), gateway=gateway)
    (call,) = gateway.refunds
    assert (call.net_cents + call.vat_cents, result.refund_cents) == (3100, 3100)
    assert (promo.status, promo.refunded_cents) == ("ended_early", 3100)
    assert "credit note cn_1" in (promo.refund_note or "")


@pytest.mark.asyncio
async def test_withdraw_of_a_card_paid_promotion_stays_paid_when_stripe_refuses(db, make, gateway) -> None:
    _, promo = await stripe_paid(db, make)
    gateway.fail_refund = True
    with pytest.raises(PaymentProviderError):
        await withdraw_promotion(db, promo.id, at_tallinn(2090, 1, 5), gateway=gateway)
    assert (promo.status, promo.refunded_cents) == ("paid", 0)


@pytest.mark.asyncio
async def test_withdraw_all_skips_a_card_promotion_stripe_refuses_and_ends_the_rest(db, make, gateway) -> None:
    _, card = await stripe_paid(db, make)
    _, bank = await make_promo(db, make, 10, 14, paid=True)
    gateway.fail_refund = True
    outcome = await withdraw_all(db, at_tallinn(2090, 1, 5), gateway=gateway)
    assert {"id": card.id, "code": "refund_provider_failed"} in outcome.skipped
    assert bank.id in {r.promotion.id for r in outcome.withdrawn}
    assert card.status == "paid"


@pytest.mark.asyncio
async def test_withdraw_endpoints_use_the_gateway(wired, db, make, gateway, monkeypatch) -> None:
    monkeypatch.setattr(settings, "PROMOTIONS_SLOTS_ENABLED", False)
    _, promo = await stripe_paid(db, make)
    await db.commit()
    url = f"/admin/promotions/{promo.id}/withdraw"
    Clock.now = at_tallinn(2090, 1, 5)
    gateway.fail_refund = True
    assert (await wired.post(url)).status_code == 502
    gateway.fail_refund = False
    resp = await wired.post(url)
    assert resp.status_code == 200
    assert resp.json()["refunded_cents"] == 3100 and len(gateway.refunds) == 1


@pytest.mark.asyncio
async def test_withdraw_all_endpoint_reports_a_stripe_refusal_in_skipped(wired, db, make, gateway, monkeypatch) -> None:
    monkeypatch.setattr(settings, "PROMOTIONS_SLOTS_ENABLED", False)
    _, promo = await stripe_paid(db, make)
    await db.commit()
    Clock.now = at_tallinn(2090, 1, 5)
    gateway.fail_refund = True
    body = (await wired.post("/admin/promotions/withdraw-all")).json()
    assert {"id": promo.id, "code": "refund_provider_failed"} in body["skipped"]


# --- a card-paid Promotion's dates are fixed --------------------------------------


@pytest.mark.asyncio
async def test_edit_refuses_date_changes_on_a_card_paid_promotion(db, make) -> None:
    _, promo = await stripe_paid(db, make)
    with pytest.raises(PromotionRefused) as exc:
        await edit_promotion(db, promo.id, {"end_date": d(16)}, NOW)
    assert exc.value.violations[0].code == "stripe_paid_dates_locked"
    assert promo.net_price_cents == 2500
    await edit_promotion(db, promo.id, {"billing_email": "new@x.test"}, NOW)  # other fields still edit
    assert promo.billing_email == "new@x.test"


@pytest.mark.asyncio
async def test_the_dates_locked_refusal_is_a_409(wired, db, make) -> None:
    _, promo = await stripe_paid(db, make)
    await db.commit()
    resp = await wired.patch(f"/admin/promotions/{promo.id}", json={"end_date": "2090-01-16"})
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "stripe_paid_dates_locked"


# --- the Stripe call runs outside the cap lock (real commits) ---------------------


@pytest.mark.asyncio
async def test_stripe_refund_runs_without_the_cap_lock_held(engine, sessionmaker_for, gateway) -> None:
    from sqlalchemy import delete, text

    from app.constants.promotions import PROMOTION_CAP_LOCK_KEY
    from app.models.events import Event
    from app.models.promotions import Promotion, PromotionSnapshot
    from app.models.organizers import Organizer
    from tests.conftest import Factory

    seen: list[bool] = []
    real_refund = gateway.refund

    async def probing_refund(request):
        async with engine.connect() as other:  # a second connection can take the lock
            seen.append(
                bool(await other.scalar(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": PROMOTION_CAP_LOCK_KEY}))
            )
        return await real_refund(request)

    gateway.refund = probing_refund  # type: ignore[method-assign]
    ids: dict[str, int] = {}
    try:
        async with sessionmaker_for() as setup:
            ev, promo = await stripe_paid(setup, Factory(setup), 20, 24)
            ids = {"event": ev.id, "promo": promo.id, "org": ev.submitted_by_organizer_id}
            await setup.commit()
        async with sessionmaker_for() as s:
            await record_refund(s, ids["promo"], 1240, "Operator fault", NOW, gateway=gateway)
            await s.commit()
        assert seen == [True]
        async with sessionmaker_for() as check:
            assert (await check.get(Promotion, ids["promo"])).refunded_cents == 1240
    finally:
        async with sessionmaker_for() as cleanup:
            await cleanup.execute(delete(PromotionSnapshot).where(PromotionSnapshot.promotion_id == ids.get("promo")))
            await cleanup.execute(delete(Promotion).where(Promotion.id == ids.get("promo")))
            await cleanup.execute(delete(Event).where(Event.id == ids.get("event")))
            await cleanup.execute(delete(Organizer).where(Organizer.id == ids.get("org")))
            await cleanup.commit()
