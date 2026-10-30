"""Stripe behind a Protocol: the only module that imports the ``stripe`` SDK.

The SDK is a documented bypass of the shared HTTP client (docs/conventions.md
"HTTP Retry Bypasses"). Everything the Promotions code needs from Stripe is one
method here, so tests swap in ``tests/promotions/fakes.py``'s fake.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

import stripe

from app.config import settings
from app.constants.promotions import (
    PROMOTION_CHECKOUT_CURRENCY,
    STRIPE_CREDIT_NOTE_LINE_DEFAULT,
    STRIPE_CREDIT_NOTE_LINE_MAX_CHARS,
    STRIPE_CREDIT_NOTE_MEMO_MAX_CHARS,
    STRIPE_CREDIT_NOTE_REASON,
    STRIPE_WEBHOOK_TOLERANCE_SECONDS,
)


class PaymentProviderError(Exception):
    """Stripe refused or could not be reached."""


class InvalidWebhookSignature(Exception):
    """The webhook body was not signed by Stripe, or the signature is stale."""


@dataclass(frozen=True)
class StripeEvent:
    id: str
    type: str
    object: dict[str, Any]


@dataclass(frozen=True)
class CustomerRequest:
    email: str
    name: str
    registry_code: str
    organizer_id: int


@dataclass(frozen=True)
class CheckoutSessionRequest:
    customer_id: str
    promotion_id: int
    locale: str
    expires_at: datetime
    net_cents: int
    tax_rate_id: str
    product_name: str
    success_url: str
    cancel_url: str
    invoice_footer: str
    custom_fields: dict[str, str]


@dataclass(frozen=True)
class CheckoutSession:
    id: str
    url: str
    expires_at: datetime


@dataclass(frozen=True)
class InvoiceInfo:
    number: str | None
    hosted_url: str | None


@dataclass(frozen=True)
class RefundRequest:
    """One refund. With an invoice it is a credit note (reversing the VAT) and
    the card refund in a single call; without one it is a plain card refund."""

    payment_intent_id: str
    invoice_id: str | None
    net_cents: int
    vat_cents: int
    tax_rate_id: str
    reason: str
    idempotency_key: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RefundResult:
    refund_id: str | None
    credit_note_id: str | None


class PaymentGateway(Protocol):
    def construct_event(self, payload: bytes, signature: str | None) -> StripeEvent:
        """Verify the signature over the raw body (5-minute tolerance) and parse
        it. Raises ``InvalidWebhookSignature``."""
        ...

    async def create_customer(self, request: CustomerRequest) -> str: ...

    async def update_customer(self, customer_id: str, email: str, name: str) -> None:
        """Set the Customer's billing email and legal name."""
        ...

    async def create_checkout_session(self, request: CheckoutSessionRequest) -> CheckoutSession: ...

    async def retrieve_invoice(self, invoice_id: str) -> InvoiceInfo: ...

    async def refund(self, request: RefundRequest) -> RefundResult: ...


class StripeGateway:
    """The production adapter, on the official SDK's async client."""

    def __init__(self, secret_key: str | None = None, webhook_secret: str | None = None) -> None:
        self._secret_key = settings.STRIPE_SECRET_KEY if secret_key is None else secret_key
        self._webhook_secret = (
            settings.STRIPE_WEBHOOK_SECRET if webhook_secret is None else webhook_secret
        )
        self._stripe_client: stripe.StripeClient | None = None

    def _client(self) -> stripe.StripeClient:
        if not self._secret_key:
            raise PaymentProviderError("Stripe is not configured")
        if self._stripe_client is None:
            self._stripe_client = stripe.StripeClient(self._secret_key)
        return self._stripe_client

    def construct_event(self, payload: bytes, signature: str | None) -> StripeEvent:
        if not self._webhook_secret or not signature:
            raise InvalidWebhookSignature("missing secret or signature")
        try:
            stripe.WebhookSignature.verify_header(
                payload.decode("utf-8"), signature, self._webhook_secret, STRIPE_WEBHOOK_TOLERANCE_SECONDS
            )
            body = json.loads(payload)
            return StripeEvent(
                id=str(body["id"]), type=str(body["type"]), object=dict(body["data"]["object"])
            )
        except (stripe.SignatureVerificationError, ValueError, KeyError, TypeError) as exc:
            raise InvalidWebhookSignature(str(exc)) from exc

    async def create_customer(self, request: CustomerRequest) -> str:
        try:
            customer = await self._client().v1.customers.create_async(
                params={
                    "email": request.email,
                    "name": request.name,
                    "metadata": {
                        "registry_code": request.registry_code,
                        "organizer_id": str(request.organizer_id),
                    },
                }
            )
        except stripe.StripeError as exc:
            raise PaymentProviderError(str(exc)) from exc
        return str(customer.id)

    async def update_customer(self, customer_id: str, email: str, name: str) -> None:
        try:
            await self._client().v1.customers.update_async(
                customer_id, params={"email": email, "name": name}
            )
        except stripe.StripeError as exc:
            raise PaymentProviderError(str(exc)) from exc

    async def create_checkout_session(self, request: CheckoutSessionRequest) -> CheckoutSession:
        params: dict[str, Any] = {
            "mode": "payment",
            "customer": request.customer_id,
            "locale": request.locale,
            "expires_at": int(request.expires_at.timestamp()),
            "client_reference_id": str(request.promotion_id),
            "metadata": {"promotion_id": str(request.promotion_id)},
            "success_url": request.success_url,
            "cancel_url": request.cancel_url,
            "line_items": [
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": PROMOTION_CHECKOUT_CURRENCY,
                        "unit_amount": request.net_cents,
                        "product_data": {"name": request.product_name},
                    },
                    "tax_rates": [request.tax_rate_id],
                }
            ],
            "invoice_creation": {
                "enabled": True,
                "invoice_data": {
                    "footer": request.invoice_footer,
                    "custom_fields": [
                        {"name": label, "value": value}
                        for label, value in request.custom_fields.items()
                    ],
                    "metadata": {"promotion_id": str(request.promotion_id)},
                },
            },
        }
        try:
            session = await self._client().v1.checkout.sessions.create_async(params=params)  # type: ignore[arg-type]
        except stripe.StripeError as exc:
            raise PaymentProviderError(str(exc)) from exc
        if not session.url:
            raise PaymentProviderError("Stripe returned a session without a URL")
        return CheckoutSession(
            id=str(session.id),
            url=str(session.url),
            expires_at=datetime.fromtimestamp(session.expires_at, tz=timezone.utc),
        )

    async def retrieve_invoice(self, invoice_id: str) -> InvoiceInfo:
        try:
            invoice = await self._client().v1.invoices.retrieve_async(invoice_id)
        except stripe.StripeError as exc:
            raise PaymentProviderError(str(exc)) from exc
        return InvoiceInfo(number=invoice.number, hosted_url=invoice.hosted_invoice_url)

    async def refund(self, request: RefundRequest) -> RefundResult:
        client = self._client()
        options: Any = {"idempotency_key": request.idempotency_key}
        try:
            if request.invoice_id is not None:
                note = await client.v1.credit_notes.create_async(
                    params={
                        "invoice": request.invoice_id,
                        "reason": STRIPE_CREDIT_NOTE_REASON,
                        "memo": request.reason[:STRIPE_CREDIT_NOTE_MEMO_MAX_CHARS],
                        "metadata": request.metadata,
                        "lines": [
                            {
                                "type": "custom_line_item",
                                "description": request.reason[:STRIPE_CREDIT_NOTE_LINE_MAX_CHARS] or STRIPE_CREDIT_NOTE_LINE_DEFAULT,
                                "quantity": 1,
                                "unit_amount": request.net_cents,
                                "tax_rates": [request.tax_rate_id],
                            }
                        ],
                        "refund_amount": request.net_cents + request.vat_cents,
                    },
                    options=options,
                )
                refunds = await client.v1.refunds.list_async(
                    params={"payment_intent": request.payment_intent_id, "limit": 1}
                )
                refund_id = refunds.data[0].id if refunds.data else None
                return RefundResult(refund_id=refund_id, credit_note_id=str(note.id))
            refund = await client.v1.refunds.create_async(
                params={
                    "payment_intent": request.payment_intent_id,
                    "amount": request.net_cents + request.vat_cents,
                    "metadata": request.metadata,
                },
                options=options,
            )
        except stripe.StripeError as exc:
            raise PaymentProviderError(str(exc)) from exc
        return RefundResult(refund_id=str(refund.id), credit_note_id=None)
