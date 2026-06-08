"""Auth endpoints — magic-link request + verification + current-user."""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.email import send_magic_link
from app.auth.tokens import (
    generate_magic_token,
    generate_session_token,
    hash_token,
    magic_ttl_seconds,
    verify_magic_token,
    verify_session_token,
)
from app.constants import (
    DEFAULT_USER_LOCALE,
    RATE_LIMIT_AUTH_REQUEST_LINK,
    RATE_LIMIT_AUTH_VERIFY,
    VALID_LOCALES,
)
from app.db import get_db
from app.models.models import AuthMagicLink, User, UserPersona
from app.rate_limit import limiter
from app.routers.utils import mask_email, serialize_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


def _detect_locale(accept_language: str) -> str:
    """Pick the best supported locale from an Accept-Language header value."""
    for part in accept_language.replace(" ", "").split(","):
        lang = part.split(";")[0].split("-")[0].lower()
        if lang in VALID_LOCALES:
            return lang
    return DEFAULT_USER_LOCALE


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class RequestLinkBody(BaseModel):
    email: EmailStr


# ---------------------------------------------------------------------------
# Shared auth dependency
# ---------------------------------------------------------------------------


async def get_current_user(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization[len("Bearer ") :]
    try:
        user_id, token_version = verify_session_token(token)
    except (SignatureExpired, BadSignature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token expired or invalid",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if token_version != user.session_token_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session revoked. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/request-link", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_AUTH_REQUEST_LINK)
async def request_magic_link(
    body: RequestLinkBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Request a magic sign-in link. Always returns 200 to prevent user enumeration."""
    email = body.email.lower()

    # Upsert user
    user = await db.scalar(select(User).where(User.email == email))
    if user is None:
        locale = _detect_locale(request.headers.get("Accept-Language", ""))
        user = User(email=email, locale=locale)
        db.add(user)
        await db.flush()  # populate user.id

    # Per-email cooldown: skip if an unused link was issued in the last 2 minutes.
    # A link created T seconds ago has expires_at = now + (TTL - T), so
    # expires_at > now + TTL - 120 ↔ T < 120 (i.e. created less than 2 min ago).
    # This prevents Resend quota exhaustion from rapid repeated requests.
    # IP-level throttling is handled separately by @limiter.limit(RATE_LIMIT_AUTH_REQUEST_LINK).
    recent_cutoff = datetime.now(timezone.utc) + timedelta(
        seconds=magic_ttl_seconds() - 120
    )
    already_sent = await db.scalar(
        select(AuthMagicLink)
        .where(
            AuthMagicLink.user_id == user.id,
            AuthMagicLink.used_at.is_(None),
            AuthMagicLink.expires_at > recent_cutoff,
        )
        .limit(1)
    )
    if already_sent is not None:
        return {
            "detail": "If that address is registered, a sign-in link has been sent."
        }

    signed_token, token_hash, expires_at = generate_magic_token(user.id)

    db.add(
        AuthMagicLink(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
    )
    await db.commit()

    try:
        await send_magic_link(email, signed_token, user.locale)
    except Exception:
        log.exception("Failed to send magic link to %s", mask_email(email))
        # Do not surface email errors to caller — link is in DB, user can retry.

    return {"detail": "If that address is registered, a sign-in link has been sent."}


@router.get("/verify")
@limiter.limit(RATE_LIMIT_AUTH_VERIFY)
async def verify_magic_link(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Verify a magic-link token. Returns a session token on success."""
    try:
        user_id = verify_magic_token(token)
    except SignatureExpired:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sign-in link has expired. Please request a new one.",
        )
    except BadSignature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid sign-in link.",
        )

    token_hash = hash_token(token)
    now = datetime.now(timezone.utc)

    # Atomic UPDATE: collapses read-then-write into one statement, preventing the
    # TOCTOU race where two concurrent requests both see used_at IS NULL.
    result = await db.execute(
        update(AuthMagicLink)
        .where(
            AuthMagicLink.token_hash == token_hash,
            AuthMagicLink.user_id == user_id,
            AuthMagicLink.used_at.is_(None),
            AuthMagicLink.expires_at > now,
        )
        .values(used_at=now)
        .returning(AuthMagicLink.user_id)
    )
    if result.fetchone() is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sign-in link already used, expired, or not found.",
        )

    await db.commit()

    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User not found.",
        )

    session_token = generate_session_token(user.id, user.session_token_version)
    return {
        "session_token": session_token,
        "user": {
            "id": user.id,
            "email": user.email,
            "locale": user.locale,
        },
    }


@router.post("/logout-all", status_code=status.HTTP_200_OK)
async def logout_all(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Invalidate every session token issued so far ("log out everywhere") by
    bumping session_token_version — get_current_user rejects any token whose
    embedded "v" claim no longer matches the stored value, including the one
    used to make this very request.

    Atomic UPDATE ... RETURNING (mirrors verify_magic_link's token-consume
    pattern) rather than ORM read-modify-write, so two concurrent calls can't
    race and silently lose an increment."""
    result = await db.execute(
        update(User)
        .where(User.id == current_user.id)
        .values(session_token_version=User.session_token_version + 1)
        .returning(User.session_token_version)
    )
    new_version = result.scalar_one()
    await db.commit()
    current_user.session_token_version = new_version
    return {"detail": "Signed out of all devices."}


@router.get("/me")
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the currently authenticated user."""
    count: int = (
        await db.scalar(
            select(func.count())
            .select_from(UserPersona)
            .where(UserPersona.user_id == current_user.id)
        )
        or 0
    )
    return serialize_user(current_user, has_personas=count > 0)
