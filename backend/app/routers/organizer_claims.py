"""Organizer event-claiming endpoints (#413) — the first slice of #409 to
actually create/mutate a `claims` row. See CONTEXT.md's Event Claiming
glossary, docs/organizer-portal.md, and app/claims/lifecycle.py for the
business logic these endpoints just wire up to HTTP.
"""

import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired
from pydantic import BaseModel, EmailStr
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.email import send_magic_link
from app.auth.tokens import (
    generate_organizer_claim_link_token,
    generate_organizer_session_token,
    hash_token,
    organizer_magic_ttl_seconds,
    verify_organizer_claim_link_token,
)
from app.claims.lifecycle import ClaimError, cancel_claim, create_claim, recheck_claim
from app.constants import (
    DETAIL_MAGIC_LINK_SENT,
    ERROR_MAGIC_LINK_CONSUMED,
    ERROR_MAGIC_LINK_EXPIRED,
    ERROR_MAGIC_LINK_INVALID,
    ERROR_ORGANIZER_NOT_FOUND,
    HTTP_TIMEOUT_SECONDS,
    LOG_EVENT_AUTH_FAILED,
    ORGANIZER_AUTH_VERIFY_PATH,
    ORGANIZER_SESSION_COOKIE_NAME,
    ORGANIZER_SESSION_COOKIE_PATH,
    ORGANIZER_SESSION_TTL_DAYS,
    RATE_LIMIT_AUTH_REQUEST_LINK,
    RATE_LIMIT_AUTH_VERIFY,
    RATE_LIMIT_CLAIM,
    SECONDS_PER_DAY,
    VALID_LOCALES,
)
from app.db import get_db
from app.models.models import Claim, Organizer, OrganizerMagicLink
from app.rate_limit import limiter
from app.routers.organizer_auth import get_current_organizer
from app.routers.utils import (
    get_or_create_organizer,
    mask_email,
    recent_unused_link_exists,
    set_session_cookie,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/organizer/claims", tags=["organizer-claims"])


class CreateClaimBody(BaseModel):
    event_id: int


class ClaimLinkRequestBody(BaseModel):
    email: EmailStr
    event_id: int
    locale: str | None = None


class ClaimLinkVerifyBody(BaseModel):
    token: str


def _serialize(claim: Claim) -> dict:
    return {
        "id": claim.id,
        "kind": claim.kind,
        "publisher_id": claim.publisher_id,
        "event_series_key": claim.event_series_key,
        "status": claim.status,
        "verification_mechanism": claim.verification_mechanism,
        "proof_token": claim.proof_token,
        "created_at": claim.created_at,
        "last_checked_at": claim.last_checked_at,
        "resolved_at": claim.resolved_at,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
@limiter.limit(RATE_LIMIT_CLAIM)
async def create_own_claim(
    body: CreateClaimBody,
    request: Request,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        try:
            claim = await create_claim(db, client, current_organizer, body.event_id)
        except ClaimError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return _serialize(claim)


@router.post("/{claim_id}/cancel")
@limiter.limit(RATE_LIMIT_CLAIM)
async def cancel_own_claim(
    claim_id: int,
    request: Request,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        claim = await cancel_claim(db, current_organizer, claim_id)
    except ClaimError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return _serialize(claim)


@router.post("/{claim_id}/recheck")
@limiter.limit(RATE_LIMIT_CLAIM)
async def recheck_own_claim(
    claim_id: int,
    request: Request,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        try:
            claim = await recheck_claim(db, client, current_organizer, claim_id)
        except ClaimError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return _serialize(claim)


@router.post("/request-link", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_AUTH_REQUEST_LINK)
async def request_claim_link(
    body: ClaimLinkRequestBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Sign-in link for an organizer who wants to claim `event_id` but isn't
    signed in yet — the claim intent (event_id) is encoded into the token
    itself (generate_organizer_claim_link_token), not a query param or
    sessionStorage, so it round-trips even when the link is opened on a
    different device/session. Always returns 200 (anti-enumeration), mirrors
    organizer_auth.py::request_organizer_magic_link."""
    email = body.email.lower()
    requested_locale = body.locale if body.locale in VALID_LOCALES else None
    organizer = await get_or_create_organizer(db, email, requested_locale)
    email_locale = requested_locale or organizer.locale

    if await recent_unused_link_exists(
        db,
        OrganizerMagicLink,
        OrganizerMagicLink.organizer_id,
        organizer.id,
        organizer_magic_ttl_seconds(),
    ):
        return {"detail": DETAIL_MAGIC_LINK_SENT}

    signed_token, token_hash, expires_at = generate_organizer_claim_link_token(
        organizer.id, body.event_id
    )
    db.add(
        OrganizerMagicLink(
            organizer_id=organizer.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
    )
    await db.commit()

    try:
        await send_magic_link(
            email, signed_token, email_locale, verify_path=ORGANIZER_AUTH_VERIFY_PATH
        )
    except Exception:
        log.exception("Failed to send organizer claim link to %s", mask_email(email))
        # Do not surface email errors to caller — link is in DB, organizer can retry.

    return {"detail": DETAIL_MAGIC_LINK_SENT}


@router.post("/verify-link")
@limiter.limit(RATE_LIMIT_AUTH_VERIFY)
async def verify_claim_link(
    request: Request,
    body: ClaimLinkVerifyBody,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Verify a claim-intent magic link: signs the organizer in (same session
    cookie as organizer_auth.py::verify_organizer_magic_link) and immediately
    creates the claim the link was minted for."""
    token = body.token
    try:
        organizer_id, event_id = verify_organizer_claim_link_token(token)
    except SignatureExpired:
        log.warning(
            "organizer claim-link verify failed: expired",
            extra={"event": LOG_EVENT_AUTH_FAILED},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=ERROR_MAGIC_LINK_EXPIRED
        )
    except (BadSignature, KeyError):
        # KeyError: a validly-signed token with no "eid" claim — e.g. a plain
        # organizer sign-in token (generate_organizer_magic_token), which
        # shares this salt but was never minted with claim intent. Treated
        # the same as a bad signature rather than a 500 (#413 review finding).
        log.warning(
            "organizer claim-link verify failed: bad-signature",
            extra={"event": LOG_EVENT_AUTH_FAILED},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=ERROR_MAGIC_LINK_INVALID
        )

    token_hash = hash_token(token)
    now = datetime.now(timezone.utc)

    # Atomic UPDATE — same TOCTOU-closing pattern as organizer_auth.py::verify_organizer_magic_link.
    result = await db.execute(
        update(OrganizerMagicLink)
        .where(
            OrganizerMagicLink.token_hash == token_hash,
            OrganizerMagicLink.organizer_id == organizer_id,
            OrganizerMagicLink.used_at.is_(None),
            OrganizerMagicLink.expires_at > now,
        )
        .values(used_at=now)
        .returning(OrganizerMagicLink.organizer_id)
    )
    if result.fetchone() is None:
        log.warning(
            "organizer claim-link verify failed: already-used or not-found",
            extra={"event": LOG_EVENT_AUTH_FAILED},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=ERROR_MAGIC_LINK_CONSUMED
        )
    await db.commit()

    organizer = await db.get(Organizer, organizer_id)
    if organizer is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=ERROR_ORGANIZER_NOT_FOUND
        )

    session_token = generate_organizer_session_token(
        organizer.id, organizer.session_token_version
    )
    set_session_cookie(
        response,
        name=ORGANIZER_SESSION_COOKIE_NAME,
        token=session_token,
        path=ORGANIZER_SESSION_COOKIE_PATH,
        ttl_seconds=ORGANIZER_SESSION_TTL_DAYS * SECONDS_PER_DAY,
    )

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        try:
            claim = await create_claim(db, client, organizer, event_id)
        except ClaimError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    return {
        "organizer": {
            "id": organizer.id,
            "email": organizer.email,
            "locale": organizer.locale,
        },
        "claim": _serialize(claim),
    }
