"""POST /webhooks/stripe (#618, #619): signature, replay, order, paid, void,
late payment and dispute. Real Postgres; Stripe and the emails are fakes."""

import time
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.config import settings
from app.integrations.payments import PaymentProviderError
from app.integrations.providers import get_payment_gateway
from app.models.models import AdminAction, Organizer, ProcessedStripeEvent, Promotion, PromotionSnapshot
from app.promotions import stripe_events
from app.promotions.checkout import CheckoutInput, start_checkout
from app.routers import stripe_webhook as webhook_router
from tests.promotions.conftest import NOW, d
from tests.promotions.fakes import (
    WEBHOOK_SECRET,
    FakePaymentGateway,
    FakeRegistry,
    completed_session,
    sign,
    stripe_event,
)


@pytest.fixture
def gateway() -> FakePaymentGateway:
    return FakePaymentGateway()


@pytest.fixture
def mails(monkeypatch):
    sent: dict[str, list] = {"admin": [], "organizer": []}

    async def admin(headline, detail, promotion_id):
        sent["admin"].append((headline, promotion_id))

    async def organizer(to_email, title, start, end, reason, locale, http_client=None):
        sent["organizer"].append((to_email, locale, reason))

    monkeypatch.setattr(stripe_events, "send_payment_notice", admin)
    monkeypatch.setattr(stripe_events, "send_promotion_late_refund_email", organizer)
    return sent


@pytest_asyncio.fixture
async def client(db, gateway, monkeypatch):
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "STRIPE_TAX_RATE_ID", "txr_24")

    @asynccontextmanager
    async def session_ctx():
        try:
            yield db
        except Exception:
            await db.rollback()  # what closing a real session does to open work
            raise

    monkeypatch.setattr(webhook_router, "AsyncSessionLocal", session_ctx)
    monkeypatch.setattr(webhook_router, "now_tallinn", lambda: NOW)
    app = FastAPI()
    app.include_router(webhook_router.router)
    app.dependency_overrides[get_payment_gateway] = lambda: gateway
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def held_promotion(db, make, gateway) -> Promotion:
    """An `unpaid` card-checkout hold with session cs_test_<n>."""
    registry = FakeRegistry()
    registry.found("12345678", "Acme OÜ")
    org = await make.organizer()
    event = await make.event(submitted_by=org, promotion_restriction="none")
    started = await start_checkout(
        db,
        gateway,
        registry,
        org,
        CheckoutInput(event.id, d(10), d(14), "12345678", None, True, True),
        NOW,
    )
    return started.promotion


async def post(client, event_id, event_type, obj, **sign_kw):
    payload = stripe_event(event_id, event_type, obj)
    return await client.post(
        "/webhooks/stripe", content=payload, headers={"stripe-signature": sign(payload, **sign_kw)}
    )


async def audit_actions(db, promotion_id) -> list[str]:
    rows = await db.scalars(select(AdminAction).where(AdminAction.target == str(promotion_id)))
    return sorted(r.action for r in rows)


# --- signature -----------------------------------------------------------


@pytest.mark.asyncio
async def test_bad_missing_and_stale_signatures_are_400_and_change_nothing(
    client, db, make, gateway, mails
) -> None:
    promo = await held_promotion(db, make, gateway)
    payload = stripe_event("evt_1", "checkout.session.completed", completed_session("cs_test_1"))
    stale = sign(payload, timestamp=int(time.time()) - 301)
    wrong_secret = sign(payload, secret="whsec_other")
    for headers in ({}, {"stripe-signature": "t=1,v1=abc"}, {"stripe-signature": stale}, {"stripe-signature": wrong_secret}):
        resp = await client.post("/webhooks/stripe", content=payload, headers=headers)
        assert resp.status_code == 400
    # A valid signature over a different body is bad too (raw body is what's signed).
    tampered = await client.post(
        "/webhooks/stripe", content=payload + b" ", headers={"stripe-signature": sign(payload)}
    )
    assert tampered.status_code == 400
    await db.refresh(promo)
    assert promo.status == "unpaid"
    assert (await db.scalar(select(func.count()).select_from(ProcessedStripeEvent))) == 0


@pytest.mark.asyncio
async def test_unset_secret_fails_closed(client, db, make, gateway, monkeypatch) -> None:
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", "")
    resp = await post(client, "evt_1", "checkout.session.completed", completed_session("cs_test_1"))
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_signature_within_tolerance_is_accepted(client, db, make, gateway, mails) -> None:
    promo = await held_promotion(db, make, gateway)
    resp = await post(
        client, "evt_1", "checkout.session.completed", completed_session("cs_test_1"),
        timestamp=int(time.time()) - 290,
    )
    assert resp.status_code == 200
    await db.refresh(promo)
    assert promo.status == "paid"


# --- completed -> paid ---------------------------------------------------


@pytest.mark.asyncio
async def test_completed_marks_paid_with_invoice_snapshot_audit_and_admin_email(
    client, db, make, gateway, mails
) -> None:
    promo = await held_promotion(db, make, gateway)
    resp = await post(client, "evt_1", "checkout.session.completed", completed_session("cs_test_1"))
    assert (resp.status_code, resp.json()) == (200, {"status": "ok"})

    await db.refresh(promo)
    assert promo.status == "paid" and promo.paid_at == NOW
    assert (promo.invoice_reference, promo.invoice_url) == ("ER-0001", "https://invoice.test/in_1")
    assert (promo.stripe_payment_intent_id, promo.stripe_invoice_id) == ("pi_1", "in_1")
    snapshots = (await db.scalars(select(PromotionSnapshot).where(PromotionSnapshot.promotion_id == promo.id))).all()
    assert [s.trigger for s in snapshots] == ["checkout_paid"]
    assert await audit_actions(db, promo.id) == ["promotion_system_paid"]
    assert mails["admin"] == [("Promotion paid by card", promo.id)]
    assert mails["organizer"] == []


@pytest.mark.asyncio
async def test_replay_returns_200_and_changes_nothing(client, db, make, gateway, mails) -> None:
    promo = await held_promotion(db, make, gateway)
    await post(client, "evt_1", "checkout.session.completed", completed_session("cs_test_1"))
    again = await post(client, "evt_1", "checkout.session.completed", completed_session("cs_test_1"))
    assert (again.status_code, again.json()) == (200, {"status": "duplicate"})
    snapshots = await db.scalar(select(func.count()).select_from(PromotionSnapshot).where(PromotionSnapshot.promotion_id == promo.id))
    assert snapshots == 1
    assert len(mails["admin"]) == 1


@pytest.mark.asyncio
async def test_unpaid_payment_status_and_unknown_session_are_ignored(client, db, make, gateway, mails) -> None:
    promo = await held_promotion(db, make, gateway)
    unpaid = await post(client, "evt_1", "checkout.session.completed", completed_session("cs_test_1", payment_status="unpaid"))
    unknown = await post(client, "evt_2", "checkout.session.completed", completed_session("cs_nope"))
    other = await post(client, "evt_3", "customer.created", {"id": "cus_x"})
    assert [r.json()["status"] for r in (unpaid, unknown, other)] == ["ignored"] * 3
    await db.refresh(promo)
    assert promo.status == "unpaid"


# --- expired -> void -----------------------------------------------------


@pytest.mark.asyncio
async def test_expired_voids_quietly(client, db, make, gateway, mails) -> None:
    promo = await held_promotion(db, make, gateway)
    resp = await post(client, "evt_1", "checkout.session.expired", {"id": "cs_test_1"})
    assert resp.status_code == 200
    await db.refresh(promo)
    assert (promo.status, promo.end_reason) == ("void", "checkout_expired")
    assert mails == {"admin": [], "organizer": []}
    assert await audit_actions(db, promo.id) == ["promotion_system_void"]


@pytest.mark.asyncio
async def test_expired_after_completed_is_a_no_op(client, db, make, gateway, mails) -> None:
    promo = await held_promotion(db, make, gateway)
    await post(client, "evt_1", "checkout.session.completed", completed_session("cs_test_1"))
    late_expired = await post(client, "evt_2", "checkout.session.expired", {"id": "cs_test_1"})
    assert late_expired.json() == {"status": "ignored"}
    await db.refresh(promo)
    assert promo.status == "paid"


# --- late payment (#619) -------------------------------------------------


@pytest.mark.asyncio
async def test_completed_after_void_refunds_in_full_and_stays_void(client, db, make, gateway, mails) -> None:
    promo = await held_promotion(db, make, gateway)
    org_email = (await db.get(Organizer, promo.organizer_id)).email
    await post(client, "evt_1", "checkout.session.expired", {"id": "cs_test_1"})
    resp = await post(client, "evt_2", "checkout.session.completed", completed_session("cs_test_1"))
    assert resp.json() == {"status": "ok"}

    await db.refresh(promo)
    assert promo.status == "void"  # never reinstated
    assert promo.paid_at is None
    (refund,) = gateway.refunds
    assert (refund.payment_intent_id, refund.invoice_id) == ("pi_1", "in_1")
    assert (refund.net_cents, refund.vat_cents, refund.tax_rate_id) == (2500, 600, "txr_24")
    assert refund.idempotency_key == f"late-refund-{promo.id}"
    assert promo.refunded_cents == 3100
    assert promo.refund_note == "Automatic full refund: payment arrived after the checkout hold lapsed."
    assert await audit_actions(db, promo.id) == ["promotion_system_late_refund", "promotion_system_void"]
    assert mails["admin"] == [("Late Promotion payment refunded", promo.id)]
    assert [m[0] for m in mails["organizer"]] == [org_email]


@pytest.mark.asyncio
async def test_a_second_late_completed_does_not_refund_twice(client, db, make, gateway, mails) -> None:
    await held_promotion(db, make, gateway)
    await post(client, "evt_1", "checkout.session.expired", {"id": "cs_test_1"})
    await post(client, "evt_2", "checkout.session.completed", completed_session("cs_test_1"))
    again = await post(client, "evt_3", "checkout.session.completed", completed_session("cs_test_1"))
    assert again.json() == {"status": "ignored"}
    assert len(gateway.refunds) == 1


@pytest.mark.asyncio
async def test_refund_failure_is_retried_by_stripe(client, db, make, gateway, mails) -> None:
    promo = await held_promotion(db, make, gateway)
    await post(client, "evt_1", "checkout.session.expired", {"id": "cs_test_1"})
    gateway.fail_refund = True
    with pytest.raises(PaymentProviderError):
        await post(client, "evt_2", "checkout.session.completed", completed_session("cs_test_1"))
    assert (await db.get(ProcessedStripeEvent, "evt_2")) is None  # not recorded, so Stripe retries
    gateway.fail_refund = False
    retry = await post(client, "evt_2", "checkout.session.completed", completed_session("cs_test_1"))
    assert retry.json() == {"status": "ok"}
    await db.refresh(promo)
    assert promo.refunded_cents == 3100


# --- dispute (#619) ------------------------------------------------------


@pytest.mark.asyncio
async def test_dispute_notifies_admin_and_changes_nothing(client, db, make, gateway, mails) -> None:
    promo = await held_promotion(db, make, gateway)
    await post(client, "evt_1", "checkout.session.completed", completed_session("cs_test_1"))
    mails["admin"].clear()
    resp = await post(
        client, "evt_2", "charge.dispute.created",
        {"id": "dp_1", "payment_intent": "pi_1", "reason": "fraudulent", "amount": 3100},
    )
    assert resp.status_code == 200
    assert mails["admin"] == [("Stripe dispute opened", promo.id)]
    await db.refresh(promo)
    assert (promo.status, promo.refunded_cents) == ("paid", 0)
    assert await audit_actions(db, promo.id) == ["promotion_system_paid"]
    assert gateway.refunds == []
