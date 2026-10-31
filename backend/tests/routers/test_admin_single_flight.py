"""Single-flight guard tests for the expensive/destructive admin triggers
(issue #160): a second concurrent call to pipeline/run, cleanup, full
ingest, send_digests, or classify gets 409 instead of starting a duplicate
run. Each test blocks the trigger's underlying job on an asyncio.Event to
simulate an in-flight run, fires a second request while the first is still
running, then unblocks the first so it completes normally.
"""
import asyncio
import http
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.constants.core import APP_ENV_DEVELOPMENT
from app.routers.utils import _RUNNING_ADMIN_JOBS
from tests.routers.conftest import patch_admin_settings


def _blocked_job(event: asyncio.Event, result: dict):
    async def _run(*_args, **_kwargs) -> dict:
        await event.wait()
        return result

    return AsyncMock(side_effect=_run)


@pytest.fixture(autouse=True)
def _clear_locks():
    """The single-flight guard is a module-level set — clear it around every
    test so a failure in one test can't leak a held lock into the next."""
    _RUNNING_ADMIN_JOBS.clear()
    yield
    _RUNNING_ADMIN_JOBS.clear()


@pytest.mark.asyncio
async def test_second_concurrent_classify_call_gets_409(admin_app):
    app = admin_app
    block = asyncio.Event()
    job = _blocked_job(block, {"classified": 1})

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin_jobs.classify_pending_drain_now", job),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            first = asyncio.create_task(client.post("/admin/classify", auth=("admin", "")))
            await asyncio.sleep(0.05)

            second = await client.post("/admin/classify", auth=("admin", ""))
            assert second.status_code == http.HTTPStatus.CONFLICT

            block.set()
            first_resp = await first
            assert first_resp.status_code == http.HTTPStatus.OK

    job.assert_awaited_once()


@pytest.mark.asyncio
async def test_second_concurrent_full_ingest_call_gets_409(admin_app):
    app = admin_app
    block = asyncio.Event()
    job = _blocked_job(block, [])

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin_jobs.ingest_all_enabled", job),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            first = asyncio.create_task(client.post("/admin/ingest", auth=("admin", "")))
            await asyncio.sleep(0.05)

            second = await client.post("/admin/ingest", auth=("admin", ""))
            assert second.status_code == http.HTTPStatus.CONFLICT

            block.set()
            first_resp = await first
            assert first_resp.status_code == http.HTTPStatus.OK

    job.assert_awaited_once()


@pytest.mark.asyncio
async def test_second_concurrent_cleanup_call_gets_409(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db_ctx = make_db_ctx(mock_db)
    block = asyncio.Event()
    job = _blocked_job(block, {})

    with (
        patch_admin_settings() as mock_settings,
        patch("app.db.AsyncSessionLocal", return_value=db_ctx),
        patch("app.routers.admin_jobs.cleanup_stale_data", job),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            first = asyncio.create_task(client.post("/admin/cleanup", auth=("admin", "")))
            await asyncio.sleep(0.05)

            second = await client.post("/admin/cleanup", auth=("admin", ""))
            assert second.status_code == http.HTTPStatus.CONFLICT

            block.set()
            first_resp = await first
            assert first_resp.status_code == http.HTTPStatus.OK

    job.assert_awaited_once()


@pytest.mark.asyncio
async def test_second_concurrent_send_digests_call_gets_409(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db_ctx = make_db_ctx(mock_db)
    block = asyncio.Event()
    job = _blocked_job(block, {"sent": 0, "skipped": 0, "errored": 0, "total_opted_in": 0, "dry_run": True})

    with (
        patch_admin_settings() as mock_settings,
        patch("app.db.AsyncSessionLocal", return_value=db_ctx),
        patch("app.routers.admin_jobs.send_daily_digests", job),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            first = asyncio.create_task(client.post("/admin/send-digests", auth=("admin", "")))
            await asyncio.sleep(0.05)

            second = await client.post("/admin/send-digests", auth=("admin", ""))
            assert second.status_code == http.HTTPStatus.CONFLICT

            block.set()
            first_resp = await first
            assert first_resp.status_code == http.HTTPStatus.OK

    job.assert_awaited_once()


@pytest.mark.asyncio
async def test_second_concurrent_pipeline_run_call_gets_409(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db_ctx = make_db_ctx(mock_db)
    block = asyncio.Event()
    # Only the first stage (sync_organizers) blocks — the other six stages
    # must be mocked too, or the run would fall through to real ingestion/
    # DB calls once unblocked (this hung for real before being mocked).
    job = _blocked_job(block, {"added": [], "stale": []})

    with (
        patch_admin_settings() as mock_settings,
        patch("app.db.AsyncSessionLocal", return_value=db_ctx),
        patch("app.routers.admin_jobs.sync_fienta_organizers", job),
        patch("app.routers.admin_jobs.ingest_all_enabled", AsyncMock(return_value=[])),
        patch("app.routers.admin_jobs.dedup_pass_drain_now", AsyncMock(return_value={"merged": 0})),
        patch("app.routers.admin_jobs.classify_pending_drain_now", AsyncMock(return_value={"classified": 0})),
        patch("app.routers.admin_jobs.publish_pending_job", AsyncMock(return_value={"published": 0})),
        patch("app.routers.admin_jobs.build_daily_feeds", AsyncMock(return_value={"built": 0, "empty": 0, "total_users": 0, "candidate_events": 0})),
        patch("app.routers.admin_jobs.send_daily_digests", AsyncMock(return_value={"sent": 0, "skipped": 0, "errored": 0, "total_opted_in": 0, "dry_run": True})),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            first = asyncio.create_task(client.post("/admin/pipeline/run", auth=("admin", "")))
            await asyncio.sleep(0.05)

            second = await client.post("/admin/pipeline/run", auth=("admin", ""))
            assert second.status_code == http.HTTPStatus.CONFLICT

            block.set()
            first_resp = await first
            assert first_resp.status_code == http.HTTPStatus.OK

    job.assert_awaited_once()


@pytest.mark.asyncio
async def test_standalone_classify_blocked_while_pipeline_run_is_mid_classify_stage(admin_app, make_db_ctx, mock_db):
    """Regression: pipeline/run only held its own lock, not the locks for the
    ingest/classify/send_digests sub-stages it runs internally — a standalone
    trigger for one of those stages could run concurrently with the
    pipeline's own execution of that same stage."""
    app = admin_app
    db_ctx = make_db_ctx(mock_db)
    block = asyncio.Event()
    classify_job = _blocked_job(block, {"classified": 1})

    with (
        patch_admin_settings() as mock_settings,
        patch("app.db.AsyncSessionLocal", return_value=db_ctx),
        patch("app.routers.admin_jobs.sync_fienta_organizers", AsyncMock(return_value={"added": [], "stale": []})),
        patch("app.routers.admin_jobs.ingest_all_enabled", AsyncMock(return_value=[])),
        patch("app.routers.admin_jobs.dedup_pass_drain_now", AsyncMock(return_value={"merged": 0})),
        patch("app.routers.admin_jobs.classify_pending_drain_now", classify_job),
        patch("app.routers.admin_jobs.publish_pending_job", AsyncMock(return_value={"published": 0})),
        patch("app.routers.admin_jobs.build_daily_feeds", AsyncMock(return_value={"built": 0, "empty": 0, "total_users": 0, "candidate_events": 0})),
        patch("app.routers.admin_jobs.send_daily_digests", AsyncMock(return_value={"sent": 0, "skipped": 0, "errored": 0, "total_opted_in": 0, "dry_run": True})),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            pipeline = asyncio.create_task(client.post("/admin/pipeline/run", auth=("admin", "")))
            await asyncio.sleep(0.05)

            standalone_classify = await client.post("/admin/classify", auth=("admin", ""))
            assert standalone_classify.status_code == http.HTTPStatus.CONFLICT

            block.set()
            pipeline_resp = await pipeline
            assert pipeline_resp.status_code == http.HTTPStatus.OK

    classify_job.assert_awaited_once()


@pytest.mark.asyncio
async def test_lock_released_after_completion_allows_a_later_call(admin_app):
    """Not concurrent — proves the guard doesn't wedge the trigger shut
    after a run finishes."""
    app = admin_app

    with (
        patch_admin_settings() as mock_settings,
        patch(
            "app.routers.admin_jobs.classify_pending_drain_now",
            new_callable=AsyncMock,
            return_value={"classified": 1},
        ),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            first = await client.post("/admin/classify", auth=("admin", ""))
            second = await client.post("/admin/classify", auth=("admin", ""))

    assert first.status_code == http.HTTPStatus.OK
    assert second.status_code == http.HTTPStatus.OK
