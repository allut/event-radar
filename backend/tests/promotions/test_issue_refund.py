"""Issue refund for a Stripe-paid Promotion (#619): the prefill, the one-call
credit note and card refund, and the extended admin refund endpoint."""

import pytest
from sqlalchemy import select

from app.config import settings
from app.integrations.payments import PaymentProviderError
from app.integrations.providers import get_payment_gateway
from app.models.models import AdminAction, PromotionDailyStat
from app.promotions.grant import PromotionRefused
from app.promotions.lifecycle import end_early, record_refund
from app.promotions.refunds import refund_prefill
from tests.promotions.conftest import NOW, Clock, at_tallinn, d
from tests.promotions.fakes import FakePaymentGateway
from tests.promotions.test_lifecycle_commands import make_promo


@pytest.fixture(autouse=True)
def tax_rate(monkeypatch):
    monkeypatch.setattr(settings, "STRIPE_TAX_RATE_ID", "txr_24")


@pytest.fixture
def gateway() -> FakePaymentGateway:
    return FakePaymentGateway()


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
