"""Tests for L2: consecutive-failure lockout on the admin console form login
(routers/admin_auth.py), on top of the shared_limit rate bucket. HTTP Basic
no longer exists on /admin/* (OWASP audit #4), so every failure here is a form
login attempt."""

import http
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.constants.auth import ADMIN_AUTH_MAX_FAILURES
from tests.routers.conftest import patch_admin_settings


def _login_app() -> FastAPI:
    from app.routers.admin_auth import router as admin_auth_router

    app = FastAPI()
    app.include_router(admin_auth_router)
    return app


_BAD_LOGIN = {"username": "realadmin", "password": "wrong", "totp_code": "000000"}


def _configure(mock_settings) -> None:
    mock_settings.ADMIN_PASSWORD = "s3cret"
    mock_settings.ADMIN_USERNAME = "realadmin"
    mock_settings.APP_ENV = "production"
    mock_settings.ALLOW_INSECURE_DEV = False
    mock_settings.ADMIN_TOTP_SECRET = "JBSWY3DPEHPK3PXP"


@pytest.mark.asyncio
async def test_lockout_after_max_consecutive_failures():
    with patch_admin_settings() as mock_settings, patch(
        "app.routers.admin_auth.settings", mock_settings
    ):
        _configure(mock_settings)

        async with AsyncClient(
            transport=ASGITransport(app=_login_app()), base_url="http://test"
        ) as client:
            statuses = []
            for _ in range(ADMIN_AUTH_MAX_FAILURES):
                resp = await client.post("/admin/auth/login", json=_BAD_LOGIN)
                statuses.append(resp.status_code)

            # One more failure past the threshold — must be locked out (429),
            # not just another 401.
            locked_resp = await client.post("/admin/auth/login", json=_BAD_LOGIN)

    assert statuses == [http.HTTPStatus.UNAUTHORIZED] * ADMIN_AUTH_MAX_FAILURES
    assert locked_resp.status_code == http.HTTPStatus.TOO_MANY_REQUESTS


@pytest.mark.asyncio
async def test_admin_auth_failures_dict_is_bounded():
    """P2-11: _admin_auth_failures is an in-memory dict keyed by client_key()
    with no prior eviction — sustained scanning traffic from many distinct
    clients would grow it forever. Bounded LRU (ADMIN_AUTH_FAILURES_MAX_ENTRIES)
    caps it, mirroring browse.py's _score_cache."""
    from app.auth import admin_lockout

    with patch_admin_settings() as mock_settings, patch(
        "app.routers.admin_auth.settings", mock_settings
    ), patch("app.auth.admin_lockout.ADMIN_AUTH_FAILURES_MAX_ENTRIES", 3):
        _configure(mock_settings)

        async with AsyncClient(
            transport=ASGITransport(app=_login_app()), base_url="http://test"
        ) as client:
            for i in range(6):
                await client.post(
                    "/admin/auth/login",
                    json=_BAD_LOGIN,
                    headers={"X-Forwarded-For": f"10.0.0.{i}"},
                )

    assert 0 < len(admin_lockout._admin_auth_failures) <= 3


@pytest.mark.asyncio
async def test_eviction_does_not_lift_an_active_lockout():
    """A blind oldest-first eviction would let a high-cardinality distributed
    brute-force evict — and thereby prematurely lift — another client's
    still-active lockout. The victim's locked-until entry must survive being
    the oldest in the dict as long as other, already-expired entries exist
    to evict instead."""
    from app.auth import admin_lockout

    with patch_admin_settings() as mock_settings, patch(
        "app.routers.admin_auth.settings", mock_settings
    ), patch("app.auth.admin_lockout.ADMIN_AUTH_FAILURES_MAX_ENTRIES", 1):
        _configure(mock_settings)

        async with AsyncClient(
            transport=ASGITransport(app=_login_app()), base_url="http://test"
        ) as client:
            # Victim: lock it out first, so it is both the oldest entry and
            # currently under an active lockout.
            for _ in range(ADMIN_AUTH_MAX_FAILURES):
                await client.post(
                    "/admin/auth/login",
                    json=_BAD_LOGIN,
                    headers={"X-Forwarded-For": "10.0.0.1"},
                )
            assert admin_lockout._admin_auth_failures["10.0.0.1"][1] > 0.0

            # Attacker: fail from a second, expired (never-locked) client —
            # pushes the dict over the max-entries cap.
            await client.post(
                "/admin/auth/login",
                json=_BAD_LOGIN,
                headers={"X-Forwarded-For": "10.0.0.2"},
            )

    # The victim's active lockout must not have been evicted to make room.
    assert "10.0.0.1" in admin_lockout._admin_auth_failures
    assert admin_lockout._admin_auth_failures["10.0.0.1"][1] > 0.0


@pytest.mark.asyncio
async def test_rate_limit_bucket_shared_across_different_admin_routes(admin_app):
    """L2: RATE_LIMIT_ADMIN must be ONE bucket per client across the whole
    /admin prefix (limiter.shared_limit(..., scope="admin")), not one bucket
    per route — otherwise cycling through routes lets an attacker exceed the
    nominal cap by ~Nx (N = number of admin routes)."""
    from app.constants.rate_limits import RATE_LIMIT_ADMIN

    burst = int(RATE_LIMIT_ADMIN.split("/")[0])
    app = admin_app

    with (
        patch_admin_settings() as mock_settings,
        patch(
            "app.routers.admin.publish_pending_job",
            new_callable=AsyncMock,
            return_value={"published": 0},
        ),
        patch(
            "app.routers.admin.geocode_pending_job",
            new_callable=AsyncMock,
            return_value={"geocoded": 0},
        ),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = "development"
        mock_settings.ALLOW_INSECURE_DEV = True

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            statuses = []
            # Alternate between two distinct admin routes — if each had its
            # own bucket, none of these would ever 429.
            for i in range(burst + 1):
                path = "/admin/publish" if i % 2 == 0 else "/admin/geocode"
                resp = await client.post(path, auth=("admin", ""))
                statuses.append(resp.status_code)

    assert http.HTTPStatus.TOO_MANY_REQUESTS in statuses


def test_failure_log_never_contains_attempted_username(caplog):
    """OWASP audit L-12: a password typed into the username field must not be logged."""
    import time

    from app.auth.admin_lockout import record_admin_auth_failure

    with caplog.at_level("WARNING"):
        record_admin_auth_failure("k-l12", time.monotonic(), "hunter2-secret")
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "hunter2-secret" not in text
    assert "username_ok=False" in text
