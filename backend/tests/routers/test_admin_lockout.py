"""Tests for L2: consecutive-failure lockout on /admin/* Basic auth
(routers/admin.py::_require_admin), on top of the shared_limit rate bucket."""

import http
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.constants import ADMIN_AUTH_MAX_FAILURES


def _build_app() -> FastAPI:
    from app.routers.admin import router

    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture(autouse=True)
def _reset_admin_auth_failures():
    """The failure counter is a module-level dict (in-memory, single-process
    by design — see ADMIN_AUTH_MAX_FAILURES in constants.py) shared across
    tests in this process; isolate each test from the others."""
    from app.routers import admin as admin_module

    admin_module._admin_auth_failures.clear()
    yield
    admin_module._admin_auth_failures.clear()


@pytest.mark.asyncio
async def test_lockout_after_max_consecutive_failures():
    app = _build_app()

    with patch("app.routers.admin.settings") as mock_settings:
        mock_settings.ADMIN_PASSWORD = "s3cret"
        mock_settings.ADMIN_USERNAME = "realadmin"
        mock_settings.APP_ENV = "production"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            statuses = []
            for _ in range(ADMIN_AUTH_MAX_FAILURES):
                resp = await client.post(
                    "/admin/publish", auth=("realadmin", "wrong")
                )
                statuses.append(resp.status_code)

            # One more failure past the threshold — must be locked out (429),
            # not just another 401.
            locked_resp = await client.post(
                "/admin/publish", auth=("realadmin", "wrong")
            )

    assert statuses == [http.HTTPStatus.UNAUTHORIZED] * ADMIN_AUTH_MAX_FAILURES
    assert locked_resp.status_code == http.HTTPStatus.TOO_MANY_REQUESTS


@pytest.mark.asyncio
async def test_rate_limit_bucket_shared_across_different_admin_routes():
    """L2: RATE_LIMIT_ADMIN must be ONE bucket per client across the whole
    /admin prefix (limiter.shared_limit(..., scope="admin")), not one bucket
    per route — otherwise cycling through routes lets an attacker exceed the
    nominal cap by ~Nx (N = number of admin routes)."""
    from app.constants import RATE_LIMIT_ADMIN

    burst = int(RATE_LIMIT_ADMIN.split("/")[0])
    app = _build_app()

    with (
        patch("app.routers.admin.settings") as mock_settings,
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


@pytest.mark.asyncio
async def test_successful_auth_resets_failure_counter():
    app = _build_app()

    with patch("app.routers.admin.settings") as mock_settings:
        mock_settings.ADMIN_PASSWORD = "s3cret"
        mock_settings.ADMIN_USERNAME = "realadmin"
        mock_settings.APP_ENV = "production"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for _ in range(ADMIN_AUTH_MAX_FAILURES - 1):
                await client.post("/admin/publish", auth=("realadmin", "wrong"))

            with patch(
                "app.routers.admin.publish_pending_job",
                new_callable=AsyncMock,
                return_value={"published": 0},
            ):
                good_resp = await client.post(
                    "/admin/publish", auth=("realadmin", "s3cret")
                )

            # Counter reset by the successful auth — next failure alone must
            # not trigger a lockout.
            next_fail_resp = await client.post(
                "/admin/publish", auth=("realadmin", "wrong")
            )

    assert good_resp.status_code == http.HTTPStatus.OK
    assert next_fail_resp.status_code == http.HTTPStatus.UNAUTHORIZED
