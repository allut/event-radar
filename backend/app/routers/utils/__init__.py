"""Shared serialization helpers for event routers."""

import logging
from datetime import date

from fastapi import HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from app._generated.shared_constants import (
    PROMOTION_ERROR_REQUEST_DAILY_LIMIT,
)
from app.constants.claims import (
    CLAIM_DNS_TXT_RECORD_LABEL,
    CLAIM_DNS_VERIFICATION_MECHANISMS,
)
from app.constants.promotions import (
    PROMOTION_ADVERTISER_NAME_MAX_CHARS,
    PROMOTION_BILLING_EMAIL_MAX_CHARS,
    PROMOTION_CONFLICT_ERROR_CODES,
    PROMOTION_INVOICE_REFERENCE_MAX_LEN,
    PROMOTION_NOTE_MAX_CHARS,
    PROMOTION_REGISTRY_CODE_MAX_LEN,
)
from app.constants.reports import (
    ERROR_INVALID_REPORT_REASON,
    VALID_REPORT_REASONS,
)
from app.promotions.grant import PromotionRefused

log = logging.getLogger(__name__)


def validate_report_reason(reason: str) -> None:
    """Shared by POST /reports and GET /admin/reports's ``reason`` filter —
    a single source of truth for the taxonomy check and its error message."""
    if reason not in VALID_REPORT_REASONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_INVALID_REPORT_REASON.format(reasons=sorted(VALID_REPORT_REASONS)),
        )


def claim_dns_record_name(mechanism: str | None, domain: str | None) -> str | None:
    """The TXT record name a DNS-TXT/Piletilevi-promoter claim's organizer is
    told to add (#412/#413) — shared by the organizer-facing pending screen
    (organizer_claims.py) and the admin claims queue (admin.py, #420) so the
    two never disagree on the record name shown for the same claim."""
    if mechanism in CLAIM_DNS_VERIFICATION_MECHANISMS and domain:
        return f"{CLAIM_DNS_TXT_RECORD_LABEL}.{domain}"
    return None


def promotion_refusal(refused: PromotionRefused) -> HTTPException:
    """409 when the state of things forbids the command, 429 for the daily
    request ceiling, 422 for bad input; `detail.errors` lists every rule
    broken."""
    codes = [v.code for v in refused.violations]
    if any(c in PROMOTION_CONFLICT_ERROR_CODES for c in codes):
        code = status.HTTP_409_CONFLICT
    elif PROMOTION_ERROR_REQUEST_DAILY_LIMIT in codes:
        code = status.HTTP_429_TOO_MANY_REQUESTS
    else:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(
        status_code=code,
        detail={
            "code": refused.violations[0].code,
            "message": refused.violations[0].message,
            "errors": [v.as_dict() for v in refused.violations],
        },
    )


class PromotionGrantBody(BaseModel):
    start_date: date
    end_date: date
    advertiser_legal_name: str = Field(max_length=PROMOTION_ADVERTISER_NAME_MAX_CHARS)
    advertiser_registry_code: str = Field(max_length=PROMOTION_REGISTRY_CODE_MAX_LEN)
    billing_email: EmailStr | None = Field(
        default=None, max_length=PROMOTION_BILLING_EMAIL_MAX_CHARS
    )
    is_complimentary: bool = False
    complimentary_note: str | None = Field(default=None, max_length=PROMOTION_NOTE_MAX_CHARS)
    invoice_reference: str | None = Field(default=None, max_length=PROMOTION_INVOICE_REFERENCE_MAX_LEN)
    # Required (both) when the event carries a Promotion restriction (#612).
    restriction_clearance_confirmed: bool = False
    restriction_clearance_note: str | None = Field(default=None, max_length=PROMOTION_NOTE_MAX_CHARS)
