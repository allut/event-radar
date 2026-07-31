"""Organizer auth endpoints — magic-link request + verification + current-organizer.

A parallel track to app/routers/auth.py's consumer auth: separate account
table, separate magic-link table, distinct token salts (app/auth/tokens.py)
so a user token and an organizer token can never be confused for one another.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.email import send_magic_link
from app.auth.tokens import (
    generate_organizer_magic_token,
    generate_organizer_session_token,
    hash_token,
    organizer_magic_ttl_seconds,
    verify_organizer_magic_token,
    verify_organizer_session_token,
)
from app.constants import (
    DEFAULT_USER_LOCALE,
    LOG_EVENT_AUTH_FAILED,
    ORGANIZER_AUTH_VERIFY_PATH,
    RATE_LIMIT_AUTH_REQUEST_LINK,
    RATE_LIMIT_AUTH_VERIFY,
    RATE_LIMIT_LOGOUT_ALL,
    VALID_LOCALES,
)
from app.db import get_db
from app.models.models import Organizer, OrganizerMagicLink
from app.rate_limit import limiter
from app.routers.utils import RequestLinkBody, mask_email, recent_unused_link_exists

log = logging.getLogger(__name__)
router = APIRouter(prefix="/organizer/auth", tags=["organizer-auth"])


async def get_current_organizer(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> Organizer:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization[len("Bearer ") :]
    try:
        organizer_id, token_version = verify_organizer_session_token(token)
    except (SignatureExpired, BadSignature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token expired or invalid",
            headers={"WWW-Authenticate": "Bearer"},
        )
    organizer = await db.get(Organizer, organizer_id)
    if organizer is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Organizer not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if token_version != organizer.session_token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session revoked. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return organizer


async def _get_or_create_organizer(
    db: AsyncSession, email: str, requested_locale: str | None
) -> Organizer:
    """Look up (or insert) the organizer for a magic-link request. Mirrors
    auth.py::_get_or_create_user — same unverified-row-creation trade-off,
    mitigated the same way (RATE_LIMIT_AUTH_REQUEST_LINK + cooldown)."""
    organizer = await db.scalar(select(Organizer).where(Organizer.email == email))
    if organizer is None:
        organizer = Organizer(email=email, locale=requested_locale or DEFAULT_USER_LOCALE)
        db.add(organizer)
        await db.flush()
        log.info(
            "organizer auth: new unverified organizer row created email=%s",
            mask_email(email),
        )
    return organizer


@router.post("/request-link", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_AUTH_REQUEST_LINK)
async def request_organizer_magic_link(
    body: RequestLinkBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Request an organizer sign-in link. Always returns 200 (anti-enumeration)."""
    email = body.email.lower()
    requested_locale = body.locale if body.locale in VALID_LOCALES else None
    organizer = await _get_or_create_organizer(db, email, requested_locale)
    email_locale = requested_locale or organizer.locale

    if await recent_unused_link_exists(
        db,
        OrganizerMagicLink,
        OrganizerMagicLink.organizer_id,
        organizer.id,
        organizer_magic_ttl_seconds(),
    ):
        return {
            "detail": "If that address is registered, a sign-in link has been sent."
        }

    signed_token, token_hash, expires_at = generate_organizer_magic_token(organizer.id)

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
        log.exception("Failed to send organizer magic link to %s", mask_email(email))
        # Do not surface email errors to caller — link is in DB, organizer can retry.

    return {"detail": "If that address is registered, a sign-in link has been sent."}


@router.get("/verify")
@limiter.limit(RATE_LIMIT_AUTH_VERIFY)
async def verify_organizer_magic_link(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Verify an organizer magic-link token. Returns a session token on success."""
    try:
        organizer_id = verify_organizer_magic_token(token)
    except SignatureExpired:
        log.warning(
            "organizer magic-link verify failed: expired",
            extra={"event": LOG_EVENT_AUTH_FAILED},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sign-in link has expired. Please request a new one.",
        )
    except BadSignature:
        log.warning(
            "organizer magic-link verify failed: bad-signature",
            extra={"event": LOG_EVENT_AUTH_FAILED},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid sign-in link.",
        )

    token_hash = hash_token(token)
    now = datetime.now(timezone.utc)

    # Atomic UPDATE — same TOCTOU-closing pattern as auth.py::verify_magic_link.
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
            "organizer magic-link verify failed: already-used or not-found",
            extra={"event": LOG_EVENT_AUTH_FAILED},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sign-in link already used, expired, or not found.",
        )

    await db.commit()

    organizer = await db.get(Organizer, organizer_id)
    if organizer is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organizer not found.",
        )

    session_token = generate_organizer_session_token(
        organizer.id, organizer.session_token_version
    )
    return {
        "session_token": session_token,
        "organizer": {
            "id": organizer.id,
            "email": organizer.email,
            "locale": organizer.locale,
        },
    }


@router.post("/logout-all", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_LOGOUT_ALL)
async def organizer_logout_all(
    request: Request,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Invalidate every organizer session token issued so far. Mirrors
    auth.py::logout_all's atomic UPDATE ... RETURNING pattern."""
    result = await db.execute(
        update(Organizer)
        .where(Organizer.id == current_organizer.id)
        .values(session_token_version=Organizer.session_token_version + 1)
        .returning(Organizer.session_token_version)
    )
    new_version = result.scalar_one()
    await db.commit()
    current_organizer.session_token_version = new_version
    return {"detail": "Signed out of all devices."}
