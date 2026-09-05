"""Auth endpoints — magic-link request + verification + current-user."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired
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
from app.config import settings
from app.constants import (
    DEFAULT_USER_LOCALE,
    ERROR_MAGIC_LINK_CONSUMED,
    ERROR_MAGIC_LINK_EXPIRED,
    ERROR_MAGIC_LINK_INVALID,
    ERROR_MISSING_SESSION_COOKIE,
    ERROR_SESSION_INVALID,
    ERROR_SESSION_REVOKED,
    ERROR_USER_NOT_FOUND,
    LOG_EVENT_AUTH_FAILED,
    RATE_LIMIT_AUTH_REQUEST_LINK,
    RATE_LIMIT_AUTH_VERIFY,
    RATE_LIMIT_BROWSE,
    RATE_LIMIT_LOGOUT,
    RATE_LIMIT_LOGOUT_ALL,
    SECONDS_PER_DAY,
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_PATH,
    VALID_LOCALES,
)
from app.db import get_db
from app.models.models import AuthMagicLink, User, UserPersona
from app.rate_limit import limiter
from app.routers.utils import (
    RequestLinkBody,
    VerifyTokenBody,
    clear_session_cookie,
    mask_email,
    recent_unused_link_exists,
    record_unverified_account_creation,
    serialize_user,
    set_session_cookie,
)

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
# Shared auth dependency
# ---------------------------------------------------------------------------


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


async def _get_or_create_user(
    db: AsyncSession, email: str, request: Request, requested_locale: str | None
) -> User:
    """Look up (or insert) the user for a magic-link request.

    Creates a User row before the email is ever verified, so an
    unauthenticated caller can pollute the users table with unverified
    addresses (mitigated by RATE_LIMIT_AUTH_REQUEST_LINK + the per-email
    cooldown, not eliminated). The distinct greppable log marker lets an
    operator alert on abnormal unverified-account growth via shipped logs.

    A new user's locale is seeded from the requested (already-validated)
    locale when present, else detected from Accept-Language. An existing
    user's stored locale is never overwritten here — this endpoint is
    unauthenticated, so mutating an existing account's locale from it would
    be an abuse vector.
    """
    user = await db.scalar(select(User).where(User.email == email))
    if user is None:
        locale = requested_locale or _detect_locale(
            request.headers.get("Accept-Language", "")
        )
        user = User(email=email, locale=locale)
        db.add(user)
        await db.flush()  # populate user.id
        log.info("auth: new unverified user row created email=%s", mask_email(email))
        record_unverified_account_creation()
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
    requested_locale = body.locale if body.locale in VALID_LOCALES else None
    user = await _get_or_create_user(db, email, request, requested_locale)
    email_locale = requested_locale or user.locale

    if await recent_unused_link_exists(
        db, AuthMagicLink, AuthMagicLink.user_id, user.id, magic_ttl_seconds()
    ):
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
        await send_magic_link(
            email, signed_token, email_locale, theme_preference=user.theme_preference
        )
    except Exception:
        log.exception("Failed to send magic link to %s", mask_email(email))
        # Do not surface email errors to caller — link is in DB, user can retry.

    return {"detail": "If that address is registered, a sign-in link has been sent."}


@router.post("/verify")
@limiter.limit(RATE_LIMIT_AUTH_VERIFY)
async def verify_magic_link(
    request: Request,
    body: VerifyTokenBody,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Verify a magic-link token. Sets the session cookie on success; the
    token itself moves in the request body (was a query parameter) so it
    stops landing in access logs."""
    token = body.token
    try:
        user_id = verify_magic_token(token)
    except SignatureExpired:
        log.warning(
            "magic-link verify failed: expired", extra={"event": LOG_EVENT_AUTH_FAILED}
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MAGIC_LINK_EXPIRED,
        )
    except BadSignature:
        log.warning(
            "magic-link verify failed: bad-signature",
            extra={"event": LOG_EVENT_AUTH_FAILED},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MAGIC_LINK_INVALID,
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
        log.warning(
            "magic-link verify failed: already-used or not-found",
            extra={"event": LOG_EVENT_AUTH_FAILED},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MAGIC_LINK_CONSUMED,
        )

    # Same transaction as the link-consume UPDATE above, one shared commit below:
    # marks the account durably verified — a session token can only ever be
    # issued from here, so this is the one place that gates build_daily_feeds/
    # send_daily_digests on a real login having happened. Unconditional SET is
    # idempotent for a user who already verified before. Sharing the
    # transaction (rather than an intermediate commit) means a failure here
    # rolls back the link-consume too, instead of leaving the link durably
    # spent with the user never marked verified.
    user_result = await db.execute(
        update(User)
        .where(User.id == user_id)
        .values(email_verified=True)
        .returning(User.id, User.email, User.locale, User.session_token_version)
    )
    user_row = user_result.fetchone()
    await db.commit()

    if user_row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_USER_NOT_FOUND,
        )

    session_token = generate_session_token(user_row.id, user_row.session_token_version)
    set_session_cookie(
        response,
        name=SESSION_COOKIE_NAME,
        token=session_token,
        path=SESSION_COOKIE_PATH,
        ttl_seconds=settings.SESSION_TTL_DAYS * SECONDS_PER_DAY,
    )
    return {
        "user": {
            "id": user_row.id,
            "email": user_row.email,
            "locale": user_row.locale,
        },
    }


@router.post("/logout", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_LOGOUT)
async def logout(request: Request, response: Response) -> dict:
    """Sign out this device only: expires the session cookie without
    touching session_token_version, leaving every other device's session
    intact. The server-side counterpart "sign out" previously lacked — until
    now it was pure client-side localStorage.removeItem.

    Idempotent (OWASP audit F18): no auth dependency, so a session that's
    already expired/revoked still gets a 200 and its stale cookie cleared,
    instead of a 401 that leaves the dead cookie sitting in the browser."""
    clear_session_cookie(response, name=SESSION_COOKIE_NAME, path=SESSION_COOKIE_PATH)
    return {"detail": "Signed out."}


@router.post("/logout-all", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_LOGOUT_ALL)
async def logout_all(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Invalidate every session token issued so far ("log out everywhere") by
    bumping session_token_version — get_current_user rejects any token whose
    embedded "v" claim no longer matches the stored value, including the one
    used to make this very request. Also expires this device's cookie
    directly, rather than relying on the client to notice the next rejected
    request.

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
    clear_session_cookie(response, name=SESSION_COOKIE_NAME, path=SESSION_COOKIE_PATH)
    return {"detail": "Signed out of all devices."}


@router.get("/me")
@limiter.limit(RATE_LIMIT_BROWSE)
async def get_me(
    request: Request,
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
