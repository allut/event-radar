"""FastAPI ``Depends`` auth entry-points shared by every consumer and organizer
router. Defined once here so routers never import from each other's modules.
"""

from fastapi import Cookie, Depends, HTTPException, status
from itsdangerous import BadSignature, SignatureExpired
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import (
    verify_admin_session_token,
    verify_organizer_session_token,
    verify_session_token,
)
from app.config import settings
from app.constants import (
    ADMIN_SESSION_COOKIE_NAME,
    ERROR_MISSING_SESSION_COOKIE,
    ERROR_ORGANIZER_NOT_FOUND,
    ERROR_SESSION_INVALID,
    ERROR_SESSION_REVOKED,
    ERROR_USER_NOT_FOUND,
    FEATURE_ADMIN_ENDPOINTS,
    ORGANIZER_SESSION_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    SETTING_NAME_ADMIN_PASSWORD,
)
from app.db import get_db
from app.models.models import Organizer, User
from app.auth.utils import require_configured_secret


async def get_current_user(
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MISSING_SESSION_COOKIE,
        )
    try:
        user_id, token_version = verify_session_token(session)
    except (SignatureExpired, BadSignature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_SESSION_INVALID,
        )
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_USER_NOT_FOUND,
        )
    if token_version != user.session_token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_SESSION_REVOKED,
        )
    return user


async def get_optional_user(
    session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Like get_current_user, but returns None instead of raising 401 when
    there's no session, the token is expired/invalid, or it's been revoked —
    for endpoints open to anonymous callers (GET /explore, #234)."""
    if not session:
        return None
    try:
        user_id, token_version = verify_session_token(session)
    except (SignatureExpired, BadSignature):
        return None
    user = await db.get(User, user_id)
    if user is None or token_version != user.session_token_version:
        return None
    return user


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


def get_current_admin(
    admin_session: str | None = Cookie(default=None, alias=ADMIN_SESSION_COOKIE_NAME),
) -> None:
    """Session-only dependency — no HTTP Basic fallback, on any route. Every
    /admin/* route uses this (H-1 in the OWASP audit: a Basic branch checks
    only ADMIN_USERNAME/ADMIN_PASSWORD and never touches TOTP, so it made the
    admin console's second factor bypassable; OWASP audit #4 removed the last
    two Basic-eligible routes, /admin/counts and /admin/stats, since password-
    only access doubled as a guess oracle the per-IP lockout can't slow when
    spread across many IPs). Shared by routers/admin.py and
    routers/admin_auth.py, so it lives here rather than in either router.

    A missing cookie still goes through the same require_configured_secret
    dev fail-open every other secret-gated surface uses (ADMIN_PASSWORD
    unset + APP_ENV=development + ALLOW_INSECURE_DEV=true) — this is
    orthogonal to H-1: that bug was Basic credentials alone satisfying a
    *configured* password without TOTP, not the pre-existing "admin auth is
    off entirely" dev/test convenience."""
    if admin_session is None:
        if not require_configured_secret(
            settings.ADMIN_PASSWORD,
            feature=FEATURE_ADMIN_ENDPOINTS,
            setting_name=SETTING_NAME_ADMIN_PASSWORD,
            app_env=settings.APP_ENV,
            allow_insecure_dev=settings.ALLOW_INSECURE_DEV,
        ):
            return
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_MISSING_SESSION_COOKIE,
        )
    try:
        verify_admin_session_token(admin_session)
    except (SignatureExpired, BadSignature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_SESSION_INVALID,
        )
