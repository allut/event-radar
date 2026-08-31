"""Tests for the admin console auth track (routers/admin_auth.py) — login/
logout/me, and its shared lockout counter with routers/admin.py's HTTP Basic
_require_admin (issue #154)."""

import http
from unittest.mock import AsyncMock, patch

import pyotp
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.auth.totp as totp_module
from app.constants import ADMIN_AUTH_MAX_FAILURES


@pytest.fixture(autouse=True)
def _reset_totp_replay_state():
    """_last_accepted_step (app/auth/totp.py) is process-global — isolate
    each test, since every test here mints its own TOTP secret but the
    replay guard tracks accepted steps across all secrets (single-admin
    design). Without this, a later test's "current" step can collide with
    an earlier test's accepted step within the same wall-clock second."""
    totp_module._last_accepted_step = None
    yield
    totp_module._last_accepted_step = None


def _build_app() -> FastAPI:
    from app.routers.admin import router as admin_router
    from app.routers.admin_auth import router as admin_auth_router

    app = FastAPI()
    app.include_router(admin_router)
    app.include_router(admin_auth_router)
    return app


def _patch_settings(mock_settings, *, totp_secret: str | None):
    mock_settings.ADMIN_USERNAME = "realadmin"
    mock_settings.ADMIN_PASSWORD = "s3cret"
    mock_settings.APP_ENV = "production"
    mock_settings.ALLOW_INSECURE_DEV = False
    mock_settings.ADMIN_TOTP_SECRET = totp_secret


@pytest.mark.asyncio
async def test_login_succeeds_with_correct_credentials_and_totp():
    secret = pyotp.random_base32()
    app = _build_app()

    with patch("app.routers.admin_auth.settings") as mock_settings, patch(
        "app.routers.admin.settings", mock_settings
    ):
        _patch_settings(mock_settings, totp_secret=secret)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/auth/login",
                json={
                    "username": "realadmin",
                    "password": "s3cret",
                    "totp_code": pyotp.TOTP(secret).now(),
                },
            )

    assert resp.status_code == http.HTTPStatus.OK
    set_cookie = resp.headers["set-cookie"]
    assert "admin_session=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=strict" in set_cookie
    assert "Path=/api/admin" in set_cookie


@pytest.mark.asyncio
async def test_login_rejects_wrong_totp_code():
    secret = pyotp.random_base32()
    app = _build_app()

    with patch("app.routers.admin_auth.settings") as mock_settings, patch(
        "app.routers.admin.settings", mock_settings
    ):
        _patch_settings(mock_settings, totp_secret=secret)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/auth/login",
                json={
                    "username": "realadmin",
                    "password": "s3cret",
                    "totp_code": "000000",
                },
            )

    assert resp.status_code == http.HTTPStatus.UNAUTHORIZED


@pytest.mark.asyncio
async def test_login_rejects_wrong_password():
    secret = pyotp.random_base32()
    app = _build_app()

    with patch("app.routers.admin_auth.settings") as mock_settings, patch(
        "app.routers.admin.settings", mock_settings
    ):
        _patch_settings(mock_settings, totp_secret=secret)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/auth/login",
                json={
                    "username": "realadmin",
                    "password": "wrong",
                    "totp_code": pyotp.TOTP(secret).now(),
                },
            )

    assert resp.status_code == http.HTTPStatus.UNAUTHORIZED


@pytest.mark.asyncio
async def test_login_and_logout_and_me_roundtrip():
    secret = pyotp.random_base32()
    app = _build_app()

    with patch("app.routers.admin_auth.settings") as mock_settings, patch(
        "app.routers.admin.settings", mock_settings
    ):
        _patch_settings(mock_settings, totp_secret=secret)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            login_resp = await client.post(
                "/admin/auth/login",
                json={
                    "username": "realadmin",
                    "password": "s3cret",
                    "totp_code": pyotp.TOTP(secret).now(),
                },
            )
            assert login_resp.status_code == http.HTTPStatus.OK
            # The cookie is Path-scoped to /api/admin (the app-served path
            # here has no /api prefix — that's added by Vercel's rewrite in
            # production), so httpx's jar won't auto-attach it to these
            # requests; pass it explicitly instead of relying on the jar.
            session_cookie = login_resp.cookies["admin_session"]

            me_resp = await client.get(
                "/admin/auth/me", cookies={"admin_session": session_cookie}
            )
            assert me_resp.status_code == http.HTTPStatus.OK
            assert me_resp.json() == {"authenticated": True}

            logout_resp = await client.post(
                "/admin/auth/logout", cookies={"admin_session": session_cookie}
            )
            assert logout_resp.status_code == http.HTTPStatus.OK
            assert "Max-Age=0" in logout_resp.headers["set-cookie"]

            me_after_logout = await client.get("/admin/auth/me")
    assert me_after_logout.status_code == http.HTTPStatus.UNAUTHORIZED


@pytest.mark.asyncio
async def test_logout_is_idempotent_with_no_session_cookie():
    """OWASP audit F18: logout must not require a valid session — hitting it
    with no cookie at all still gets a 200, not a 401, and clears the cookie."""
    app = _build_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/admin/auth/logout")
    assert resp.status_code == http.HTTPStatus.OK
    assert "Max-Age=0" in resp.headers["set-cookie"]


@pytest.mark.asyncio
async def test_me_without_session_cookie_is_401():
    app = _build_app()
    with patch("app.routers.admin.settings") as mock_settings:
        _patch_settings(mock_settings, totp_secret=None)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/admin/auth/me")
    assert resp.status_code == http.HTTPStatus.UNAUTHORIZED


@pytest.mark.asyncio
async def test_admin_session_cookie_satisfies_require_admin():
    """A session cookie from POST /admin/auth/login must let the console
    reach the existing HTTP-Basic-protected /admin/* surface without ever
    sending Basic credentials — the whole point of the shared _require_admin
    accept-either change."""
    secret = pyotp.random_base32()
    app = _build_app()

    with patch("app.routers.admin_auth.settings") as mock_settings, patch(
        "app.routers.admin.settings", mock_settings
    ), patch(
        "app.routers.admin.publish_pending_job",
        new_callable=AsyncMock,
        return_value={"published": 0},
    ):
        _patch_settings(mock_settings, totp_secret=secret)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            login_resp = await client.post(
                "/admin/auth/login",
                json={
                    "username": "realadmin",
                    "password": "s3cret",
                    "totp_code": pyotp.TOTP(secret).now(),
                },
            )
            session_cookie = login_resp.cookies["admin_session"]
            resp = await client.post(
                "/admin/publish", cookies={"admin_session": session_cookie}
            )

    assert resp.status_code == http.HTTPStatus.OK


@pytest.mark.asyncio
async def test_correct_basic_credentials_alone_do_not_satisfy_a_mutating_route():
    """H-1 regression: the admin console's TOTP second factor must not be
    bypassable on a mutating /admin/* route via HTTP Basic alone — Basic only
    ever checks ADMIN_USERNAME/ADMIN_PASSWORD, never TOTP. Mutating routes
    require get_current_admin (session-cookie only, no Basic fallback)."""
    app = _build_app()

    with patch("app.routers.admin.settings") as mock_settings:
        mock_settings.ADMIN_PASSWORD = "s3cret"
        mock_settings.ADMIN_USERNAME = "realadmin"
        mock_settings.APP_ENV = "production"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/publish", auth=("realadmin", "s3cret")
            )

    assert resp.status_code == http.HTTPStatus.UNAUTHORIZED


@pytest.mark.asyncio
async def test_failed_form_login_shares_lockout_counter_with_basic_auth():
    """L2 shared lockout: consecutive failures on the FORM login endpoint
    must count toward the SAME lockout as HTTP Basic — after
    ADMIN_AUTH_MAX_FAILURES failed form logins, a subsequent Basic attempt
    with correct credentials must still be locked out (429), and vice versa.
    Checked against a read-only (GET) route — mutating (POST) routes require
    the session-only get_current_admin (H-1 in the OWASP audit) and no
    longer accept Basic auth at all."""
    secret = pyotp.random_base32()
    app = _build_app()

    with patch("app.routers.admin_auth.settings") as mock_settings, patch(
        "app.routers.admin.settings", mock_settings
    ):
        _patch_settings(mock_settings, totp_secret=secret)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for _ in range(ADMIN_AUTH_MAX_FAILURES):
                resp = await client.post(
                    "/admin/auth/login",
                    json={
                        "username": "realadmin",
                        "password": "wrong",
                        "totp_code": "000000",
                    },
                )
                assert resp.status_code == http.HTTPStatus.UNAUTHORIZED

            # Correct Basic credentials, but this client_key is now locked out.
            basic_resp = await client.get(
                "/admin/stats", auth=("realadmin", "s3cret")
            )

    assert basic_resp.status_code == http.HTTPStatus.TOO_MANY_REQUESTS


@pytest.mark.asyncio
async def test_successful_form_login_clears_prior_basic_auth_failures():
    secret = pyotp.random_base32()
    app = _build_app()

    with patch("app.routers.admin_auth.settings") as mock_settings, patch(
        "app.routers.admin.settings", mock_settings
    ):
        _patch_settings(mock_settings, totp_secret=secret)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for _ in range(ADMIN_AUTH_MAX_FAILURES - 1):
                await client.post(
                    "/admin/publish", auth=("realadmin", "wrong")
                )

            login_resp = await client.post(
                "/admin/auth/login",
                json={
                    "username": "realadmin",
                    "password": "s3cret",
                    "totp_code": pyotp.TOTP(secret).now(),
                },
            )

    assert login_resp.status_code == http.HTTPStatus.OK
    from app.routers import admin as admin_module

    assert len(admin_module._admin_auth_failures) == 0
