"""Card checkout start (#618): the recheck, the hold, the Stripe customer and
session. Real Postgres; the registry and Stripe are the fakes."""

from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.auth.dependencies import get_current_organizer
from app.config import settings
from app.constants.promotions import PROMOTION_LIVE_CAP
from app.db import get_db
from app.integrations.providers import get_payment_gateway, get_registry_lookup
from app.models.models import Organizer, Promotion, StripeCustomer
from app.promotions.checkout import CheckoutInput, CheckoutRefused, start_checkout
from app.promotions.grant import GrantRequest, PromotionRefused, grant_promotion
from app.routers import organizer_promotion_checkout as checkout_router
from tests.promotions.conftest import NOW, d
from tests.promotions.fakes import FakeRegistry


@pytest.fixture
def registry() -> FakeRegistry:
    fake = FakeRegistry()
    fake.found("12345678", "Acme Events OÜ")
    return fake


@pytest.fixture(autouse=True)
def stripe_settings(monkeypatch):
    monkeypatch.setattr(settings, "STRIPE_TAX_RATE_ID", "txr_24")
    monkeypatch.setattr(settings, "PROMOTIONS_INVOICE_FOOTER", "Operator OÜ, VAT EE123456789")


def data(event, **overrides):
    values = dict(
        event_id=event.id,
        start_date=d(10),
        end_date=d(14),
        registry_code="12345678",
        billing_email=None,
        content_policy_attested=True,
        business_attested=True,
        terms_accepted=True,
    )
    values.update(overrides)
    return CheckoutInput(**values)


async def clear_event(make, org, **kw):
    return await make.event(submitted_by=org, promotion_restriction="none", **kw)


@pytest.mark.asyncio
async def test_checkout_holds_the_days_and_opens_one_net_line_session(
    db, make, gateway, registry
) -> None:
    org = await make.organizer()
    org.locale = "ru"
    event = await clear_event(make, org)
    started = await start_checkout(db, gateway, registry, org, data(event), NOW)

    promo = started.promotion
    assert (promo.status, promo.days, promo.net_price_cents) == ("unpaid", 5, 2500)
    assert promo.vat_rate_percent == Decimal("24.00")
    assert (promo.advertiser_legal_name, promo.advertiser_registry_code) == (
        "Acme Events OÜ",
        "12345678",
    )
    assert promo.billing_email == org.email
    assert promo.invoice_source == "stripe"
    assert (promo.content_policy_version, promo.terms_version) == ("1", "1")
    assert promo.content_policy_attested_at == NOW and promo.terms_accepted_at == NOW
    assert promo.business_attested_at == NOW
    assert promo.stripe_checkout_session_id == "cs_test_1"
    assert started.checkout_url == "https://checkout.stripe.test/1"

    (session,) = gateway.sessions
    assert session.net_cents == 2500
    assert session.tax_rate_id == "txr_24"
    assert session.locale == "ru"
    assert session.invoice_footer == "Operator OÜ, VAT EE123456789"
    assert session.custom_fields == {
        "Registry code": "12345678",
        "Event": event.title_orig,
        "Promotion window": "2090-01-10 to 2090-01-14",
    }
    # 30 minutes (plus the small margin Stripe's minimum needs).
    assert 30 * 60 <= (session.expires_at - NOW).total_seconds() <= 32 * 60


@pytest.mark.asyncio
async def test_customer_is_reused_per_organizer_and_registry_code(
    db, make, gateway, registry
) -> None:
    org = await make.organizer()
    registry.found("87654321", "Other OÜ")
    first = await clear_event(make, org)
    second = await clear_event(make, org)
    third = await clear_event(make, org)
    await start_checkout(db, gateway, registry, org, data(first), NOW)
    await start_checkout(db, gateway, registry, org, data(second), NOW)
    await start_checkout(db, gateway, registry, org, data(third, registry_code="87654321"), NOW)

    assert len(gateway.customers) == 2  # one per (Organizer, registry code)
    assert [s.customer_id for s in gateway.sessions] == ["cus_1", "cus_1", "cus_2"]
    rows = (await db.scalars(select(StripeCustomer).where(StripeCustomer.organizer_id == org.id))).all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_repeat_checkout_updates_the_customer_only_when_details_change(
    db, make, gateway, registry
) -> None:
    org = await make.organizer()
    events = [await clear_event(make, org) for _ in range(4)]
    await start_checkout(db, gateway, registry, org, data(events[0]), NOW)
    await start_checkout(db, gateway, registry, org, data(events[1]), NOW)
    assert gateway.customer_updates == []  # same details: no call

    registry.found("12345678", "Renamed OÜ")
    await start_checkout(db, gateway, registry, org, data(events[2]), NOW)
    assert gateway.customer_updates == [("cus_1", org.email, "Renamed OÜ")]

    await start_checkout(db, gateway, registry, org, data(events[3]), NOW)
    assert len(gateway.customer_updates) == 1  # the new details are stored
    row = await db.scalar(select(StripeCustomer).where(StripeCustomer.organizer_id == org.id))
    assert (row.billing_email, row.legal_name) == (org.email, "Renamed OÜ")


@pytest.mark.asyncio
async def test_customer_row_without_stored_details_is_updated_once(
    db, make, gateway, registry
) -> None:
    org = await make.organizer()
    first = await clear_event(make, org)
    second = await clear_event(make, org)
    await start_checkout(db, gateway, registry, org, data(first), NOW)
    row = await db.scalar(select(StripeCustomer).where(StripeCustomer.organizer_id == org.id))
    row.billing_email = row.legal_name = None  # a row from before the columns existed
    await db.commit()

    await start_checkout(db, gateway, registry, org, data(second), NOW)
    assert len(gateway.customer_updates) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "restriction,code",
    [(None, "event_needs_review"), ("alcohol", "event_needs_review")],
)
async def test_unassessed_or_restricted_event_goes_to_review(
    db, make, gateway, registry, restriction, code
) -> None:
    org = await make.organizer()
    event = await make.event(submitted_by=org, promotion_restriction=restriction)
    with pytest.raises(CheckoutRefused) as exc:
        await start_checkout(db, gateway, registry, org, data(event), NOW)
    assert exc.value.code == code
    assert gateway.sessions == []


@pytest.mark.asyncio
async def test_only_the_owner_can_check_out(db, make, gateway, registry) -> None:
    owner, stranger = await make.organizer(), await make.organizer()
    event = await clear_event(make, owner)
    with pytest.raises(CheckoutRefused) as exc:
        await start_checkout(db, gateway, registry, stranger, data(event), NOW)
    assert exc.value.code == "not_event_owner"


@pytest.mark.asyncio
async def test_unpublished_event_is_not_promotable(db, make, gateway, registry) -> None:
    org = await make.organizer()
    event = await clear_event(make, org, status="draft")
    with pytest.raises(CheckoutRefused) as exc:
        await start_checkout(db, gateway, registry, org, data(event), NOW)
    assert exc.value.code == "event_not_promotable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides,code",
    [
        ({"content_policy_attested": False}, "content_policy_attestation_required"),
        ({"business_attested": False}, "business_attestation_required"),
        ({"terms_accepted": False}, "organizer_terms_required"),
    ],
)
async def test_attestation_and_terms_are_required(
    db, make, gateway, registry, overrides, code
) -> None:
    org = await make.organizer()
    event = await clear_event(make, org)
    with pytest.raises(CheckoutRefused) as exc:
        await start_checkout(db, gateway, registry, org, data(event, **overrides), NOW)
    assert exc.value.code == code


@pytest.mark.asyncio
async def test_window_rules_are_rechecked(db, make, gateway, registry) -> None:
    org = await make.organizer()
    event = await clear_event(make, org)
    with pytest.raises(PromotionRefused) as exc:
        await start_checkout(db, gateway, registry, org, data(event, end_date=d(11)), NOW)
    assert [v.code for v in exc.value.violations] == ["window_too_short"]
    assert gateway.sessions == []


@pytest.mark.asyncio
async def test_a_full_cap_day_is_refused_without_a_hold(db, make, gateway, registry) -> None:
    for _ in range(PROMOTION_LIVE_CAP):
        other = await make.organizer()
        ev = await make.event(submitted_by=other)
        await grant_promotion(db, ev, GrantRequest(d(12), d(14), "Acme OÜ", "12345678"), NOW)
    org = await make.organizer()
    event = await clear_event(make, org)
    with pytest.raises(PromotionRefused) as exc:
        await start_checkout(db, gateway, registry, org, data(event), NOW)
    assert "cap_exceeded" in [v.code for v in exc.value.violations]
    held = (await db.scalars(select(Promotion).where(Promotion.event_id == event.id))).all()
    assert held == []


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["deleted", "not_found", "outage"])
async def test_registry_failure_blocks_checkout_before_any_hold(
    db, make, gateway, registry, fault
) -> None:
    from app.promotions.registry_check import RegistryRefused

    org = await make.organizer()
    event = await clear_event(make, org)
    registry.deleted("12345678", "Gone OÜ") if fault == "deleted" else None
    if fault == "not_found":
        registry.answers.clear()
    registry.outage = fault == "outage"
    with pytest.raises(RegistryRefused):
        await start_checkout(db, gateway, registry, org, data(event), NOW)
    assert gateway.customers == []
    assert (await db.scalars(select(Promotion).where(Promotion.event_id == event.id))).all() == []


@pytest.mark.asyncio
async def test_stripe_failure_voids_the_hold_at_once(db, make, gateway, registry) -> None:
    org = await make.organizer()
    event = await clear_event(make, org)
    gateway.fail_session = True
    with pytest.raises(CheckoutRefused) as exc:
        await start_checkout(db, gateway, registry, org, data(event), NOW)
    assert exc.value.code == "checkout_unavailable"
    (promo,) = (await db.scalars(select(Promotion).where(Promotion.event_id == event.id))).all()
    assert (promo.status, promo.end_reason) == ("void", "checkout_failed")


# --- HTTP layer ----------------------------------------------------------


@pytest_asyncio.fixture
async def api(db, make, gateway, registry, monkeypatch):
    org = await make.organizer()
    org_id = org.id
    await db.commit()
    monkeypatch.setattr(checkout_router, "now_tallinn", lambda: NOW)

    async def current_organizer() -> Organizer:
        # Reload per request, as the real dependency does: a refused checkout
        # rolls the shared test session back and expires everything in it.
        loaded = await db.get(Organizer, org_id, populate_existing=True)
        assert loaded is not None
        return loaded

    app = FastAPI()
    app.include_router(checkout_router.router)
    app.dependency_overrides[get_current_organizer] = current_organizer
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_payment_gateway] = lambda: gateway
    app.dependency_overrides[get_registry_lookup] = lambda: registry
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, org


def body(event, **overrides):
    values = {
        "event_id": event.id,
        "start_date": "2090-01-10",
        "end_date": "2090-01-14",
        "registry_code": "12345678",
        "content_policy_attested": True,
        "business_attested": True,
        "terms_accepted": True,
    }
    values.update(overrides)
    return values


@pytest.mark.asyncio
async def test_endpoints_are_404_while_flags_are_off(api, make, monkeypatch) -> None:
    client, org = api
    event = await clear_event(make, org)
    monkeypatch.setattr(settings, "PROMOTIONS_OFFER_ENABLED", False)
    monkeypatch.setattr(settings, "PROMOTIONS_CHECKOUT_ENABLED", True)
    assert (await client.post("/organizer/promotions/registry-lookup", json={"registry_code": "12345678"})).status_code == 404
    assert (await client.post("/organizer/promotions/checkout", json=body(event))).status_code == 404
    # Checkout is effective only while the offer flag is on, and needs its own flag.
    monkeypatch.setattr(settings, "PROMOTIONS_OFFER_ENABLED", True)
    monkeypatch.setattr(settings, "PROMOTIONS_CHECKOUT_ENABLED", False)
    assert (await client.post("/organizer/promotions/checkout", json=body(event))).status_code == 404
    assert (await client.post("/organizer/promotions/registry-lookup", json={"registry_code": "12345678"})).status_code == 200


@pytest.mark.asyncio
async def test_registry_lookup_endpoint_returns_name_or_coded_refusal(api, registry, monkeypatch) -> None:
    client, _ = api
    monkeypatch.setattr(settings, "PROMOTIONS_OFFER_ENABLED", True)
    registry.deleted("22222222", "Gone OÜ")
    ok = await client.post("/organizer/promotions/registry-lookup", json={"registry_code": "12345678"})
    assert ok.json() == {"registry_code": "12345678", "legal_name": "Acme Events OÜ"}
    for code, status, expected in [
        ("22222222", 422, "registry_company_deleted"),
        ("99999999", 422, "registry_company_not_found"),
        ("12", 422, "registry_invalid_code"),
    ]:
        resp = await client.post("/organizer/promotions/registry-lookup", json={"registry_code": code})
        assert (resp.status_code, resp.json()["detail"]["code"]) == (status, expected)
    registry.outage = True
    down = await client.post("/organizer/promotions/registry-lookup", json={"registry_code": "12345678"})
    assert (down.status_code, down.json()["detail"]["code"]) == (503, "registry_unavailable")


@pytest.mark.asyncio
async def test_checkout_endpoint_returns_the_redirect(api, make, monkeypatch) -> None:
    client, org = api
    monkeypatch.setattr(settings, "PROMOTIONS_OFFER_ENABLED", True)
    monkeypatch.setattr(settings, "PROMOTIONS_CHECKOUT_ENABLED", True)
    event = await clear_event(make, org)
    resp = await client.post("/organizer/promotions/checkout", json=body(event))
    assert resp.status_code == 201
    payload = resp.json()
    assert payload["checkout_url"] == "https://checkout.stripe.test/1"
    assert payload["promotion_id"] and payload["expires_at"]


@pytest.mark.asyncio
async def test_checkout_endpoint_refusal_statuses(api, db, make, monkeypatch) -> None:
    client, org = api
    monkeypatch.setattr(settings, "PROMOTIONS_OFFER_ENABLED", True)
    monkeypatch.setattr(settings, "PROMOTIONS_CHECKOUT_ENABLED", True)
    unreviewed = await make.event(submitted_by=org)
    await db.commit()
    resp = await client.post("/organizer/promotions/checkout", json=body(unreviewed))
    assert (resp.status_code, resp.json()["detail"]["code"]) == (409, "event_needs_review")
    clear = await clear_event(make, org)
    await db.commit()  # a refused checkout rolls the shared session back to here
    short_body = body(clear, end_date="2090-01-11")
    bad_body = body(clear, content_policy_attested=False)
    short = await client.post("/organizer/promotions/checkout", json=short_body)
    assert (short.status_code, short.json()["detail"]["code"]) == (422, "window_too_short")
    bad = await client.post("/organizer/promotions/checkout", json=bad_body)
    assert (bad.status_code, bad.json()["detail"]["code"]) == (422, "content_policy_attestation_required")
