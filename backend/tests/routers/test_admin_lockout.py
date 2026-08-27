"""Tests for L2: consecutive-failure lockout on /admin/* Basic auth
(routers/admin.py::_require_admin), on top of the shared_limit rate bucket.

Basic-auth-specific tests target a read-only (GET) route — mutating (POST)
routes require the session-only get_current_admin (H-1 in the OWASP audit)
and no longer accept Basic at all, so they can't exercise this lockout."""

import http
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.constants import ADMIN_AUTH_MAX_FAILURES


@pytest.mark.asyncio
async def test_lockout_after_max_consecutive_failures(admin_app):
    app = admin_app

    with patch("app.routers.admin.settings") as mock_settings:
        mock_settings.ADMIN_PASSWORD = "s3cret"
        mock_settings.ADMIN_USERNAME = "realadmin"
        mock_settings.APP_ENV = "production"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            statuses = []
            for _ in range(ADMIN_AUTH_MAX_FAILURES):
                resp = await client.get(
                    "/admin/stats", auth=("realadmin", "wrong")
                )
                statuses.append(resp.status_code)

            # One more failure past the threshold — must be locked out (429),
            # not just another 401.
            locked_resp = await client.get(
                "/admin/stats", auth=("realadmin", "wrong")
            )

    assert statuses == [http.HTTPStatus.UNAUTHORIZED] * ADMIN_AUTH_MAX_FAILURES
    assert locked_resp.status_code == http.HTTPStatus.TOO_MANY_REQUESTS


@pytest.mark.asyncio
async def test_admin_auth_failures_dict_is_bounded(admin_app):
    """P2-11: _admin_auth_failures is an in-memory dict keyed by client_key()
    with no prior eviction — sustained scanning traffic from many distinct
    clients would grow it forever. Bounded LRU (ADMIN_AUTH_FAILURES_MAX_ENTRIES)
    caps it, mirroring browse.py's _score_cache."""
    from app.routers import admin as admin_module

    app = admin_app

    with patch("app.routers.admin.settings") as mock_settings, patch(
        "app.routers.admin.ADMIN_AUTH_FAILURES_MAX_ENTRIES", 3
    ):
        mock_settings.ADMIN_PASSWORD = "s3cret"
        mock_settings.ADMIN_USERNAME = "realadmin"
        mock_settings.APP_ENV = "production"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for i in range(6):
                await client.get(
                    "/admin/stats",
                    auth=("realadmin", "wrong"),
                    headers={"X-Forwarded-For": f"10.0.0.{i}"},
                )

    assert len(admin_module._admin_auth_failures) <= 3


@pytest.mark.asyncio
async def test_eviction_does_not_lift_an_active_lockout(admin_app):
    """A blind oldest-first eviction would let a high-cardinality distributed
    brute-force evict — and thereby prematurely lift — another client's
    still-active lockout. The victim's locked-until entry must survive being
    the oldest in the dict as long as other, already-expired entries exist
    to evict instead."""
    from app.routers import admin as admin_module

    app = admin_app

    with patch("app.routers.admin.settings") as mock_settings, patch(
        "app.routers.admin.ADMIN_AUTH_FAILURES_MAX_ENTRIES", 1
    ):
        mock_settings.ADMIN_PASSWORD = "s3cret"
        mock_settings.ADMIN_USERNAME = "realadmin"
        mock_settings.APP_ENV = "production"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # Victim: lock it out first, so it is both the oldest entry and
            # currently under an active lockout.
            for _ in range(ADMIN_AUTH_MAX_FAILURES):
                await client.get(
                    "/admin/stats",
                    auth=("realadmin", "wrong"),
                    headers={"X-Forwarded-For": "10.0.0.1"},
                )
            assert admin_module._admin_auth_failures["10.0.0.1"][1] > 0.0

            # Attacker: fail from a second, expired (never-locked) client —
            # pushes the dict over the max-entries cap of 2.
            await client.get(
                "/admin/stats",
                auth=("realadmin", "wrong"),
                headers={"X-Forwarded-For": "10.0.0.2"},
            )

    # The victim's active lockout must not have been evicted to make room.
    assert "10.0.0.1" in admin_module._admin_auth_failures
    assert admin_module._admin_auth_failures["10.0.0.1"][1] > 0.0


@pytest.mark.asyncio
async def test_rate_limit_bucket_shared_across_different_admin_routes(admin_app):
    """L2: RATE_LIMIT_ADMIN must be ONE bucket per client across the whole
    /admin prefix (limiter.shared_limit(..., scope="admin")), not one bucket
    per route — otherwise cycling through routes lets an attacker exceed the
    nominal cap by ~Nx (N = number of admin routes)."""
    from app.constants import RATE_LIMIT_ADMIN

    burst = int(RATE_LIMIT_ADMIN.split("/")[0])
    app = admin_app

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
async def test_successful_auth_resets_failure_counter(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db = mock_db
    # total, canonical, sources_total, sources_enabled
    db.scalar = AsyncMock(side_effect=[100, 60, 8, 5])

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = "s3cret"
        mock_settings.ADMIN_USERNAME = "realadmin"
        mock_settings.APP_ENV = "production"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for _ in range(ADMIN_AUTH_MAX_FAILURES - 1):
                await client.get("/admin/stats", auth=("realadmin", "wrong"))

            good_resp = await client.get(
                "/admin/stats", auth=("realadmin", "s3cret")
            )

            # Counter reset by the successful auth — next failure alone must
            # not trigger a lockout.
            next_fail_resp = await client.get(
                "/admin/stats", auth=("realadmin", "wrong")
            )

    assert good_resp.status_code == http.HTTPStatus.OK
    assert next_fail_resp.status_code == http.HTTPStatus.UNAUTHORIZED
