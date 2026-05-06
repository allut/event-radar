"""Auth endpoints — magic-link request + verification + current-user."""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from itsdangerous import BadSignature, SignatureExpired
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, update
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
from app.config import settings
from app.db import get_db
from app.models.models import AuthMagicLink, User

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


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
    token = authorization[len("Bearer "):]
    try:
        user_id = verify_session_token(token)
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
    return user


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/request-link", status_code=status.HTTP_200_OK)
async def request_magic_link(
    body: RequestLinkBody,
    db: AsyncSession = Depends(get_db),
):
    """Request a magic sign-in link. Always returns 200 to prevent user enumeration."""
    email = body.email.lower()

    # Upsert user
    user = await db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email)
        db.add(user)
        await db.flush()  # populate user.id

    # Per-email cooldown: skip if an unused link was issued in the last 2 minutes.
    # A link created T seconds ago has expires_at = now + (TTL - T), so
    # expires_at > now + TTL - 120 ↔ T < 120 (i.e. created less than 2 min ago).
    # This prevents Resend quota exhaustion from rapid repeated requests.
    # TODO before production: add IP-level rate limiting (SlowAPI/fastapi-limiter).
    recent_cutoff = datetime.now(timezone.utc) + timedelta(seconds=magic_ttl_seconds() - 120)
    already_sent = await db.scalar(
        select(AuthMagicLink).where(
            AuthMagicLink.user_id == user.id,
            AuthMagicLink.used_at.is_(None),
            AuthMagicLink.expires_at > recent_cutoff,
        ).limit(1)
    )
    if already_sent is not None:
        return {"detail": "If that address is registered, a sign-in link has been sent."}

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
        await send_magic_link(email, signed_token)
    except Exception:
        log.exception("Failed to send magic link to %s", email)
        # Do not surface email errors to caller — link is in DB, user can retry.

    return {"detail": "If that address is registered, a sign-in link has been sent."}


@router.get("/verify")
async def verify_magic_link(
    token: str,
    db: AsyncSession = Depends(get_db),
):
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

    session_token = generate_session_token(user.id)
    return {
        "session_token": session_token,
        "user": {
            "id": user.id,
            "email": user.email,
            "locale": user.locale,
        },
    }


@router.get("/me")
async def get_me(current_user: User = Depends(get_current_user)):
    """Return the currently authenticated user."""
    return {
        "id": current_user.id,
        "email": current_user.email,
        "locale": current_user.locale,
        "home_city": current_user.home_city,
        "created_at": current_user.created_at.isoformat(),
    }
