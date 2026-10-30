"""POST /webhooks/stripe (public path /api/webhooks/stripe): Stripe events.

Outside all three auth tracks: the signature over the raw body is the only
credential (5-minute tolerance), so a bad, missing or stale one is a 400 before
any work. See docs/security.md "Stripe Webhook".
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from app.config import settings
from app.constants.log_events import LOG_EVENT_EMAIL_SEND_FAILED, LOG_EVENT_WEBHOOK_REJECTED
from app.constants.promotions import (
    ERROR_STRIPE_SIGNATURE_INVALID,
    ERROR_STRIPE_WEBHOOK_NOT_CONFIGURED,
    STRIPE_WEBHOOK_SIGNATURE_HEADER,
)
from app.constants.rate_limits import RATE_LIMIT_WEBHOOK_STRIPE
from app.db import AsyncSessionLocal
from app.integrations.payments import InvalidWebhookSignature, PaymentGateway
from app.integrations.providers import get_payment_gateway
from app.promotions.stripe_events import process_stripe_event
from app.promotions.windows import now_tallinn
from app.rate_limit import limiter

log = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/stripe", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_WEBHOOK_STRIPE)
async def stripe_webhook(
    request: Request, gateway: PaymentGateway = Depends(get_payment_gateway)
) -> JSONResponse:
    body = await request.body()
    if not settings.STRIPE_WEBHOOK_SECRET:
        log.error("stripe webhook: STRIPE_WEBHOOK_SECRET is not set")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=ERROR_STRIPE_WEBHOOK_NOT_CONFIGURED
        )
    try:
        event = gateway.construct_event(body, request.headers.get(STRIPE_WEBHOOK_SIGNATURE_HEADER))
    except InvalidWebhookSignature:
        log.warning(
            "stripe webhook: invalid or missing signature",
            extra={"event": LOG_EVENT_WEBHOOK_REJECTED},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=ERROR_STRIPE_SIGNATURE_INVALID
        ) from None

    async with AsyncSessionLocal() as db:
        # Any handler error rolls back the event id too, so Stripe's retry runs it again.
        outcome = await process_stripe_event(db, gateway, event, now_tallinn())
        await db.commit()
    for notify in outcome.after_commit:
        try:
            await notify()
        except Exception:
            log.error(
                "stripe webhook: notification failed (event=%s)",
                event.id,
                exc_info=True,
                extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
            )
    return JSONResponse({"status": outcome.status})
