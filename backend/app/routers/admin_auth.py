"""Admin console auth endpoints — password + TOTP login, own session cookie.

A third auth track alongside app/routers/auth.py (consumer) and
app/routers/organizer_auth.py (organizer): see docs/backend-ops.md's Admin
Endpoints section and docs/security.md's Auth section. Credential is the
existing ADMIN_USERNAME/ADMIN_PASSWORD env vars app/routers/admin.py already
checks via HTTP Basic — this endpoint adds a required TOTP step and issues a
session cookie so the admin console frontend can authenticate without ever
holding the Basic credential in JS. Login/logout failures share the same
lockout counter as Basic auth (app/routers/admin.py::check_admin_lockout) —
one damper for both auth surfaces on this credential pair.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.auth.tokens import generate_admin_session_token
from app.auth.totp import verify_totp_code
from app.config import settings
from app.constants import (
    ADMIN_SESSION_COOKIE_NAME,
    ADMIN_SESSION_COOKIE_PATH,
    ADMIN_SESSION_TTL_SECONDS,
    ERROR_ADMIN_DISABLED,
    ERROR_ADMIN_INCORRECT_CREDENTIALS,
    LOG_EVENT_ADMIN_ACTION,
    RATE_LIMIT_ADMIN_LOGIN,
    RATE_LIMIT_BROWSE,
    RATE_LIMIT_LOGOUT,
)
from app.rate_limit import client_key, limiter
from app.routers.admin import (
    admin_credentials_ok,
    admin_username_disabled,
    check_admin_lockout,
    clear_admin_auth_failure,
    get_current_admin,
    record_admin_auth_failure,
)
from app.routers.utils import clear_session_cookie, require_configured_secret, set_session_cookie

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/auth", tags=["admin-auth"])


class AdminLoginBody(BaseModel):
    username: str
    password: str
    totp_code: str


@router.post("/login", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_ADMIN_LOGIN)
async def admin_login(body: AdminLoginBody, request: Request, response: Response) -> dict:
    """Single-submit username + password + TOTP login. Sets the admin session
    cookie on success. Shares its lockout counter with HTTP Basic
    (admin.py::_require_admin) via the check_admin_lockout/
    record_admin_auth_failure/clear_admin_auth_failure helpers."""
    key = client_key(request)
    now = check_admin_lockout(key)

    password = settings.ADMIN_PASSWORD
    password_configured = require_configured_secret(
        password,
        feature="Admin login",
        setting_name="ADMIN_PASSWORD",
        app_env=settings.APP_ENV,
        allow_insecure_dev=settings.ALLOW_INSECURE_DEV,
    )
    if password_configured:
        if admin_username_disabled():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=ERROR_ADMIN_DISABLED,
            )
        totp_secret = settings.ADMIN_TOTP_SECRET
        totp_configured = require_configured_secret(
            totp_secret,
            feature="Admin TOTP",
            setting_name="ADMIN_TOTP_SECRET",
            app_env=settings.APP_ENV,
            allow_insecure_dev=settings.ALLOW_INSECURE_DEV,
        )
        credentials_ok = admin_credentials_ok(body.username, body.password)
        totp_ok = verify_totp_code(totp_secret, body.totp_code) if totp_configured else True
        if not (credentials_ok and totp_ok):
            record_admin_auth_failure(key, now, body.username)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=ERROR_ADMIN_INCORRECT_CREDENTIALS,
            )
    # else: password unset, dev fail-open (require_configured_secret already
    # logged a warning) — mirrors _require_admin's own early return.

    clear_admin_auth_failure(key)
    session_token = generate_admin_session_token()
    set_session_cookie(
        response,
        name=ADMIN_SESSION_COOKIE_NAME,
        token=session_token,
        path=ADMIN_SESSION_COOKIE_PATH,
        ttl_seconds=ADMIN_SESSION_TTL_SECONDS,
    )
    log.info("admin login succeeded", extra={"event": LOG_EVENT_ADMIN_ACTION})
    return {"detail": "Signed in."}


@router.post("/logout", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_LOGOUT)
async def admin_logout(
    request: Request,
    response: Response,
    _admin: None = Depends(get_current_admin),
) -> dict:
    """Sign out this device only — the admin session carries no
    session_token_version, so there is no "logout everywhere" variant (a
    12h TTL with no revocation beyond expiry is the accepted ceiling; see
    docs/adr/0001)."""
    clear_session_cookie(
        response, name=ADMIN_SESSION_COOKIE_NAME, path=ADMIN_SESSION_COOKIE_PATH
    )
    log.info("admin logout", extra={"event": LOG_EVENT_ADMIN_ACTION})
    return {"detail": "Signed out."}


@router.get("/me", status_code=status.HTTP_200_OK)
@limiter.limit(RATE_LIMIT_BROWSE)
async def admin_me(request: Request, _admin: None = Depends(get_current_admin)) -> dict:
    """Session-validity probe for the console frontend — no per-admin
    identity to return (see get_current_admin)."""
    return {"authenticated": True}
