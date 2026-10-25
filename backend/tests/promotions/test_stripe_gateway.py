from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.integrations.payments import CheckoutSessionRequest, StripeGateway


@pytest.mark.asyncio
async def test_checkout_session_leaves_payment_methods_to_the_dashboard() -> None:
    create = AsyncMock(
        return_value=SimpleNamespace(id="cs_1", url="https://stripe.test/cs_1", expires_at=1_800_000_000)
    )
    client = MagicMock()
    client.v1.checkout.sessions.create_async = create
    gateway = StripeGateway(secret_key="sk_test_x", webhook_secret="whsec_x")
    gateway._stripe_client = client

    await gateway.create_checkout_session(
        CheckoutSessionRequest(
            customer_id="cus_1",
            promotion_id=1,
            locale="en",
            expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
            net_cents=1000,
            tax_rate_id="txr_1",
            product_name="Promotion",
            success_url="https://x.test/ok",
            cancel_url="https://x.test/no",
            invoice_footer="VAT",
            custom_fields={},
        )
    )

    assert "payment_method_types" not in create.call_args.kwargs["params"]
