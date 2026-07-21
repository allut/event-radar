"""Coverage for admin endpoints/branches not exercised by test_admin.py:
_require_admin fail-closed, /ingest, /ingest/{slug}, /dedup, /dedup/groups,
/classify, /refetch, /stats."""

import http
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.constants import ADMIN_USERNAME_DEFAULT, APP_ENV_DEVELOPMENT


def _build_app() -> FastAPI:
    from app.routers.admin import router

    app = FastAPI()
    app.include_router(router)
    return app


def _make_db_ctx(db: AsyncMock) -> MagicMock:
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _scalars_returning(items):
    r = MagicMock()
    r.all.return_value = items
    return r


# ---------------------------------------------------------------------------
# _require_admin fail-closed branches
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_username_in_production_returns_503():
    app = _build_app()
    with patch("app.routers.admin.settings") as mock_settings:
        mock_settings.ADMIN_PASSWORD = "s3cret"
        mock_settings.ADMIN_USERNAME = ADMIN_USERNAME_DEFAULT
        mock_settings.APP_ENV = "production"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/publish", auth=(ADMIN_USERNAME_DEFAULT, "s3cret")
            )

    assert resp.status_code == http.HTTPStatus.SERVICE_UNAVAILABLE


@pytest.mark.asyncio
async def test_wrong_credentials_returns_401():
    app = _build_app()
    with patch("app.routers.admin.settings") as mock_settings:
        mock_settings.ADMIN_PASSWORD = "s3cret"
        mock_settings.ADMIN_USERNAME = "realadmin"
        mock_settings.APP_ENV = "production"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/admin/publish", auth=("realadmin", "wrong"))

    assert resp.status_code == http.HTTPStatus.UNAUTHORIZED


# ---------------------------------------------------------------------------
# GET /admin/ingest  &  POST /admin/ingest/{slug}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_all_returns_results():
    app = _build_app()
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
            resp = await client.get("/admin/ingest", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    assert resp.json()["results"] == [{"slug": "fienta", "raw_count": 5}]


@pytest.mark.asyncio
async def test_ingest_source_unknown_slug_404():
    app = _build_app()
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
async def test_ingest_source_value_error_400():
    app = _build_app()
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

    assert resp.status_code == http.HTTPStatus.BAD_REQUEST


@pytest.mark.asyncio
async def test_ingest_source_success():
    app = _build_app()
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
    assert resp.json()["new_count"] == 1


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
async def test_simple_job_triggers(path, target):
    app = _build_app()
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
    assert resp.json() == {"done": 1}
    mock_job.assert_awaited_once()


# ---------------------------------------------------------------------------
# GET /admin/dedup/groups
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dedup_groups_empty_page():
    app = _build_app()
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=0)
    db.scalars = AsyncMock(return_value=_scalars_returning([]))

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=_make_db_ctx(db)),
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
async def test_dedup_groups_populated_page():
    from datetime import datetime, timezone

    app = _build_app()
    ev = MagicMock()
    ev.id = 11
    ev.dedup_group_id = 5
    ev.title_orig = "Jazz"
    ev.starts_at = datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc)
    ev.venue_name = "Club"
    ev.status = "published"
    ev.url = "https://x"
    ev.is_explicit = False

    db = AsyncMock()
    db.scalar = AsyncMock(return_value=1)  # total_groups
    # first scalars() -> page group ids; second -> event rows
    db.scalars = AsyncMock(
        side_effect=[_scalars_returning([5]), _scalars_returning([ev])]
    )

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=_make_db_ctx(db)),
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
async def test_stats_returns_counts():
    app = _build_app()
    db = AsyncMock()
    # total, canonical, sources_total, sources_enabled
    db.scalar = AsyncMock(side_effect=[100, 60, 8, 5])

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=_make_db_ctx(db)),
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
