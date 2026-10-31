"""Tests for the admin console auth track (routers/admin_auth.py) — login/
logout/me, and its consecutive-failure lockout (issue #154). /admin/* routes
accept the session cookie only — HTTP Basic was removed (OWASP audit #4)."""

import http
from unittest.mock import AsyncMock, patch

import pyotp
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.auth.totp as totp_module
from app.constants.auth import ADMIN_AUTH_MAX_FAILURES, ADMIN_USERNAME_DEFAULT
from tests.routers.conftest import patch_admin_settings


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
    from app.routers.admin_jobs import router as admin_router
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

    with patch_admin_settings() as mock_settings, patch(
        "app.routers.admin_auth.settings", mock_settings
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

    with patch_admin_settings() as mock_settings, patch(
        "app.routers.admin_auth.settings", mock_settings
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

    with patch_admin_settings() as mock_settings, patch(
        "app.routers.admin_auth.settings", mock_settings
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

    with patch_admin_settings() as mock_settings, patch(
        "app.routers.admin_auth.settings", mock_settings
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
            # here has no /api prefix — that's added by the Cloudflare Pages
            # Function proxy in production), so httpx's jar won't auto-attach
            # it to these requests; pass it explicitly instead of relying on
            # the jar.
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
    with patch_admin_settings() as mock_settings:
        _patch_settings(mock_settings, totp_secret=None)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/admin/auth/me")
    assert resp.status_code == http.HTTPStatus.UNAUTHORIZED


@pytest.mark.asyncio
async def test_admin_session_cookie_satisfies_get_current_admin():
    """A session cookie from POST /admin/auth/login must let the console
    reach the /admin/* surface without ever sending Basic credentials."""
    secret = pyotp.random_base32()
    app = _build_app()

    with patch_admin_settings() as mock_settings, patch(
        "app.routers.admin_auth.settings", mock_settings
    ), patch(
        "app.routers.admin_jobs.publish_pending_job",
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
    ever checks ADMIN_USERNAME/ADMIN_PASSWORD, never TOTP. Every route requires
    get_current_admin (session-cookie only, no Basic fallback)."""
    app = _build_app()

    with patch_admin_settings() as mock_settings:
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
async def test_failed_form_logins_lock_out_the_client():
    """After ADMIN_AUTH_MAX_FAILURES failed form logins, even a correct login
    from the same client_key is locked out (429)."""
    secret = pyotp.random_base32()
    app = _build_app()

    with patch_admin_settings() as mock_settings, patch(
        "app.routers.admin_auth.settings", mock_settings
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

            good_resp = await client.post(
                "/admin/auth/login",
                json={
                    "username": "realadmin",
                    "password": "s3cret",
                    "totp_code": pyotp.TOTP(secret).now(),
                },
            )

    assert good_resp.status_code == http.HTTPStatus.TOO_MANY_REQUESTS


@pytest.mark.asyncio
async def test_login_with_default_username_in_production_returns_503():
    app = _build_app()

    with patch_admin_settings() as mock_settings, patch(
        "app.routers.admin_auth.settings", mock_settings
    ):
        _patch_settings(mock_settings, totp_secret=pyotp.random_base32())
        mock_settings.ADMIN_USERNAME = ADMIN_USERNAME_DEFAULT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/auth/login",
                json={
                    "username": ADMIN_USERNAME_DEFAULT,
                    "password": "s3cret",
                    "totp_code": "000000",
                },
            )

    assert resp.status_code == http.HTTPStatus.SERVICE_UNAVAILABLE


@pytest.mark.asyncio
async def test_successful_form_login_clears_prior_failures():
    secret = pyotp.random_base32()
    app = _build_app()

    with patch_admin_settings() as mock_settings, patch(
        "app.routers.admin_auth.settings", mock_settings
    ):
        _patch_settings(mock_settings, totp_secret=secret)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for _ in range(ADMIN_AUTH_MAX_FAILURES - 1):
                await client.post(
                    "/admin/auth/login",
                    json={
                        "username": "realadmin",
                        "password": "wrong",
                        "totp_code": "000000",
                    },
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
    from app.auth import admin_lockout

    assert len(admin_lockout._admin_auth_failures) == 0
