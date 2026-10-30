"""Card checkout start (#618): recheck, hold the days, open a Stripe session.

Three short transactions, never one long one: (1) recheck everything and insert
the `unpaid` Promotion under the cap lock, which holds its days; (2) find or
create the Stripe Customer for (Organizer, registry code), updating a reused one
to this checkout's billing email and legal name; (3) open the session
and store its id. The Stripe calls run outside the cap lock. If Stripe fails
the hold is voided at once, and a crash in between leaves a hold the expiry
sweep voids an hour after its expiry. The caller's session is committed here.
"""

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app._generated.shared_constants import (
    PROMOTION_CHECKOUT_PATH_SUCCESS,
    PROMOTION_CHECKOUT_SESSION_MINUTES,
    PROMOTION_ERROR_BUSINESS_ATTESTATION,
    PROMOTION_ERROR_CHECKOUT_ATTESTATION,
    PROMOTION_ERROR_CHECKOUT_NEEDS_REVIEW,
    PROMOTION_ERROR_CHECKOUT_NOT_PROMOTABLE,
    PROMOTION_ERROR_CHECKOUT_PROVIDER,
    PROMOTION_ERROR_CHECKOUT_TERMS,
    PROMOTION_INVOICE_SOURCE_STRIPE,
    PROMOTION_VAT_RATE_PERCENT,
)
from app.constants.promotions import (
    PROMOTION_CHECKOUT_ERROR_MESSAGES,
    PROMOTION_CHECKOUT_EXPIRY_MARGIN_SECONDS,
    PROMOTION_CHECKOUT_PATH_CANCEL,
    PROMOTION_CONTENT_POLICY_VERSION,
    PROMOTION_END_REASON_CHECKOUT_FAILED,
    PROMOTION_ERROR_CHECKOUT_NOT_OWNER,
    PROMOTION_ORGANIZER_TERMS_VERSION,
    PROMOTION_RESTRICTION_NONE,
    PROMOTION_STATUS_UNPAID,
    PROMOTION_STATUS_VOID,
    STRIPE_CUSTOM_FIELD_LABELS,
    STRIPE_CUSTOM_FIELD_VALUE_MAX_CHARS,
    STRIPE_PRODUCT_NAME_TEMPLATE,
)
from app.events.localize import resolve_title
from app.events.queries import canonical_event_filter, event_not_ended_filter, public_event_filter
from app.integrations.payments import (
    CheckoutSessionRequest,
    CustomerRequest,
    PaymentGateway,
    PaymentProviderError,
)
from app.integrations.registry import RegistryLookup
from app.models.models import Event, Organizer, Promotion, StripeCustomer
from app.promotions.cap import lock_cap
from app.promotions.grant import PromotionRefused, net_price_cents, validate_grant
from app.promotions.owners import resolve_owner_ids
from app.promotions.registry_check import verified_legal_name
from app.promotions.windows import window_days

log = logging.getLogger(__name__)


def _clock() -> datetime:
    """A fresh read of the clock, for the session expiry (tests pin it)."""
    return datetime.now(timezone.utc)


class CheckoutRefused(Exception):
    """A checkout precondition failed; nothing was held."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code

    @property
    def message(self) -> str:
        return PROMOTION_CHECKOUT_ERROR_MESSAGES[self.code]


@dataclass(frozen=True)
class CheckoutInput:
    event_id: int
    start_date: date
    end_date: date
    registry_code: str
    billing_email: str | None
    content_policy_attested: bool
    business_attested: bool
    terms_accepted: bool


@dataclass(frozen=True)
class CheckoutStarted:
    promotion: Promotion
    checkout_url: str


async def _promotable(db: AsyncSession, event: Event, now: datetime) -> bool:
    row = (
        await db.execute(
            select(
                public_event_filter(), canonical_event_filter(), event_not_ended_filter(now)
            ).where(Event.id == event.id)
        )
    ).one_or_none()
    return row is not None and all(bool(flag) for flag in row)


async def _stripe_customer(
    db: AsyncSession,
    gateway: PaymentGateway,
    organizer: Organizer,
    registry_code: str,
    legal_name: str,
    email: str,
) -> str:
    existing = (
        await db.execute(
            select(StripeCustomer).where(
                StripeCustomer.organizer_id == organizer.id,
                StripeCustomer.registry_code == registry_code,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        # This checkout's billing email and the register's current name win,
        # so the invoice goes to the address the Organizer just gave. Stripe
        # is called only when they differ from what we last sent.
        if (existing.billing_email, existing.legal_name) != (email, legal_name):
            await gateway.update_customer(existing.stripe_customer_id, email, legal_name)
            existing.billing_email = email
            existing.legal_name = legal_name
        return existing.stripe_customer_id
    created = await gateway.create_customer(
        CustomerRequest(
            email=email, name=legal_name, registry_code=registry_code, organizer_id=organizer.id
        )
    )
    # A concurrent first checkout may have won; its row is the one to reuse.
    await db.execute(
        pg_insert(StripeCustomer)
        .values(
            organizer_id=organizer.id,
            registry_code=registry_code,
            stripe_customer_id=created,
            billing_email=email,
            legal_name=legal_name,
        )
        .on_conflict_do_nothing(constraint="uq_stripe_customers_organizer_code")
    )
    winner = await db.scalar(
        select(StripeCustomer.stripe_customer_id).where(
            StripeCustomer.organizer_id == organizer.id,
            StripeCustomer.registry_code == registry_code,
        )
    )
    return winner or created


async def _void_failed_hold(db: AsyncSession, promotion_id: int, now: datetime) -> None:
    await db.rollback()
    promotion = await db.get(Promotion, promotion_id, populate_existing=True)
    if promotion is not None and promotion.status == PROMOTION_STATUS_UNPAID:
        promotion.status = PROMOTION_STATUS_VOID
        promotion.ended_at = now
        promotion.end_reason = PROMOTION_END_REASON_CHECKOUT_FAILED
        promotion.updated_at = now
    await db.commit()


async def start_checkout(
    db: AsyncSession,
    gateway: PaymentGateway,
    registry: RegistryLookup,
    organizer: Organizer,
    data: CheckoutInput,
    now: datetime,
) -> CheckoutStarted:
    """Hold the days and open a Stripe Checkout session.

    Raises `CheckoutRefused` / `RegistryRefused` for a failed precondition and
    `PromotionRefused` for a window or cap rule; nothing is held then."""
    event = await db.get(Event, data.event_id)
    if event is None:
        raise CheckoutRefused(PROMOTION_ERROR_CHECKOUT_NOT_PROMOTABLE)
    if (await resolve_owner_ids(db, [event])).get(event.id) != organizer.id:
        raise CheckoutRefused(PROMOTION_ERROR_CHECKOUT_NOT_OWNER)
    if event.promotion_restriction != PROMOTION_RESTRICTION_NONE:
        raise CheckoutRefused(PROMOTION_ERROR_CHECKOUT_NEEDS_REVIEW)
    if not await _promotable(db, event, now):
        raise CheckoutRefused(PROMOTION_ERROR_CHECKOUT_NOT_PROMOTABLE)
    if not data.content_policy_attested:
        raise CheckoutRefused(PROMOTION_ERROR_CHECKOUT_ATTESTATION)
    if not data.business_attested:
        raise CheckoutRefused(PROMOTION_ERROR_BUSINESS_ATTESTATION)
    if not data.terms_accepted:
        raise CheckoutRefused(PROMOTION_ERROR_CHECKOUT_TERMS)
    registry_code = data.registry_code.strip()
    legal_name = await verified_legal_name(registry, registry_code)
    billing_email = (data.billing_email or "").strip() or organizer.email
    title = resolve_title(event, organizer.locale)

    # (1) Recheck under the cap lock and hold the days.
    await lock_cap(db)
    violations = await validate_grant(db, event, data.start_date, data.end_date, now)
    if violations:
        await db.rollback()
        raise PromotionRefused(violations)
    days = window_days(data.start_date, data.end_date)
    promotion = Promotion(
        event_id=event.id,
        organizer_id=organizer.id,
        status=PROMOTION_STATUS_UNPAID,
        start_date=data.start_date,
        end_date=data.end_date,
        days=days,
        net_price_cents=net_price_cents(days, False),
        vat_rate_percent=PROMOTION_VAT_RATE_PERCENT,
        is_complimentary=False,
        invoice_source=PROMOTION_INVOICE_SOURCE_STRIPE,
        advertiser_legal_name=legal_name,
        advertiser_registry_code=registry_code,
        billing_email=billing_email,
        checkout_expires_at=now + timedelta(minutes=PROMOTION_CHECKOUT_SESSION_MINUTES),
        content_policy_attested_at=now,
        content_policy_version=PROMOTION_CONTENT_POLICY_VERSION,
        business_attested_at=now,
        terms_accepted_at=now,
        terms_version=PROMOTION_ORGANIZER_TERMS_VERSION,
    )
    db.add(promotion)
    await db.flush()
    promotion_id = promotion.id
    net_cents = promotion.net_price_cents
    await db.commit()  # releases the cap lock; the hold is now visible to others

    # (2) + (3) Stripe, outside the lock.
    try:
        customer_id = await _stripe_customer(
            db, gateway, organizer, registry_code, legal_name, billing_email
        )
        await db.commit()
        expires_at = _clock() + timedelta(
            minutes=PROMOTION_CHECKOUT_SESSION_MINUTES,
            seconds=PROMOTION_CHECKOUT_EXPIRY_MARGIN_SECONDS,
        )
        session = await gateway.create_checkout_session(
            CheckoutSessionRequest(
                customer_id=customer_id,
                promotion_id=promotion_id,
                locale=organizer.locale,
                expires_at=expires_at,
                net_cents=net_cents,
                tax_rate_id=settings.STRIPE_TAX_RATE_ID,
                product_name=STRIPE_PRODUCT_NAME_TEMPLATE.format(
                    title=title, start=data.start_date.isoformat(), end=data.end_date.isoformat()
                ),
                success_url=(
                    f"{settings.FRONTEND_URL}{PROMOTION_CHECKOUT_PATH_SUCCESS}"
                    f"?promotion_id={promotion_id}"
                ),
                cancel_url=f"{settings.FRONTEND_URL}{PROMOTION_CHECKOUT_PATH_CANCEL}",
                invoice_footer=settings.PROMOTIONS_INVOICE_FOOTER,
                custom_fields={
                    STRIPE_CUSTOM_FIELD_LABELS["registry_code"]: registry_code,
                    STRIPE_CUSTOM_FIELD_LABELS["event"]: title[:STRIPE_CUSTOM_FIELD_VALUE_MAX_CHARS],
                    STRIPE_CUSTOM_FIELD_LABELS["window"]: (
                        f"{data.start_date.isoformat()} to {data.end_date.isoformat()}"
                    ),
                },
            )
        )
    except PaymentProviderError:
        log.error("Stripe checkout could not be opened (promotion_id=%s)", promotion_id, exc_info=True)
        await _void_failed_hold(db, promotion_id, now)
        raise CheckoutRefused(PROMOTION_ERROR_CHECKOUT_PROVIDER) from None

    held = await db.get(Promotion, promotion_id, populate_existing=True)
    assert held is not None
    held.stripe_customer_id = customer_id
    held.stripe_checkout_session_id = session.id
    held.checkout_expires_at = session.expires_at
    held.updated_at = now
    await db.commit()
    return CheckoutStarted(promotion=held, checkout_url=session.url)
