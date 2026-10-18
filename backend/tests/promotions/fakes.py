"""Test fakes for the two outbound adapters (the only new seam, #617/#618)."""

import hashlib
import hmac
import json
import time
from typing import Any

from app.integrations.payments import (
    CheckoutSession,
    CheckoutSessionRequest,
    CustomerRequest,
    InvoiceInfo,
    PaymentProviderError,
    RefundRequest,
    RefundResult,
    StripeEvent,
    StripeGateway,
)
from app.integrations.registry import RegistryResult, RegistryUnavailable

WEBHOOK_SECRET = "whsec_test_secret"


class FakeRegistry:
    """Scripts the register: found, deleted, not found, or an outage."""

    def __init__(self) -> None:
        self.answers: dict[str, RegistryResult] = {}
        self.outage = False
        self.calls: list[str] = []

    def found(self, code: str, name: str) -> None:
        self.answers[code] = RegistryResult("found", code, name)

    def deleted(self, code: str, name: str) -> None:
        self.answers[code] = RegistryResult("deleted", code, name)

    async def lookup(self, registry_code: str) -> RegistryResult:
        self.calls.append(registry_code)
        if self.outage:
            raise RegistryUnavailable("scripted outage")
        return self.answers.get(registry_code, RegistryResult("not_found", registry_code))


class FakePaymentGateway:
    """Records every call; signature checks use the real SDK verification."""

    def __init__(self) -> None:
        self.customers: list[CustomerRequest] = []
        self.sessions: list[CheckoutSessionRequest] = []
        self.refunds: list[RefundRequest] = []
        self.customer_updates: list[tuple[str, str, str]] = []
        self.invoices: dict[str, InvoiceInfo] = {}
        self.fail_session = False
        self.fail_refund = False
        self._real = StripeGateway(secret_key="", webhook_secret=WEBHOOK_SECRET)

    def construct_event(self, payload: bytes, signature: str | None) -> StripeEvent:
        return self._real.construct_event(payload, signature)

    async def create_customer(self, request: CustomerRequest) -> str:
        self.customers.append(request)
        return f"cus_{len(self.customers)}"

    async def update_customer(self, customer_id: str, email: str, name: str) -> None:
        self.customer_updates.append((customer_id, email, name))

    async def create_checkout_session(self, request: CheckoutSessionRequest) -> CheckoutSession:
        if self.fail_session:
            raise PaymentProviderError("scripted failure")
        self.sessions.append(request)
        n = len(self.sessions)
        return CheckoutSession(
            id=f"cs_test_{n}", url=f"https://checkout.stripe.test/{n}", expires_at=request.expires_at
        )

    async def retrieve_invoice(self, invoice_id: str) -> InvoiceInfo:
        return self.invoices.get(invoice_id, InvoiceInfo("ER-0001", f"https://invoice.test/{invoice_id}"))

    async def refund(self, request: RefundRequest) -> RefundResult:
        if self.fail_refund:
            raise PaymentProviderError("scripted failure")
        self.refunds.append(request)
        return RefundResult(
            refund_id=f"re_{len(self.refunds)}",
            credit_note_id=f"cn_{len(self.refunds)}" if request.invoice_id else None,
        )


def stripe_event(event_id: str, event_type: str, obj: dict[str, Any]) -> bytes:
    return json.dumps(
        {"id": event_id, "type": event_type, "data": {"object": obj}}, separators=(",", ":")
    ).encode()


def sign(payload: bytes, *, secret: str = WEBHOOK_SECRET, timestamp: int | None = None) -> str:
    ts = int(time.time()) if timestamp is None else timestamp
    digest = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


def completed_session(session_id: str, **overrides: Any) -> dict[str, Any]:
    return {
        "id": session_id,
        "payment_status": "paid",
        "payment_intent": "pi_1",
        "invoice": "in_1",
        **overrides,
    }

