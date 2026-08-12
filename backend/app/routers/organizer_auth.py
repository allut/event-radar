"""Organizer auth endpoints — magic-link request + verification + current-organizer.

A parallel track to app/routers/auth.py's consumer auth: separate account
table, separate magic-link table, distinct token salts (app/auth/tokens.py)
so a user token and an organizer token can never be confused for one another.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
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
    ERROR_MAGIC_LINK_CONSUMED,
    ERROR_MAGIC_LINK_EXPIRED,
    ERROR_MAGIC_LINK_INVALID,
    ERROR_MISSING_SESSION_COOKIE,
    ERROR_ORGANIZER_NOT_FOUND,
    ERROR_SESSION_INVALID,
    ERROR_SESSION_REVOKED,
    LOG_EVENT_AUTH_FAILED,
    ORGANIZER_AUTH_VERIFY_PATH,
    ORGANIZER_SESSION_COOKIE_NAME,
    ORGANIZER_SESSION_COOKIE_PATH,
    ORGANIZER_SESSION_TTL_DAYS,
    RATE_LIMIT_AUTH_REQUEST_LINK,
    RATE_LIMIT_AUTH_VERIFY,
    RATE_LIMIT_LOGOUT,
    RATE_LIMIT_LOGOUT_ALL,
    VALID_LOCALES,
)
from app.db import get_db
from app.models.models import Organizer, OrganizerMagicLink
from app.rate_limit import limiter
from app.routers.utils import (
    RequestLinkBody,
    VerifyTokenBody,
    clear_session_cookie,
    mask_email,
    recent_unused_link_exists,
    set_session_cookie,
)

log = logging.getLogger(__name__)
# Every organizer endpoint must live under this /organizer/* prefix (or the
# mirrored /organizer/events/* router) — ORGANIZER_SESSION_COOKIE_PATH scopes
# the cookie to Path=/api/organizer, so a future organizer route added
# outside that prefix would silently never receive it and 401 on every call.
router = APIRouter(prefix="/organizer/auth", tags=["organizer-auth"])


async def get_current_organizer(
    organizer_session: str | None = Cookie(
        default=None, alias=ORGANIZER_SESSION_COOKIE_NAME
    ),
    db: AsyncSession = Depends(get_db),
) -> Organizer:
    if not organizer_session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MISSING_SESSION_COOKIE,
        )
    try:
        organizer_id, token_version = verify_organizer_session_token(organizer_session)
    except (SignatureExpired, BadSignature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_SESSION_INVALID,
        )
    organizer = await db.get(Organizer, organizer_id)
    if organizer is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_ORGANIZER_NOT_FOUND,
        )
    if token_version != organizer.session_token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_SESSION_REVOKED,
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


@router.post("/verify")
@limiter.limit(RATE_LIMIT_AUTH_VERIFY)
async def verify_organizer_magic_link(
    request: Request,
    body: VerifyTokenBody,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Verify an organizer magic-link token. Sets the organizer session
    cookie on success; mirrors auth.py::verify_magic_link's body-token /
    no-token-in-response shape."""
    token = body.token
    try:
        organizer_id = verify_organizer_magic_token(token)
    except SignatureExpired:
        log.warning(
            "organizer magic-link verify failed: expired",
            extra={"event": LOG_EVENT_AUTH_FAILED},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MAGIC_LINK_EXPIRED,
        )
    except BadSignature:
        log.warning(
            "organizer magic-link verify failed: bad-signature",
            extra={"event": LOG_EVENT_AUTH_FAILED},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MAGIC_LINK_INVALID,
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
            detail=ERROR_MAGIC_LINK_CONSUMED,
        )

    await db.commit()

    organizer = await db.get(Organizer, organizer_id)
    if organizer is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_ORGANIZER_NOT_FOUND,
        )

    session_token = generate_organizer_session_token(
        organizer.id, organizer.session_token_version
    )
    set_session_cookie(
        response,
        name=ORGANIZER_SESSION_COOKIE_NAME,
        token=session_token,
        path=ORGANIZER_SESSION_COOKIE_PATH,
        ttl_days=ORGANIZER_SESSION_TTL_DAYS,
    )
    return {
        "organizer": {
            "id": organizer.id,
            "email": organizer.email,
            "locale": organizer.locale,
        },
    }


@router.post("/logout", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_LOGOUT)
async def organizer_logout(
    request: Request,
    response: Response,
    current_organizer: Organizer = Depends(get_current_organizer),
) -> dict:
    """Sign out this device only. Mirrors auth.py::logout — expires the
    cookie without touching session_token_version."""
    clear_session_cookie(
        response, name=ORGANIZER_SESSION_COOKIE_NAME, path=ORGANIZER_SESSION_COOKIE_PATH
    )
    return {"detail": "Signed out."}


@router.post("/logout-all", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_LOGOUT_ALL)
async def organizer_logout_all(
    request: Request,
    response: Response,
    current_organizer: Organizer = Depends(get_current_organizer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Invalidate every organizer session token issued so far. Mirrors
    auth.py::logout_all's atomic UPDATE ... RETURNING pattern, including
    expiring this device's cookie directly."""
    result = await db.execute(
        update(Organizer)
        .where(Organizer.id == current_organizer.id)
        .values(session_token_version=Organizer.session_token_version + 1)
        .returning(Organizer.session_token_version)
    )
    new_version = result.scalar_one()
    await db.commit()
    current_organizer.session_token_version = new_version
    clear_session_cookie(
        response, name=ORGANIZER_SESSION_COOKIE_NAME, path=ORGANIZER_SESSION_COOKIE_PATH
    )
    return {"detail": "Signed out of all devices."}
