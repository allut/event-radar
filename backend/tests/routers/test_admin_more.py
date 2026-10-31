"""Coverage for admin endpoints/branches not exercised by test_admin.py:
session-only auth on /stats, /ingest, /ingest/{slug}, /dedup, /dedup/groups,
/classify, /refetch, /stats.

Every /admin/* route — /stats and /counts included (OWASP audit #4) — requires
the TOTP-backed session cookie; HTTP Basic is not accepted anywhere. GET
/admin/dedup/groups moved off Basic earlier (OWASP audit G-5) — see
test_dedup_groups_rejects_basic_auth_alone below."""

import http
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.constants.core import APP_ENV_DEVELOPMENT
from tests.routers.conftest import patch_admin_settings


# ---------------------------------------------------------------------------
# session-only auth on /stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stats_rejects_correct_basic_credentials_alone(admin_app):
    """OWASP audit #4: password-only access to /admin/stats is gone — correct
    Basic credentials no longer reach TOTP-less read access (and so no longer
    act as a password-guess oracle)."""
    app = admin_app
    with patch_admin_settings() as mock_settings:
        mock_settings.ADMIN_PASSWORD = "s3cret"
        mock_settings.ADMIN_USERNAME = "realadmin"
        mock_settings.APP_ENV = "production"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/admin/stats", auth=("realadmin", "s3cret"))

    assert resp.status_code == http.HTTPStatus.UNAUTHORIZED


@pytest.mark.asyncio
async def test_counts_rejects_correct_basic_credentials_alone(admin_app):
    app = admin_app
    with patch_admin_settings() as mock_settings:
        mock_settings.ADMIN_PASSWORD = "s3cret"
        mock_settings.ADMIN_USERNAME = "realadmin"
        mock_settings.APP_ENV = "production"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/admin/counts", auth=("realadmin", "s3cret"))

    assert resp.status_code == http.HTTPStatus.UNAUTHORIZED


@pytest.mark.asyncio
async def test_wrong_credentials_returns_401(admin_app):
    app = admin_app
    with patch_admin_settings() as mock_settings:
        mock_settings.ADMIN_PASSWORD = "s3cret"
        mock_settings.ADMIN_USERNAME = "realadmin"
        mock_settings.APP_ENV = "production"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/admin/stats", auth=("realadmin", "wrong"))

    assert resp.status_code == http.HTTPStatus.UNAUTHORIZED


# ---------------------------------------------------------------------------
# GET /admin/stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stats_returns_counts(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db = mock_db
    # one execute() for (total, canonical); scalar() for sources_total, sources_enabled
    counts = MagicMock()
    counts.one.return_value = (100, 60)
    db.execute = AsyncMock(return_value=counts)
    db.scalar = AsyncMock(side_effect=[8, 5])

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/admin/stats", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    body = resp.json()
    assert body["events"] == {"total": 100, "canonical": 60}
    assert body["sources"] == {"total": 8, "enabled": 5}
