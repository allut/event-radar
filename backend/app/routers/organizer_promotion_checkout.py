"""Organizer-side Promotion card checkout (#617, #618): the Äriregister lookup
and the checkout start. Both are 404 while the offer flag is off (checkout also
while its own flag is off), so the feature does not exist until launch.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_organizer
from app._generated.shared_constants import (
    PROMOTION_ERROR_CHECKOUT_NEEDS_REVIEW,
    PROMOTION_ERROR_CHECKOUT_NOT_PROMOTABLE,
    PROMOTION_ERROR_CHECKOUT_PROVIDER,
    PROMOTION_ERROR_REGISTRY_UNAVAILABLE,
)
from app.constants.promotions import (
    PROMOTION_BILLING_EMAIL_MAX_CHARS,
    PROMOTION_CHECKOUT_ERROR_MESSAGES,
    PROMOTION_CONFLICT_ERROR_CODES,
    PROMOTION_ERROR_CHECKOUT_NOT_OWNER,
    PROMOTION_ERROR_OFFER_DISABLED,
    PROMOTION_REGISTRY_CODE_MAX_LEN,
)
from app.constants.rate_limits import (
    RATE_LIMIT_PROMOTION_CHECKOUT,
    RATE_LIMIT_PROMOTION_REGISTRY_LOOKUP,
)
from app.db import get_db
from app.integrations.payments import PaymentGateway
from app.integrations.providers import get_payment_gateway, get_registry_lookup
from app.integrations.registry import RegistryLookup
from app.models.models import Organizer
from app.promotions.checkout import CheckoutInput, CheckoutRefused, start_checkout
from app.promotions.flags import checkout_enabled, offer_enabled
from app.promotions.grant import PromotionRefused
from app.promotions.registry_check import RegistryRefused, verified_legal_name
from app.promotions.windows import now_tallinn
from app.rate_limit import limiter

# Must stay under /organizer/*: the organizer session cookie is scoped to /api/organizer.
router = APIRouter(prefix="/organizer/promotions", tags=["organizer-promotions"])


def _require_offer() -> None:
    if not offer_enabled():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=PROMOTION_ERROR_OFFER_DISABLED
        )


def _require_checkout() -> None:
    if not checkout_enabled():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=PROMOTION_ERROR_OFFER_DISABLED
        )


def _registry_refusal(refused: RegistryRefused) -> HTTPException:
    unavailable = refused.code == PROMOTION_ERROR_REGISTRY_UNAVAILABLE
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE
        if unavailable
        else status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail={"code": refused.code, "message": refused.message},
    )


_CHECKOUT_REFUSAL_STATUS = {
    PROMOTION_ERROR_CHECKOUT_NEEDS_REVIEW: status.HTTP_409_CONFLICT,
    PROMOTION_ERROR_CHECKOUT_NOT_PROMOTABLE: status.HTTP_409_CONFLICT,
    PROMOTION_ERROR_CHECKOUT_NOT_OWNER: status.HTTP_404_NOT_FOUND,
    PROMOTION_ERROR_CHECKOUT_PROVIDER: status.HTTP_502_BAD_GATEWAY,
}


class RegistryLookupBody(BaseModel):
    registry_code: str = Field(max_length=PROMOTION_REGISTRY_CODE_MAX_LEN)


class CheckoutBody(BaseModel):
    event_id: int
    start_date: date
    end_date: date
    registry_code: str = Field(max_length=PROMOTION_REGISTRY_CODE_MAX_LEN)
    billing_email: EmailStr | None = Field(
        default=None, max_length=PROMOTION_BILLING_EMAIL_MAX_CHARS
    )
    content_policy_attested: bool
    business_attested: bool
    terms_accepted: bool


@router.post("/registry-lookup")
@limiter.limit(RATE_LIMIT_PROMOTION_REGISTRY_LOOKUP)
async def registry_lookup(
    body: RegistryLookupBody,
    request: Request,
    _organizer: Organizer = Depends(get_current_organizer),
    registry: RegistryLookup = Depends(get_registry_lookup),
) -> dict:
    """The legal name for a registry code, or a coded refusal in `detail`:
    422 `registry_invalid_code` / `registry_company_deleted` /
    `registry_company_not_found`, 503 `registry_unavailable` (fail closed: offer
    the bank-transfer request instead)."""
    _require_offer()
    try:
        legal_name = await verified_legal_name(registry, body.registry_code)
    except RegistryRefused as refused:
        raise _registry_refusal(refused) from None
    return {"registry_code": body.registry_code.strip(), "legal_name": legal_name}


@router.post("/checkout", status_code=status.HTTP_201_CREATED)
@limiter.limit(RATE_LIMIT_PROMOTION_CHECKOUT)
async def start_promotion_checkout(
    body: CheckoutBody,
    request: Request,
    organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
    gateway: PaymentGateway = Depends(get_payment_gateway),
    registry: RegistryLookup = Depends(get_registry_lookup),
) -> dict:
    """Hold the days and open a Stripe Checkout session. Returns
    `{promotion_id, checkout_url, expires_at}`; the SPA redirects to the URL.
    Refusals carry `detail.code` and `detail.message`: 404 `not_event_owner`,
    409 `event_needs_review` / `event_not_promotable` (and the window rules
    `overlap` / `cap_exceeded`, with `detail.errors`), 422 for the other window
    rules, the attestation and terms, and the registry codes (503
    `registry_unavailable`), 502 `checkout_unavailable`."""
    _require_checkout()
    data = CheckoutInput(
        event_id=body.event_id,
        start_date=body.start_date,
        end_date=body.end_date,
        registry_code=body.registry_code,
        billing_email=str(body.billing_email) if body.billing_email else None,
        content_policy_attested=body.content_policy_attested,
        business_attested=body.business_attested,
        terms_accepted=body.terms_accepted,
    )
    try:
        started = await start_checkout(db, gateway, registry, organizer, data, now_tallinn())
    except RegistryRefused as refused:
        raise _registry_refusal(refused) from None
    except CheckoutRefused as refused:
        raise HTTPException(
            status_code=_CHECKOUT_REFUSAL_STATUS.get(
                refused.code, status.HTTP_422_UNPROCESSABLE_CONTENT
            ),
            detail={"code": refused.code, "message": PROMOTION_CHECKOUT_ERROR_MESSAGES[refused.code]},
        ) from None
    except PromotionRefused as refused:
        conflict = any(v.code in PROMOTION_CONFLICT_ERROR_CODES for v in refused.violations)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT
            if conflict
            else status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": refused.violations[0].code,
                "message": refused.violations[0].message,
                "errors": [v.as_dict() for v in refused.violations],
            },
        ) from None
    promotion = started.promotion
    return {
        "promotion_id": promotion.id,
        "checkout_url": started.checkout_url,
        "expires_at": promotion.checkout_expires_at.isoformat()
        if promotion.checkout_expires_at
        else None,
    }
