"""Auth endpoints — magic-link request + verification + current-user."""

import logging
import secrets
from datetime import datetime, timezone

import httpx
import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, SignatureExpired
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.email import (
    notify_identity_linked,
    send_google_link_confirmation,
    send_magic_link,
)
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
    generate_google_link_binding_token,
    generate_magic_token,
    generate_oauth_state_token,
    generate_session_token,
    google_link_binding_matches,
    hash_token,
    magic_ttl_seconds,
    verify_magic_token,
    verify_oauth_state_token,
)
from app.config import settings
from app._generated.shared_constants import (
    AUTH_TRACK_USER,
    DEFAULT_USER_LOCALE,
    OAUTH_ERROR_DENIED,
    VALID_LOCALES,
)
from app.constants.auth import (
    DETAIL_MAGIC_LINK_SENT,
    DETAIL_SIGNED_OUT,
    DETAIL_SIGNED_OUT_ALL,
    ERROR_MAGIC_LINK_CONSUMED,
    ERROR_MAGIC_LINK_EXPIRED,
    ERROR_MAGIC_LINK_INVALID,
    ERROR_USER_NOT_FOUND,
    GOOGLE_CALLBACK_PUBLIC_PATH,
    GOOGLE_LINK_BINDING_COOKIE_NAME,
    GOOGLE_LINK_BINDING_COOKIE_PATH,
    GOOGLE_SIGNIN_OUTCOME_AUTO_LINKED,
    GOOGLE_SIGNIN_OUTCOME_CONFIRMATION_SENT,
    GOOGLE_SIGNIN_OUTCOME_EXISTING_LOGIN,
    GOOGLE_SIGNIN_OUTCOME_NEW_ACCOUNT,
    GOOGLE_SIGNIN_OUTCOME_UNVERIFIED_EMAIL,
    IDENTITY_PROVIDER_GOOGLE,
    OAUTH_ERROR_STATE_INVALID,
    OAUTH_ERROR_TOKEN_EXCHANGE_FAILED,
    OAUTH_ERROR_VERIFICATION_FAILED,
    OAUTH_STATE_COOKIE_NAME,
    OAUTH_STATE_COOKIE_PATH,
    SESSION_COOKIE_NAME,
    SESSION_COOKIE_PATH,
)
from app.constants.core import HOME_PATH, LOGIN_PATH, ONBOARDING_PATH, SECONDS_PER_DAY
from app.constants.http import HEADER_ACCEPT_LANGUAGE
from app.constants.log_events import (
    LOG_EVENT_AUTH_FAILED,
    LOG_EVENT_GOOGLE_SIGNIN,
    LOG_EVENT_GOOGLE_SIGNIN_DEGRADED,
    LOG_EVENT_IDENTITY_LINKED,
)
from app.constants.rate_limits import (
    RATE_LIMIT_AUTH_REQUEST_LINK,
    RATE_LIMIT_AUTH_VERIFY,
    RATE_LIMIT_BROWSE,
    RATE_LIMIT_GOOGLE_SIGNIN_CALLBACK,
    RATE_LIMIT_GOOGLE_SIGNIN_START,
    RATE_LIMIT_LOGOUT,
    RATE_LIMIT_LOGOUT_ALL,
)
from app.db import get_db
from app.models.users import AuthMagicLink, User, UserIdentity, UserPersona
from app.rate_limit import limiter
from app.routers.utils import (
    RequestLinkBody,
    VerifyTokenBody,
    build_google_redirect_uri,
    append_google_signin_result,
    build_oauth_error_redirect,
    clear_oauth_state_cookie,
    clear_session_cookie,
    recent_unused_link_exists,
    record_unverified_account_creation,
    serialize_user,
    set_oauth_state_cookie,
    set_session_cookie,
)
from app.auth.utils import mask_email

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


def _detect_locale(accept_language: str) -> str:
    """Pick the best supported locale from an Accept-Language header value."""
    for part in accept_language.replace(" ", "").split(","):
        lang = part.split(";")[0].split("-")[0].lower()
        if lang in VALID_LOCALES:
            return lang
    return DEFAULT_USER_LOCALE


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
            request.headers.get(HEADER_ACCEPT_LANGUAGE, "")
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
        return {"detail": DETAIL_MAGIC_LINK_SENT}

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
        await send_magic_link(email, signed_token, email_locale)
    except Exception:
        log.exception("Failed to send magic link to %s", mask_email(email))
        # Do not surface email errors to caller — link is in DB, user can retry.

    return {"detail": DETAIL_MAGIC_LINK_SENT}


@router.post("/verify")
@limiter.limit(RATE_LIMIT_AUTH_VERIFY)
async def verify_magic_link(
    request: Request,
    body: VerifyTokenBody,
    response: Response,
    db: AsyncSession = Depends(get_db),
    google_link_binding: str | None = Cookie(
        default=None, alias=GOOGLE_LINK_BINDING_COOKIE_NAME
    ),
) -> dict:
    """Verify a magic-link token. Sets the session cookie on success; the
    token itself moves in the request body (was a query parameter) so it
    stops landing in access logs.

    A Google-confirmation link (pending_google_sub set) only attaches that
    identity when the request carries the google_link_binding cookie for the
    same sub — i.e. it is opened in the browser that started the Google
    sign-in (OWASP audit #3). Anywhere else it is a plain sign-in: the
    address owner is signed in, no identity is linked."""
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
    # Also returns pending_google_sub (ADR 0002): set when this link was sent
    # to confirm a Google-identity link rather than to start a session.
    result = await db.execute(
        update(AuthMagicLink)
        .where(
            AuthMagicLink.token_hash == token_hash,
            AuthMagicLink.user_id == user_id,
            AuthMagicLink.used_at.is_(None),
            AuthMagicLink.expires_at > now,
        )
        .values(used_at=now)
        .returning(AuthMagicLink.user_id, AuthMagicLink.pending_google_sub)
    )
    row = result.fetchone()
    if row is None:
        log.warning(
            "magic-link verify failed: already-used or not-found",
            extra={"event": LOG_EVENT_AUTH_FAILED},
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MAGIC_LINK_CONSUMED,
        )
    pending_google_sub = row[1]

    # Same transaction as the link-consume UPDATE above, one shared commit below:
    # marks the account durably verified — a session token can only ever be
    # issued from here or from the Google-sign-in linking gate (ADR 0002:
    # google_callback's authoritative/absorption branches), so email_verified
    # now has two writers, not one. Unconditional SET is idempotent for a user
    # who already verified before. Sharing the transaction (rather than an
    # intermediate commit) means a failure here rolls back the link-consume
    # too, instead of leaving the link durably spent with the user never
    # marked verified.
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

    if pending_google_sub is not None:
        # ADR 0002 — this magic link was sent to confirm a pending Google
        # identity link (non-authoritative address), not to start a session
        # directly. Create the link now that control of the address is proven
        # — and only in the browser that started the Google sign-in (OWASP
        # audit #3); elsewhere this is a plain sign-in.
        if google_link_binding_matches(
            google_link_binding, sub=pending_google_sub, track=AUTH_TRACK_USER
        ):
            try:
                db.add(
                    UserIdentity(
                        user_id=user_row.id,
                        provider=IDENTITY_PROVIDER_GOOGLE,
                        provider_sub=pending_google_sub,
                    )
                )
                await db.commit()
                log.info(
                    "user identity linked via confirmation: user_id=%s",
                    user_row.id,
                    extra={"event": LOG_EVENT_IDENTITY_LINKED, "provider": IDENTITY_PROVIDER_GOOGLE},
                )
                await notify_identity_linked(user_row.email, user_row.locale)
            except IntegrityError:
                # Already linked by a concurrent request (or a stale/reused
                # sub) — not this request's problem to surface; the session
                # still mints.
                await db.rollback()
        else:
            log.warning(
                "google identity NOT linked: confirmation link opened without "
                "the matching browser binding user_id=%s",
                user_row.id,
                extra={"event": LOG_EVENT_AUTH_FAILED},
            )
        clear_session_cookie(
            response,
            name=GOOGLE_LINK_BINDING_COOKIE_NAME,
            path=GOOGLE_LINK_BINDING_COOKIE_PATH,
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
    return {"detail": DETAIL_SIGNED_OUT}


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
    return {"detail": DETAIL_SIGNED_OUT_ALL}


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


# ---------------------------------------------------------------------------
# Google sign-in (ADR 0002) — consumer track. Mirrors organizer_auth.py's
# organizer-track implementation; see that module's docstrings for the
# shared PKCE/state-cookie/linking-gate rationale. Divergences from the
# organizer track are called out inline where they occur.
# ---------------------------------------------------------------------------


def _google_redirect_uri() -> str:
    """Browser-facing callback URL — must match what's registered with
    Google and what the state cookie is scoped to (OAUTH_STATE_COOKIE_PATH)."""
    return build_google_redirect_uri(GOOGLE_CALLBACK_PUBLIC_PATH)


def _set_oauth_state_cookie(response: Response, token: str) -> None:
    set_oauth_state_cookie(
        response,
        token,
        cookie_name=OAUTH_STATE_COOKIE_NAME,
        cookie_path=OAUTH_STATE_COOKIE_PATH,
    )


def _clear_oauth_state_cookie(response: Response) -> None:
    clear_oauth_state_cookie(
        response, cookie_name=OAUTH_STATE_COOKIE_NAME, cookie_path=OAUTH_STATE_COOKIE_PATH
    )


def _error_redirect(error_code: str) -> RedirectResponse:
    """Every callback failure path lands here: a 302 back to the login page
    carrying an error code, never a 500 — the state cookie (single-use) is
    cleared regardless of outcome."""
    return build_oauth_error_redirect(
        error_code,
        login_path=LOGIN_PATH,
        cookie_name=OAUTH_STATE_COOKIE_NAME,
        cookie_path=OAUTH_STATE_COOKIE_PATH,
    )


@router.get("/google/start")
@limiter.limit(RATE_LIMIT_GOOGLE_SIGNIN_START)
async def start_google_signin(request: Request) -> RedirectResponse:
    """Kick off the consumer-track Google sign-in flow (ADR 0002). 404 when
    the flag is off — the endpoint doesn't exist for an outside prober, not
    just "disabled"."""
    if not settings.GOOGLE_SIGNIN_CONSUMER_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    code_verifier, code_challenge = generate_pkce_pair()
    state = generate_state()
    auth_url = build_authorization_url(
        state=state, code_challenge=code_challenge, redirect_uri=_google_redirect_uri()
    )
    response = RedirectResponse(auth_url, status_code=status.HTTP_302_FOUND)
    _set_oauth_state_cookie(
        response, generate_oauth_state_token(state, code_verifier, track=AUTH_TRACK_USER)
    )
    return response


async def _get_or_create_user_for_google(db: AsyncSession, email: str) -> User:
    """Same unverified-row-creation shape as _get_or_create_user, split out so
    the Google linking-gate paths that need it don't have to carry a
    locale/Accept-Language-unrelated signature. Used only where a magic link
    is about to be sent (confirmation branch) — the metric this trips
    (record_unverified_account_creation) exists specifically to bound
    magic-link email volume, which is what's happening here too."""
    user = await db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, locale=DEFAULT_USER_LOCALE)
        db.add(user)
        await db.flush()
        log.info("auth: new unverified user row created email=%s", mask_email(email))
        record_unverified_account_creation()
    return user


async def _send_google_confirmation_link(db: AsyncSession, user: User, sub: str) -> None:
    """Send a confirmation magic link that, once used, absorbs `sub` into
    user_identities (see verify_magic_link above) rather than starting a
    session directly — ADR 0002's non-authoritative-address gate."""
    if await recent_unused_link_exists(
        db,
        AuthMagicLink,
        AuthMagicLink.user_id,
        user.id,
        magic_ttl_seconds(),
        # Scoped to a pending link for this exact sub — an unrelated unused
        # plain sign-in link (or a pending link for a different Google
        # account) must never suppress this send.
        extra_predicate=AuthMagicLink.pending_google_sub == sub,
    ):
        return

    signed_token, token_hash, expires_at = generate_magic_token(user.id)
    db.add(
        AuthMagicLink(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
            pending_google_sub=sub,
        )
    )
    await db.commit()

    try:
        await send_google_link_confirmation(user.email, signed_token, user.locale)
    except Exception:
        log.exception(
            "Failed to send Google-confirmation link to %s", mask_email(user.email)
        )


async def _link_new_google_identity(
    db: AsyncSession, user: User, sub: str, *, success_outcome: str
) -> tuple[str, User | None]:
    """Flip email_verified, insert the UserIdentity row, and commit in one
    transaction, falling back to the concurrent winner's row on a unique-
    constraint collision — shared by the unverified-absorption and
    existing/new-authoritative branches below, which differ only in what
    outcome to report on the happy path (``success_outcome``)."""
    user.email_verified = True
    db.add(
        UserIdentity(user_id=user.id, provider=IDENTITY_PROVIDER_GOOGLE, provider_sub=sub)
    )
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent callback for the same Google account (double-click,
        # two tabs) won the identity-link race first — never surface a 500
        # here (docs/security.md "Auth", callback invariant). Roll back (which also
        # undoes this request's own uncommitted User insert/email_verified
        # flip, if any — the winning request's row is what persists) and
        # fall back to that winner's identity.
        await db.rollback()
        existing_identity = await db.scalar(
            select(UserIdentity).where(
                UserIdentity.provider == IDENTITY_PROVIDER_GOOGLE,
                UserIdentity.provider_sub == sub,
            )
        )
        winner = (
            await db.get(User, existing_identity.user_id)
            if existing_identity is not None
            else None
        )
        return GOOGLE_SIGNIN_OUTCOME_EXISTING_LOGIN, winner
    log.info(
        "user identity linked: user_id=%s",
        user.id,
        extra={"event": LOG_EVENT_IDENTITY_LINKED, "provider": IDENTITY_PROVIDER_GOOGLE},
    )
    return success_outcome, user


async def _apply_google_linking_gate(
    db: AsyncSession, identity: GoogleIdentity
) -> tuple[str, User | None]:
    """ADR 0002's linking gate — consumer-track branches. Returns (outcome,
    user) — user is None only for GOOGLE_SIGNIN_OUTCOME_CONFIRMATION_SENT,
    where no session is minted this request.

    Diverges from organizer_auth.py::_apply_google_linking_gate only by
    flipping User.email_verified on every auto-link/absorb path (Organizer
    has nothing analogous to flip)."""
    existing_identity = await db.scalar(
        select(UserIdentity).where(
            UserIdentity.provider == IDENTITY_PROVIDER_GOOGLE,
            UserIdentity.provider_sub == identity["sub"],
        )
    )
    if existing_identity is not None:
        user = await db.get(User, existing_identity.user_id)
        return GOOGLE_SIGNIN_OUTCOME_EXISTING_LOGIN, user

    existing_user = await db.scalar(select(User).where(User.email == identity["email"]))
    authoritative = is_authoritative_identity(identity)

    if authoritative:
        is_new = existing_user is None
        user = existing_user or User(
            email=identity["email"], locale=DEFAULT_USER_LOCALE
        )
        if is_new:
            db.add(user)
            await db.flush()
        return await _link_new_google_identity(
            db,
            user,
            identity["sub"],
            success_outcome=(
                GOOGLE_SIGNIN_OUTCOME_NEW_ACCOUNT if is_new else GOOGLE_SIGNIN_OUTCOME_AUTO_LINKED
            ),
        )

    # Google itself says it hasn't verified this address — nothing to confirm
    # and no reason to email a third party (OWASP audit #3): no row, no link.
    if not identity["email_verified"]:
        return GOOGLE_SIGNIN_OUTCOME_UNVERIFIED_EMAIL, None

    # Non-authoritative address — Google's word on `email_verified` isn't
    # trusted enough to auto-link (ADR 0002). Prove control via a
    # confirmation magic link before any identity row is created.
    user = existing_user or await _get_or_create_user_for_google(db, identity["email"])
    await db.commit()
    await _send_google_confirmation_link(db, user, identity["sub"])
    return GOOGLE_SIGNIN_OUTCOME_CONFIRMATION_SENT, None


@router.get("/google/callback")
@limiter.limit(RATE_LIMIT_GOOGLE_SIGNIN_CALLBACK)
async def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    oauth_state: str | None = Cookie(default=None, alias=OAUTH_STATE_COOKIE_NAME),
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    if not settings.GOOGLE_SIGNIN_CONSUMER_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if error:
        log.warning(
            "google sign-in denied: %s", error, extra={"event": LOG_EVENT_AUTH_FAILED}
        )
        return _error_redirect(OAUTH_ERROR_DENIED)

    if not oauth_state or not code or not state:
        log.warning(
            "google sign-in failed: missing state cookie/code/state",
            extra={"event": LOG_EVENT_AUTH_FAILED},
        )
        return _error_redirect(OAUTH_ERROR_STATE_INVALID)

    try:
        state_payload = verify_oauth_state_token(oauth_state, track=AUTH_TRACK_USER)
    except (BadSignature, SignatureExpired):
        log.warning(
            "google sign-in failed: bad/expired state token",
            extra={"event": LOG_EVENT_AUTH_FAILED},
        )
        return _error_redirect(OAUTH_ERROR_STATE_INVALID)

    if not secrets.compare_digest(state_payload["state"], state):
        log.warning(
            "google sign-in failed: state mismatch",
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
            "google sign-in: token exchange failed",
            extra={"event": LOG_EVENT_GOOGLE_SIGNIN_DEGRADED, "track": AUTH_TRACK_USER},
        )
        return _error_redirect(OAUTH_ERROR_TOKEN_EXCHANGE_FAILED)

    try:
        identity = verify_google_id_token(id_token)
    except jwt.PyJWKClientError:
        # JWKS fetch/network failure — an upstream degradation, not a
        # rejected caller.
        log.warning(
            "google sign-in: JWKS fetch failed",
            extra={"event": LOG_EVENT_GOOGLE_SIGNIN_DEGRADED, "track": AUTH_TRACK_USER},
        )
        return _error_redirect(OAUTH_ERROR_TOKEN_EXCHANGE_FAILED)
    except jwt.PyJWTError:
        log.warning(
            "google sign-in failed: id token verification",
            extra={"event": LOG_EVENT_AUTH_FAILED},
        )
        return _error_redirect(OAUTH_ERROR_VERIFICATION_FAILED)

    outcome, user = await _apply_google_linking_gate(db, identity)
    log.info(
        "google sign-in: outcome=%s",
        outcome,
        extra={"event": LOG_EVENT_GOOGLE_SIGNIN, "track": AUTH_TRACK_USER, "outcome": outcome},
    )

    if outcome == GOOGLE_SIGNIN_OUTCOME_UNVERIFIED_EMAIL:
        return _error_redirect(OAUTH_ERROR_VERIFICATION_FAILED)

    if user is None:
        response = RedirectResponse(
            f"{settings.FRONTEND_URL}{LOGIN_PATH}", status_code=status.HTTP_302_FOUND
        )
        # Bind the confirmation link to this browser (OWASP audit #3): the
        # emailed link only attaches this Google identity when opened where
        # the Google sign-in was started.
        set_session_cookie(
            response,
            name=GOOGLE_LINK_BINDING_COOKIE_NAME,
            token=generate_google_link_binding_token(identity["sub"], AUTH_TRACK_USER),
            path=GOOGLE_LINK_BINDING_COOKIE_PATH,
            ttl_seconds=magic_ttl_seconds(),
        )
    else:
        if outcome == GOOGLE_SIGNIN_OUTCOME_AUTO_LINKED:
            await notify_identity_linked(user.email, user.locale)
        # A brand-new account has no personas yet — send it through onboarding
        # rather than straight to the (empty) feed; every other outcome lands
        # on the feed, mirroring the plain magic-link flow's AuthVerify.tsx.
        destination = (
            ONBOARDING_PATH if outcome == GOOGLE_SIGNIN_OUTCOME_NEW_ACCOUNT else HOME_PATH
        )
        session_token = generate_session_token(user.id, user.session_token_version)
        response = RedirectResponse(
            append_google_signin_result(
                f"{settings.FRONTEND_URL}{destination}", AUTH_TRACK_USER
            ),
            status_code=status.HTTP_302_FOUND,
        )
        set_session_cookie(
            response,
            name=SESSION_COOKIE_NAME,
            token=session_token,
            path=SESSION_COOKIE_PATH,
            ttl_seconds=settings.SESSION_TTL_DAYS * SECONDS_PER_DAY,
        )

    _clear_oauth_state_cookie(response)
    return response
