"""GET/POST /email/unsubscribe, /email/resubscribe — one-click digest opt-out.

Public (no session auth): identity comes from a signed, long-lived itsdangerous
token minted into every digest email (app/auth/tokens.py). The visible email
link is a GET to the frontend /unsubscribe page, which POSTs here; the RFC 8058
List-Unsubscribe header also POSTs here directly for mail clients that render
a native one-click button. Token lives in the query string (not a header) so
both callers hit the identical URL.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import verify_unsubscribe_token
from app.constants import RATE_LIMIT_UNSUBSCRIBE
from app.db import get_db
from app.models.models import User
from app.rate_limit import limiter
from app.routers.utils import mask_email

log = logging.getLogger(__name__)
router = APIRouter(prefix="/email", tags=["unsubscribe"])


async def _load_user_from_token(token: str, db: AsyncSession) -> User:
    try:
        user_id = verify_unsubscribe_token(token)
    except SignatureExpired:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsubscribe link has expired. Please use Settings instead.",
        )
    except BadSignature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid unsubscribe link.",
        )
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User not found.",
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
    user.email_digest_opt_in = False
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
    user.email_digest_opt_in = True
    await db.commit()
    log.info("digest resubscribe: user=%s", mask_email(user.email))
    return {"ok": True, "email": mask_email(user.email)}
