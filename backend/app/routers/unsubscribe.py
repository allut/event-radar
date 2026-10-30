"""POST /email/unsubscribe, /email/resubscribe, /email/ads-off, /email/ads-on —
one-click digest opt-out and Email ad consent withdrawal (and its undo).

Public (no session auth): identity comes from a signed, long-lived itsdangerous
token minted into every digest email (app/auth/tokens.py). The visible email
link is a GET to the frontend /unsubscribe page, which POSTs here; the RFC 8058
List-Unsubscribe header also POSTs here directly for mail clients that render
a native one-click button. Token lives in the query string (not a header) so
both callers hit the identical URL.
"""

import logging
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import verify_ads_off_token, verify_unsubscribe_token
from app.constants.auth import ERROR_USER_NOT_FOUND
from app.config import settings
from app.constants.email import (
    CONSENT_SOURCE_EMAIL_LINK,
    CONSENT_SOURCE_EMAIL_LINK_UNDO,
    ERROR_AD_CONSENT_UNAVAILABLE,
    ERROR_UNSUBSCRIBE_LINK_EXPIRED,
    ERROR_UNSUBSCRIBE_LINK_INVALID,
)
from app.constants.rate_limits import RATE_LIMIT_UNSUBSCRIBE
from app.db import get_db
from app.email.consent import grant_ad_consent, withdraw_ad_consent
from app.email.subscription import set_digest_subscription
from app.models.models import EmailAdConsentLog, User
from app.rate_limit import limiter
from app.auth.utils import mask_email

log = logging.getLogger(__name__)
router = APIRouter(prefix="/email", tags=["unsubscribe"])


async def _load_user_from_token(
    token: str, db: AsyncSession, verify: Callable[[str], int] = verify_unsubscribe_token
) -> User:
    try:
        user_id = verify(token)
    except SignatureExpired:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_UNSUBSCRIBE_LINK_EXPIRED,
        )
    except BadSignature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_UNSUBSCRIBE_LINK_INVALID,
        )
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_USER_NOT_FOUND,
        )
    return user


@router.post("/unsubscribe")
@limiter.limit(RATE_LIMIT_UNSUBSCRIBE)
async def unsubscribe(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Flip email_digest_opt_in off. Accepts an empty body — RFC 8058 one-click
    clients POST `List-Unsubscribe=One-Click` as the body, which FastAPI simply
    ignores since no body param is declared here."""
    user = await _load_user_from_token(token, db)
    set_digest_subscription(user, False, db)
    await db.commit()
    log.info("digest unsubscribe: user=%s", mask_email(user.email))
    return {"ok": True, "email": mask_email(user.email)}


@router.post("/resubscribe")
@limiter.limit(RATE_LIMIT_UNSUBSCRIBE)
async def resubscribe(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Undo an unsubscribe — same token stays valid, mirroring the reversible
    intent described on the /unsubscribe confirmation page."""
    user = await _load_user_from_token(token, db)
    set_digest_subscription(user, True, db)
    await db.commit()
    log.info("digest resubscribe: user=%s", mask_email(user.email))
    return {"ok": True, "email": mask_email(user.email)}


@router.post("/ads-off")
@limiter.limit(RATE_LIMIT_UNSUBSCRIBE)
async def ads_off(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Withdraw Email ad consent from the digest's "Stop ads in this email" link.
    The digest keeps coming. Idempotent: a second click logs nothing."""
    user = await _load_user_from_token(token, db, verify_ads_off_token)
    withdraw_ad_consent(user, db, CONSENT_SOURCE_EMAIL_LINK)
    await db.commit()
    log.info("email ads off: user=%s", mask_email(user.email))
    return {"ok": True, "email": mask_email(user.email)}


@router.post("/ads-on")
@limiter.limit(RATE_LIMIT_UNSUBSCRIBE)
async def ads_on(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Undo ads-off with the same token: a grant logged as `email_link_undo` at
    the current wording version. Only a user whose latest consent-log row is an
    `email_link` withdrawal can be granted this way; anyone else (never
    consented, or withdrew in Settings) gets the invalid-link 400 and nothing
    changes. 409 unless the digest and the slot flag are on."""
    user = await _load_user_from_token(token, db, verify_ads_off_token)
    if user.email_ad_consent:
        return {"ok": True, "email": mask_email(user.email)}  # already on: idempotent
    latest = await db.scalar(
        select(EmailAdConsentLog)
        .where(EmailAdConsentLog.user_id == user.id)
        .order_by(EmailAdConsentLog.created_at.desc(), EmailAdConsentLog.id.desc())
        .limit(1)
    )
    if latest is None or latest.granted or latest.source != CONSENT_SOURCE_EMAIL_LINK:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_UNSUBSCRIBE_LINK_INVALID,
        )
    if not (user.email_digest_opt_in and settings.PROMOTIONS_SLOTS_ENABLED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ERROR_AD_CONSENT_UNAVAILABLE,
        )
    grant_ad_consent(user, db, CONSENT_SOURCE_EMAIL_LINK_UNDO)
    await db.commit()
    log.info("email ads on (undo): user=%s", mask_email(user.email))
    return {"ok": True, "email": mask_email(user.email)}
