"""Organizer auth endpoints — magic-link request + verification + current-organizer.

A parallel track to app/routers/auth.py's consumer auth: separate account
table, separate magic-link table, distinct token salts (app/auth/tokens.py)
so a user token and an organizer token can never be confused for one another.
"""

import logging
import secrets
from datetime import datetime, timezone

import httpx
import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.email import send_magic_link
from app.auth.google_oauth import (
    GoogleIdentity,
    GoogleTokenExchangeError,
    build_authorization_url,
    exchange_code_for_id_token,
    generate_pkce_pair,
    generate_state,
    is_authoritative_identity,
    verify_google_id_token,
)
from app.auth.tokens import (
    generate_oauth_state_token,
    generate_organizer_magic_token,
    generate_organizer_session_token,
    hash_token,
    organizer_magic_ttl_seconds,
    verify_oauth_state_token,
    verify_organizer_magic_token,
    verify_organizer_session_token,
)
from app.config import settings
from app.constants import (
    AUTH_TRACK_ORGANIZER,
    DEFAULT_USER_LOCALE,
    DETAIL_MAGIC_LINK_SENT,
    DETAIL_SIGNED_OUT,
    DETAIL_SIGNED_OUT_ALL,
    ERROR_MAGIC_LINK_CONSUMED,
    ERROR_MAGIC_LINK_EXPIRED,
    ERROR_MAGIC_LINK_INVALID,
    ERROR_MISSING_SESSION_COOKIE,
    ERROR_ORGANIZER_NOT_FOUND,
    ERROR_SESSION_INVALID,
    ERROR_SESSION_REVOKED,
    GOOGLE_SIGNIN_OUTCOME_AUTO_LINKED,
    GOOGLE_SIGNIN_OUTCOME_CONFIRMATION_SENT,
    GOOGLE_SIGNIN_OUTCOME_EXISTING_LOGIN,
    GOOGLE_SIGNIN_OUTCOME_NEW_ACCOUNT,
    IDENTITY_PROVIDER_GOOGLE,
    LOG_EVENT_AUTH_FAILED,
    LOG_EVENT_GOOGLE_SIGNIN,
    LOG_EVENT_GOOGLE_SIGNIN_DEGRADED,
    LOG_EVENT_IDENTITY_LINKED,
    OAUTH_ERROR_DENIED,
    OAUTH_ERROR_STATE_INVALID,
    OAUTH_ERROR_TOKEN_EXCHANGE_FAILED,
    OAUTH_ERROR_VERIFICATION_FAILED,
    ORGANIZER_AUTH_VERIFY_PATH,
    ORGANIZER_DASHBOARD_PATH,
    ORGANIZER_GOOGLE_CALLBACK_PUBLIC_PATH,
    ORGANIZER_LOGIN_PATH,
    ORGANIZER_OAUTH_STATE_COOKIE_NAME,
    ORGANIZER_OAUTH_STATE_COOKIE_PATH,
    ORGANIZER_SESSION_COOKIE_NAME,
    ORGANIZER_SESSION_COOKIE_PATH,
    ORGANIZER_SESSION_TTL_DAYS,
    RATE_LIMIT_AUTH_REQUEST_LINK,
    RATE_LIMIT_AUTH_VERIFY,
    RATE_LIMIT_GOOGLE_SIGNIN_CALLBACK,
    RATE_LIMIT_GOOGLE_SIGNIN_START,
    RATE_LIMIT_LOGOUT,
    RATE_LIMIT_LOGOUT_ALL,
    SECONDS_PER_DAY,
    VALID_LOCALES,
)
from app.db import get_db
from app.models.models import Organizer, OrganizerIdentity, OrganizerMagicLink
from app.rate_limit import limiter
from app.routers.utils import (
    RequestLinkBody,
    VerifyTokenBody,
    build_google_redirect_uri,
    append_google_signin_result,
    build_oauth_error_redirect,
    clear_oauth_state_cookie,
    clear_session_cookie,
    get_or_create_organizer,
    mask_email,
    recent_unused_link_exists,
    set_oauth_state_cookie,
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
            email,
            signed_token,
            email_locale,
            verify_path=ORGANIZER_AUTH_VERIFY_PATH,
        )
    except Exception:
        log.exception("Failed to send organizer magic link to %s", mask_email(email))
        # Do not surface email errors to caller — link is in DB, organizer can retry.

    return {"detail": DETAIL_MAGIC_LINK_SENT}


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
    # Also returns pending_google_sub (ADR 0002): set when this link was sent
    # to confirm a Google-identity link rather than to start a session.
    result = await db.execute(
        update(OrganizerMagicLink)
        .where(
            OrganizerMagicLink.token_hash == token_hash,
            OrganizerMagicLink.organizer_id == organizer_id,
            OrganizerMagicLink.used_at.is_(None),
            OrganizerMagicLink.expires_at > now,
        )
        .values(used_at=now)
        .returning(OrganizerMagicLink.organizer_id, OrganizerMagicLink.pending_google_sub)
    )
    row = result.fetchone()
    if row is None:
        log.warning(
            "organizer magic-link verify failed: already-used or not-found",
            extra={"event": LOG_EVENT_AUTH_FAILED},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MAGIC_LINK_CONSUMED,
        )
    pending_google_sub = row[1]

    await db.commit()

    organizer = await db.get(Organizer, organizer_id)
    if organizer is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_ORGANIZER_NOT_FOUND,
        )

    if pending_google_sub is not None:
        # ADR 0002 — this magic link was sent to confirm a pending Google
        # identity link (non-authoritative address), not to start a session
        # directly. Create the link now that control of the address is proven.
        try:
            db.add(
                OrganizerIdentity(
                    organizer_id=organizer.id,
                    provider=IDENTITY_PROVIDER_GOOGLE,
                    provider_sub=pending_google_sub,
                )
            )
            await db.commit()
            log.info(
                "organizer identity linked via confirmation: organizer_id=%s",
                organizer.id,
                extra={"event": LOG_EVENT_IDENTITY_LINKED, "provider": IDENTITY_PROVIDER_GOOGLE},
            )
        except IntegrityError:
            # Already linked by a concurrent request (or a stale/reused sub) —
            # not this request's problem to surface; the session still mints.
            await db.rollback()

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
    return {
        "organizer": {
            "id": organizer.id,
            "email": organizer.email,
            "locale": organizer.locale,
        },
    }


@router.post("/logout", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_LOGOUT)
async def organizer_logout(request: Request, response: Response) -> dict:
    """Sign out this device only. Mirrors auth.py::logout — expires the
    cookie without touching session_token_version. Idempotent (OWASP audit
    F18): no auth dependency, so an already-expired/revoked session still
    gets a 200 with its stale cookie cleared, not a 401."""
    clear_session_cookie(
        response, name=ORGANIZER_SESSION_COOKIE_NAME, path=ORGANIZER_SESSION_COOKIE_PATH
    )
    return {"detail": DETAIL_SIGNED_OUT}


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
    return {"detail": DETAIL_SIGNED_OUT_ALL}


def _google_redirect_uri() -> str:
    """Browser-facing callback URL — must match what's registered with
    Google and what the state cookie is scoped to (ORGANIZER_OAUTH_STATE_COOKIE_PATH)."""
    return build_google_redirect_uri(ORGANIZER_GOOGLE_CALLBACK_PUBLIC_PATH)


def _set_oauth_state_cookie(response: Response, token: str) -> None:
    set_oauth_state_cookie(
        response,
        token,
        cookie_name=ORGANIZER_OAUTH_STATE_COOKIE_NAME,
        cookie_path=ORGANIZER_OAUTH_STATE_COOKIE_PATH,
    )


def _clear_oauth_state_cookie(response: Response) -> None:
    clear_oauth_state_cookie(
        response,
        cookie_name=ORGANIZER_OAUTH_STATE_COOKIE_NAME,
        cookie_path=ORGANIZER_OAUTH_STATE_COOKIE_PATH,
    )


def _error_redirect(error_code: str) -> RedirectResponse:
    """Every callback failure path lands here: a 302 back to the organizer
    login page carrying an error code, never a 500 — the state cookie (single-
    use) is cleared regardless of outcome."""
    return build_oauth_error_redirect(
        error_code,
        login_path=ORGANIZER_LOGIN_PATH,
        cookie_name=ORGANIZER_OAUTH_STATE_COOKIE_NAME,
        cookie_path=ORGANIZER_OAUTH_STATE_COOKIE_PATH,
    )


@router.get("/google/start")
@limiter.limit(RATE_LIMIT_GOOGLE_SIGNIN_START)
async def start_organizer_google_signin(request: Request) -> RedirectResponse:
    """Kick off the organizer-track Google sign-in flow (ADR 0002). 404 when
    the flag is off — the endpoint doesn't exist for an outside prober, not
    just "disabled"."""
    if not settings.GOOGLE_SIGNIN_ORGANIZER_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    code_verifier, code_challenge = generate_pkce_pair()
    state = generate_state()
    auth_url = build_authorization_url(
        state=state, code_challenge=code_challenge, redirect_uri=_google_redirect_uri()
    )
    response = RedirectResponse(auth_url, status_code=status.HTTP_302_FOUND)
    _set_oauth_state_cookie(
        response, generate_oauth_state_token(state, code_verifier, track=AUTH_TRACK_ORGANIZER)
    )
    return response


async def _get_or_create_organizer_for_google(db: AsyncSession, email: str) -> Organizer:
    """Same unverified-row-creation shape as get_or_create_organizer, split
    out so the Google linking-gate paths that need it don't have to carry a
    locale/cooldown-unrelated signature. Used only where a magic link is
    about to be sent (confirmation branch) — the metric this trips
    (record_unverified_account_creation) exists specifically to bound
    magic-link email volume, which is what's happening here too."""
    return await get_or_create_organizer(db, email, None)


async def _send_google_confirmation_link(
    db: AsyncSession, organizer: Organizer, sub: str
) -> None:
    """Send a confirmation magic link that, once used, absorbs `sub` into
    organizer_identities (see verify_organizer_magic_link above) rather than
    starting a session directly — ADR 0002's non-authoritative-address gate."""
    if await recent_unused_link_exists(
        db,
        OrganizerMagicLink,
        OrganizerMagicLink.organizer_id,
        organizer.id,
        organizer_magic_ttl_seconds(),
        # Scoped to a pending link for this exact sub — an unrelated unused
        # plain sign-in link (or a pending link for a different Google
        # account) must never suppress this send.
        extra_predicate=OrganizerMagicLink.pending_google_sub == sub,
    ):
        return

    signed_token, token_hash, expires_at = generate_organizer_magic_token(organizer.id)
    db.add(
        OrganizerMagicLink(
            organizer_id=organizer.id,
            token_hash=token_hash,
            expires_at=expires_at,
            pending_google_sub=sub,
        )
    )
    await db.commit()

    try:
        await send_magic_link(
            organizer.email,
            signed_token,
            organizer.locale,
            verify_path=ORGANIZER_AUTH_VERIFY_PATH,
        )
    except Exception:
        log.exception(
            "Failed to send organizer Google-confirmation link to %s",
            mask_email(organizer.email),
        )


async def _apply_google_linking_gate(
    db: AsyncSession, identity: GoogleIdentity
) -> tuple[str, Organizer | None]:
    """ADR 0002's linking gate. Returns (outcome, organizer) — organizer is
    None only for GOOGLE_SIGNIN_OUTCOME_CONFIRMATION_SENT, where no session
    is minted this request."""
    existing_identity = await db.scalar(
        select(OrganizerIdentity).where(
            OrganizerIdentity.provider == IDENTITY_PROVIDER_GOOGLE,
            OrganizerIdentity.provider_sub == identity["sub"],
        )
    )
    if existing_identity is not None:
        organizer = await db.get(Organizer, existing_identity.organizer_id)
        return GOOGLE_SIGNIN_OUTCOME_EXISTING_LOGIN, organizer

    existing_organizer = await db.scalar(
        select(Organizer).where(Organizer.email == identity["email"])
    )
    authoritative = is_authoritative_identity(identity)

    if authoritative:
        is_new = existing_organizer is None
        organizer = existing_organizer or Organizer(
            email=identity["email"], locale=DEFAULT_USER_LOCALE
        )
        if is_new:
            db.add(organizer)
            await db.flush()
        db.add(
            OrganizerIdentity(
                organizer_id=organizer.id,
                provider=IDENTITY_PROVIDER_GOOGLE,
                provider_sub=identity["sub"],
            )
        )
        try:
            await db.commit()
        except IntegrityError:
            # A concurrent callback for the same Google account (double-click,
            # two tabs) won the identity-link race first — never surface a
            # 500 here (docs/security.md's callback invariant). Roll back
            # (which also undoes this request's own uncommitted Organizer
            # insert, if any — the winning request's row is what persists)
            # and fall back to that winner's identity.
            await db.rollback()
            existing_identity = await db.scalar(
                select(OrganizerIdentity).where(
                    OrganizerIdentity.provider == IDENTITY_PROVIDER_GOOGLE,
                    OrganizerIdentity.provider_sub == identity["sub"],
                )
            )
            organizer = (
                await db.get(Organizer, existing_identity.organizer_id)
                if existing_identity is not None
                else None
            )
            return GOOGLE_SIGNIN_OUTCOME_EXISTING_LOGIN, organizer
        log.info(
            "organizer identity linked: organizer_id=%s new_account=%s",
            organizer.id,
            is_new,
            extra={"event": LOG_EVENT_IDENTITY_LINKED, "provider": IDENTITY_PROVIDER_GOOGLE},
        )
        outcome = (
            GOOGLE_SIGNIN_OUTCOME_NEW_ACCOUNT if is_new else GOOGLE_SIGNIN_OUTCOME_AUTO_LINKED
        )
        return outcome, organizer

    # Non-authoritative address — Google's word on `email_verified` isn't
    # trusted enough to auto-link (ADR 0002). Prove control via a
    # confirmation magic link before any identity row is created.
    organizer = existing_organizer or await _get_or_create_organizer_for_google(
        db, identity["email"]
    )
    await db.commit()
    await _send_google_confirmation_link(db, organizer, identity["sub"])
    return GOOGLE_SIGNIN_OUTCOME_CONFIRMATION_SENT, None


@router.get("/google/callback")
@limiter.limit(RATE_LIMIT_GOOGLE_SIGNIN_CALLBACK)
async def organizer_google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    organizer_oauth_state: str | None = Cookie(
        default=None, alias=ORGANIZER_OAUTH_STATE_COOKIE_NAME
    ),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    if not settings.GOOGLE_SIGNIN_ORGANIZER_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if error:
        log.warning(
            "organizer google sign-in denied: %s", error, extra={"event": LOG_EVENT_AUTH_FAILED}
        )
        return _error_redirect(OAUTH_ERROR_DENIED)

    if not organizer_oauth_state or not code or not state:
        log.warning(
            "organizer google sign-in failed: missing state cookie/code/state",
            extra={"event": LOG_EVENT_AUTH_FAILED},
        )
        return _error_redirect(OAUTH_ERROR_STATE_INVALID)

    try:
        state_payload = verify_oauth_state_token(organizer_oauth_state, track=AUTH_TRACK_ORGANIZER)
    except (BadSignature, SignatureExpired):
        log.warning(
            "organizer google sign-in failed: bad/expired state token",
            extra={"event": LOG_EVENT_AUTH_FAILED},
        )
        return _error_redirect(OAUTH_ERROR_STATE_INVALID)

    if not secrets.compare_digest(state_payload["state"], state):
        log.warning(
            "organizer google sign-in failed: state mismatch",
            extra={"event": LOG_EVENT_AUTH_FAILED},
        )
        return _error_redirect(OAUTH_ERROR_STATE_INVALID)

    try:
        id_token = await exchange_code_for_id_token(
            code=code,
            code_verifier=state_payload["code_verifier"],
            redirect_uri=_google_redirect_uri(),
        )
    except (httpx.HTTPError, GoogleTokenExchangeError):
        log.warning(
            "organizer google sign-in: token exchange failed",
            extra={"event": LOG_EVENT_GOOGLE_SIGNIN_DEGRADED, "track": "organizer"},
        )
        return _error_redirect(OAUTH_ERROR_TOKEN_EXCHANGE_FAILED)

    try:
        identity = verify_google_id_token(id_token)
    except jwt.PyJWKClientError:
        # JWKS fetch/network failure — an upstream degradation, not a
        # rejected caller.
        log.warning(
            "organizer google sign-in: JWKS fetch failed",
            extra={"event": LOG_EVENT_GOOGLE_SIGNIN_DEGRADED, "track": "organizer"},
        )
        return _error_redirect(OAUTH_ERROR_TOKEN_EXCHANGE_FAILED)
    except jwt.PyJWTError:
        log.warning(
            "organizer google sign-in failed: id token verification",
            extra={"event": LOG_EVENT_AUTH_FAILED},
        )
        return _error_redirect(OAUTH_ERROR_VERIFICATION_FAILED)

    outcome, organizer = await _apply_google_linking_gate(db, identity)
    log.info(
        "organizer google sign-in: outcome=%s",
        outcome,
        extra={"event": LOG_EVENT_GOOGLE_SIGNIN, "track": "organizer", "outcome": outcome},
    )

    if organizer is None:
        response = RedirectResponse(
            f"{settings.FRONTEND_URL}{ORGANIZER_LOGIN_PATH}", status_code=status.HTTP_302_FOUND
        )
    else:
        session_token = generate_organizer_session_token(
            organizer.id, organizer.session_token_version
        )
        response = RedirectResponse(
            append_google_signin_result(
                f"{settings.FRONTEND_URL}{ORGANIZER_DASHBOARD_PATH}", AUTH_TRACK_ORGANIZER
            ),
            status_code=status.HTTP_302_FOUND,
        )
        set_session_cookie(
            response,
            name=ORGANIZER_SESSION_COOKIE_NAME,
            token=session_token,
            path=ORGANIZER_SESSION_COOKIE_PATH,
            ttl_seconds=ORGANIZER_SESSION_TTL_DAYS * SECONDS_PER_DAY,
        )

    _clear_oauth_state_cookie(response)
    return response
