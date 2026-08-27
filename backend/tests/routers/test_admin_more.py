"""Coverage for admin endpoints/branches not exercised by test_admin.py:
_require_admin fail-closed, /ingest, /ingest/{slug}, /dedup, /dedup/groups,
/classify, /refetch, /stats.

_require_admin fail-closed tests below target a read-only (GET) route —
mutating (POST) routes require the session-only get_current_admin (H-1 in
the OWASP audit) and no longer accept Basic auth at all, so they can't
exercise _require_admin's Basic-branch checks (admin_username_disabled,
admin_credentials_ok)."""

import http
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.constants import ADMIN_USERNAME_DEFAULT, APP_ENV_DEVELOPMENT
from tests.routers.conftest import ndjson_lines, scalars_returning


# ---------------------------------------------------------------------------
# _require_admin fail-closed branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_username_in_production_returns_503(admin_app):
    app = admin_app
    with patch("app.routers.admin.settings") as mock_settings:
        mock_settings.ADMIN_PASSWORD = "s3cret"
        mock_settings.ADMIN_USERNAME = ADMIN_USERNAME_DEFAULT
        mock_settings.APP_ENV = "production"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/admin/stats", auth=(ADMIN_USERNAME_DEFAULT, "s3cret")
            )

    assert resp.status_code == http.HTTPStatus.SERVICE_UNAVAILABLE


@pytest.mark.asyncio
async def test_wrong_credentials_returns_401(admin_app):
    app = admin_app
    with patch("app.routers.admin.settings") as mock_settings:
        mock_settings.ADMIN_PASSWORD = "s3cret"
        mock_settings.ADMIN_USERNAME = "realadmin"
        mock_settings.APP_ENV = "production"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/admin/stats", auth=("realadmin", "wrong"))

    assert resp.status_code == http.HTTPStatus.UNAUTHORIZED


# ---------------------------------------------------------------------------
# POST /admin/ingest  &  POST /admin/ingest/{slug}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_all_returns_results(admin_app):
    app = admin_app
    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch(
            "app.routers.admin.ingest_all_enabled",
            new_callable=AsyncMock,
            return_value=[{"slug": "fienta", "raw_count": 5}],
        ),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/admin/ingest", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    assert resp.headers["cache-control"] == "no-store"
    lines = ndjson_lines(resp)
    assert len(lines) == 1
    assert lines[0]["status"] == "ok"
    assert lines[0]["result"]["results"] == [{"slug": "fienta", "raw_count": 5}]


@pytest.mark.asyncio
async def test_ingest_source_unknown_slug_404(admin_app):
    app = admin_app
    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.ADAPTER_REGISTRY", {}),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/admin/ingest/nope", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_ingest_source_value_error_400(admin_app):
    app = admin_app
    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.ADAPTER_REGISTRY", {"fienta": MagicMock()}),
        patch(
            "app.routers.admin.ingest_source",
            new_callable=AsyncMock,
            side_effect=ValueError("disabled"),
        ),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/admin/ingest/fienta", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    lines = ndjson_lines(resp)
    assert lines[0]["status"] == "error"
    assert lines[0]["error"] == "disabled"


@pytest.mark.asyncio
async def test_ingest_source_success(admin_app):
    app = admin_app
    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.ADAPTER_REGISTRY", {"fienta": MagicMock()}),
        patch(
            "app.routers.admin.ingest_source",
            new_callable=AsyncMock,
            return_value={"slug": "fienta", "raw_count": 3, "new_count": 1},
        ),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/admin/ingest/fienta", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    lines = ndjson_lines(resp)
    assert lines[0]["result"]["new_count"] == 1


# ---------------------------------------------------------------------------
# POST /admin/dedup, /admin/classify, /admin/refetch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,target",
    [
        ("/admin/dedup", "app.routers.admin.dedup_pass_drain_now"),
        ("/admin/classify", "app.routers.admin.classify_pending_drain_now"),
        ("/admin/refetch", "app.routers.admin.refetch_event_details_job"),
    ],
)
async def test_simple_job_triggers(path, target, admin_app):
    app = admin_app
    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch(target, new_callable=AsyncMock, return_value={"done": 1}) as mock_job,
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(path, auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    assert resp.headers["cache-control"] == "no-store"
    lines = ndjson_lines(resp)
    assert len(lines) == 1
    assert lines[0]["status"] == "ok"
    assert lines[0]["result"] == {"done": 1}
    mock_job.assert_awaited_once()


# ---------------------------------------------------------------------------
# GET /admin/dedup/groups
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dedup_groups_empty_page(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db = mock_db
    db.scalar = AsyncMock(return_value=0)
    db.scalars = AsyncMock(return_value=scalars_returning([]))

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/admin/dedup/groups", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    body = resp.json()
    assert body["group_count"] == 0
    assert body["groups"] == []
    assert body["has_more"] is False


@pytest.mark.asyncio
async def test_dedup_groups_populated_page(admin_app, make_db_ctx, mock_db):
    from datetime import datetime, timezone

    app = admin_app
    ev = MagicMock()
    ev.id = 11
    ev.dedup_group_id = 5
    ev.title_orig = "Jazz"
    ev.starts_at = datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc)
    ev.venue_name = "Club"
    ev.status = "published"
    ev.url = "https://x"
    ev.is_explicit = False

    db = mock_db
    db.scalar = AsyncMock(return_value=1)  # total_groups
    # first scalars() -> page group ids; second -> event rows
    db.scalars = AsyncMock(
        side_effect=[scalars_returning([5]), scalars_returning([ev])]
    )

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/admin/dedup/groups", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    body = resp.json()
    assert body["group_count"] == 1
    assert body["event_count"] == 1
    assert body["groups"][0]["dedup_group_id"] == 5
    assert body["groups"][0]["events"][0]["id"] == 11


# ---------------------------------------------------------------------------
# GET /admin/stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stats_returns_counts(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db = mock_db
    # total, canonical, sources_total, sources_enabled
    db.scalar = AsyncMock(side_effect=[100, 60, 8, 5])

    with (
        patch("app.routers.admin.settings") as mock_settings,
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
