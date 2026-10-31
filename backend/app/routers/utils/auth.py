"""Magic-link, session-cookie and OAuth helpers shared by the consumer and organizer auth tracks."""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.auth.tokens import oauth_state_ttl_seconds
from app.config import settings
from app._generated.shared_constants import (
    DEFAULT_USER_LOCALE,
    GOOGLE_SIGNIN_RESULT_QUERY_PARAM,
    OAUTH_ERROR_QUERY_PARAM,
)
from app.constants.auth import (
    IDENTITY_PROVIDER_GOOGLE,
    MAGIC_LINK_RESEND_COOLDOWN_SECONDS,
    OAUTH_STATE_COOKIE_SAMESITE,
    SESSION_COOKIE_HTTPONLY,
    SESSION_COOKIE_SAMESITE,
    SESSION_COOKIE_SECURE,
    UNVERIFIED_ACCOUNT_DAILY_BUDGET,
)
from app.constants.core import TALLINN_TZ
from app.constants.log_events import (
    LOG_EVENT_UNVERIFIED_ACCOUNT_BUDGET_EXCEEDED,
)
from app.auth.utils import mask_email
from app.models.organizers import Organizer, OrganizerIdentity
from app.models.users import UserIdentity

log = logging.getLogger(__name__)


class RequestLinkBody(BaseModel):
    """Shared magic-link request body — consumer (routers/auth.py) and
    organizer (routers/organizer_auth.py) tracks use the identical shape."""

    email: EmailStr
    locale: str | None = None


class VerifyTokenBody(BaseModel):
    """Shared /verify request body — the magic-link token moves from a query
    parameter to the body so it stops landing in server access logs (Cloudflare
    edge, Render). Identical shape for both auth tracks, mirroring
    RequestLinkBody."""

    token: str


def set_session_cookie(
    response: Response, *, name: str, token: str, path: str, ttl_seconds: int
) -> None:
    """Set a hardened session cookie — shared by the consumer, organizer, and
    admin /verify|/login endpoints. Secure is unconditional (never gated on
    APP_ENV): see docs/adr/0001-session-tokens-in-httponly-cookies.md."""
    response.set_cookie(
        key=name,
        value=token,
        max_age=ttl_seconds,
        path=path,
        secure=SESSION_COOKIE_SECURE,
        httponly=SESSION_COOKIE_HTTPONLY,
        samesite=SESSION_COOKIE_SAMESITE,
    )


def clear_session_cookie(response: Response, *, name: str, path: str) -> None:
    """Expire a session cookie (sign-out and logout-all). Attributes must
    match set_session_cookie's for the browser to actually replace/clear the
    cookie rather than setting a second, distinct one."""
    response.delete_cookie(
        key=name,
        path=path,
        secure=SESSION_COOKIE_SECURE,
        httponly=SESSION_COOKIE_HTTPONLY,
        samesite=SESSION_COOKIE_SAMESITE,
    )


def build_google_redirect_uri(callback_path: str) -> str:
    """Browser-facing Google OAuth callback URL — must match what's
    registered with Google and what the state cookie is scoped to. Shared by
    both auth tracks (auth.py's GOOGLE_CALLBACK_PUBLIC_PATH, organizer_auth.py's
    ORGANIZER_GOOGLE_CALLBACK_PUBLIC_PATH)."""
    return f"{settings.FRONTEND_URL}{callback_path}"


def set_oauth_state_cookie(
    response: Response, token: str, *, cookie_name: str, cookie_path: str
) -> None:
    """Set the PKCE state cookie for a Google OAuth start — shared by both
    auth tracks, each passing its own track-scoped cookie name/path."""
    response.set_cookie(
        key=cookie_name,
        value=token,
        max_age=oauth_state_ttl_seconds(),
        path=cookie_path,
        secure=SESSION_COOKIE_SECURE,
        httponly=SESSION_COOKIE_HTTPONLY,
        samesite=OAUTH_STATE_COOKIE_SAMESITE,
    )


def clear_oauth_state_cookie(
    response: Response, *, cookie_name: str, cookie_path: str
) -> None:
    """Expire the PKCE state cookie (single-use). Attributes must match
    set_oauth_state_cookie's for the browser to actually clear it."""
    response.delete_cookie(
        key=cookie_name,
        path=cookie_path,
        secure=SESSION_COOKIE_SECURE,
        httponly=SESSION_COOKIE_HTTPONLY,
        samesite=OAUTH_STATE_COOKIE_SAMESITE,
    )


def append_google_signin_result(url: str, track: str) -> str:
    """Tag a Google OAuth callback's success redirect with which auth track
    signed in, so the frontend can write that track's signed-in localStorage
    hint before the router's first render — a server-side redirect runs no
    app JS between cookie-set and the route guard, unlike the magic-link
    verify routes where the hint is set in-page. See
    frontend/src/lib/googleSignInLanding.ts."""
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{GOOGLE_SIGNIN_RESULT_QUERY_PARAM}={track}"


def build_oauth_error_redirect(
    error_code: str, *, login_path: str, cookie_name: str, cookie_path: str
) -> RedirectResponse:
    """Every Google OAuth callback failure path lands here: a 302 back to the
    track's login page carrying an error code, never a 500 — the state
    cookie (single-use) is cleared regardless of outcome."""
    response = RedirectResponse(
        f"{settings.FRONTEND_URL}{login_path}?{OAUTH_ERROR_QUERY_PARAM}={error_code}",
        status_code=status.HTTP_302_FOUND,
    )
    clear_oauth_state_cookie(response, cookie_name=cookie_name, cookie_path=cookie_path)
    return response


async def recent_unused_link_exists(
    db: AsyncSession,
    model: type[Any],
    fk_column: InstrumentedAttribute[Any],
    fk_value: int,
    ttl_seconds: int,
    *,
    extra_predicate: ColumnElement[bool] | None = None,
) -> bool:
    """Per-account magic-link resend cooldown, shared by the consumer
    (routers/auth.py) and organizer (routers/organizer_auth.py) auth tracks.

    True if an unused link (identified by ``fk_column == fk_value`` on
    ``model``, which must carry ``used_at``/``expires_at`` columns like
    AuthMagicLink/OrganizerMagicLink) was issued within
    MAGIC_LINK_RESEND_COOLDOWN_SECONDS of now.

    A link created T seconds ago has expires_at = now + (ttl_seconds - T), so
    expires_at > now + ttl_seconds - cooldown <-> T < cooldown. Prevents
    Resend quota exhaustion from rapid repeats; IP-level throttling is the
    separate @limiter.limit decorator on the request-link endpoint.

    ``extra_predicate`` narrows the match beyond the fk — e.g. Google
    sign-in's confirmation-link cooldown (organizer_auth.py) must only
    suppress a resend against another *pending-confirmation* link for the
    same sub, not against an unrelated plain sign-in link the organizer
    happens to have unused, which would silently skip sending the
    confirmation email while the caller still reports it as sent.
    """
    recent_cutoff = datetime.now(timezone.utc) + timedelta(
        seconds=ttl_seconds - MAGIC_LINK_RESEND_COOLDOWN_SECONDS
    )
    conditions = [
        fk_column == fk_value,
        model.used_at.is_(None),
        model.expires_at > recent_cutoff,
    ]
    if extra_predicate is not None:
        conditions.append(extra_predicate)
    already_sent = await db.scalar(select(model).where(*conditions).limit(1))
    return already_sent is not None


async def is_identity_linked(
    db: AsyncSession,
    identity_model: type[UserIdentity] | type[OrganizerIdentity],
    owner_col: InstrumentedAttribute,
    owner_id: int,
) -> bool:
    """True if ``owner_id`` has a linked Google identity row.

    Shared by settings.py (UserIdentity, UserIdentity.user_id) and
    organizer_profile.py (OrganizerIdentity, OrganizerIdentity.organizer_id) —
    both tracks' google_linked flag is otherwise the same query against a
    different identity table/owner column.
    """
    result = await db.execute(
        select(identity_model.id).where(
            owner_col == owner_id,
            identity_model.provider == IDENTITY_PROVIDER_GOOGLE,
        )
    )
    return result.scalars().first() is not None


# {"YYYY-MM-DD": count} — in-memory, single-process, like the admin lockout
# dict (auth/admin_lockout.py) — resets on deploy/restart, which just means one
# lost day of budget tracking, not a security regression.
_unverified_account_creation_counts: dict[str, int] = {}


_unverified_account_budget_alerted: set[str] = set()


async def get_or_create_organizer(
    db: AsyncSession, email: str, requested_locale: str | None
) -> Organizer:
    """Look up (or insert) the organizer for a magic-link request — shared by
    organizer_auth.py's own sign-in link and organizer_claims.py's claim-
    intent link (#413), which both need the identical unverified-row-creation
    trade-off (mitigated by RATE_LIMIT_AUTH_REQUEST_LINK + recent_unused_link_exists).
    Mirrors auth.py::_get_or_create_user."""
    organizer = await db.scalar(select(Organizer).where(Organizer.email == email))
    if organizer is None:
        organizer = Organizer(email=email, locale=requested_locale or DEFAULT_USER_LOCALE)
        db.add(organizer)
        await db.flush()
        log.info(
            "organizer auth: new unverified organizer row created email=%s",
            mask_email(email),
        )
        record_unverified_account_creation()
    return organizer


def record_unverified_account_creation() -> None:
    """Bump the global (not per-IP) daily count of new unverified User/
    Organizer rows created via the magic-link request endpoints
    (auth.py::_get_or_create_user, organizer_auth.py::_get_or_create_organizer).

    The per-email cooldown (RATE_LIMIT_AUTH_REQUEST_LINK) only throttles
    repeats to the *same* address; a burst of distinct first-contact
    addresses can still mail-bomb via this service's Resend domain. Rather
    than hard-blocking new signups (which would turn away real users during
    a legitimate burst), this logs one distinct, greppable warning the first
    time UNVERIFIED_ACCOUNT_DAILY_BUDGET is crossed for the day — an early
    signal an operator can alert on ahead of Resend's own sender-reputation/
    quota controls tripping (OWASP audit F10).
    """
    today = datetime.now(TALLINN_TZ).date().isoformat()
    count = _unverified_account_creation_counts.get(today, 0) + 1
    _unverified_account_creation_counts[today] = count
    if (
        count >= UNVERIFIED_ACCOUNT_DAILY_BUDGET
        and today not in _unverified_account_budget_alerted
    ):
        _unverified_account_budget_alerted.add(today)
        log.warning(
            "auth: unverified-account creation budget exceeded (%d today)",
            count,
            extra={"event": LOG_EVENT_UNVERIFIED_ACCOUNT_BUDGET_EXCEEDED},
        )
    # Bound growth: only today's entry is ever needed going forward — a
    # process left running for weeks would otherwise accumulate one stale
    # key per day forever.
    for stale_day in [d for d in _unverified_account_creation_counts if d != today]:
        del _unverified_account_creation_counts[stale_day]
        _unverified_account_budget_alerted.discard(stale_day)
