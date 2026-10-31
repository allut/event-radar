"""Coverage for the admin job-trigger endpoints (routers/admin_jobs.py) beyond
test_admin_jobs.py: POST /admin/ingest, /admin/ingest/{slug}, /admin/dedup,
/admin/classify and /admin/refetch."""

import http
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.constants.core import APP_ENV_DEVELOPMENT
from tests.routers.conftest import ndjson_lines, patch_admin_settings


# ---------------------------------------------------------------------------
# POST /admin/ingest  &  POST /admin/ingest/{slug}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_all_returns_results(admin_app):
    app = admin_app
    with (
        patch_admin_settings() as mock_settings,
        patch(
            "app.routers.admin_jobs.ingest_all_enabled",
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
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin_jobs.ADAPTER_REGISTRY", {}),
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
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin_jobs.ADAPTER_REGISTRY", {"fienta": MagicMock()}),
        patch(
            "app.routers.admin_jobs.ingest_source",
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
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin_jobs.ADAPTER_REGISTRY", {"fienta": MagicMock()}),
        patch(
            "app.routers.admin_jobs.ingest_source",
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,target",
    [
        ("/admin/dedup", "app.routers.admin_jobs.dedup_pass_drain_now"),
        ("/admin/classify", "app.routers.admin_jobs.classify_pending_drain_now"),
        ("/admin/refetch", "app.routers.admin_jobs.refetch_event_details_job"),
    ],
)
async def test_simple_job_triggers(path, target, admin_app):
    app = admin_app
    with (
        patch_admin_settings() as mock_settings,
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
