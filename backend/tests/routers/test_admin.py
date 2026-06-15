"""Unit tests for new manual-trigger admin endpoints.

Uses a minimal FastAPI app with the admin router. ADMIN_PASSWORD is left
unset so APP_ENV=development lets any credentials through (mirrors the
behaviour tested in test_webhooks.py for RESEND_WEBHOOK_SECRET).
"""
import http
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.constants import APP_ENV_DEVELOPMENT


# ---------------------------------------------------------------------------
# Test-app factory
# ---------------------------------------------------------------------------


def _build_app() -> FastAPI:
    from app.routers.admin import router

    app = FastAPI()
    app.include_router(router)
    return app


def _make_db_ctx(db: AsyncMock | None = None) -> MagicMock:
    """Return a mock async-context-manager that yields *db* on __aenter__."""
    if db is None:
        db = AsyncMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


# ---------------------------------------------------------------------------
# POST /admin/sync-organizers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_organizers_calls_job_and_returns_result():
    app = _build_app()
    db_ctx = _make_db_ctx()
    expected = {"added": [], "stale": []}

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=db_ctx),
        patch(
            "app.routers.admin.sync_fienta_organizers",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_sync,
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/admin/sync-organizers", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    assert resp.json() == expected
    mock_sync.assert_awaited_once()


@pytest.mark.asyncio
async def test_sync_organizers_returns_500_on_job_error():
    app = _build_app()
    db_ctx = _make_db_ctx()

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=db_ctx),
        patch(
            "app.routers.admin.sync_fienta_organizers",
            new_callable=AsyncMock,
            side_effect=RuntimeError("fienta down"),
        ),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/admin/sync-organizers", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.INTERNAL_SERVER_ERROR


# ---------------------------------------------------------------------------
# POST /admin/build-feeds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_feeds_calls_job_and_returns_result():
    app = _build_app()
    db_ctx = _make_db_ctx()
    expected = {"built": 3, "empty": 0, "total_users": 3, "candidate_events": 12}

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=db_ctx),
        patch(
            "app.routers.admin.build_daily_feeds",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_build,
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/admin/build-feeds", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    assert resp.json() == expected
    mock_build.assert_awaited_once()


@pytest.mark.asyncio
async def test_build_feeds_returns_500_on_job_error():
    app = _build_app()
    db_ctx = _make_db_ctx()

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=db_ctx),
        patch(
            "app.routers.admin.build_daily_feeds",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db error"),
        ),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/admin/build-feeds", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.INTERNAL_SERVER_ERROR


# ---------------------------------------------------------------------------
# POST /admin/publish
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_calls_job_and_returns_result():
    app = _build_app()
    expected = {"published": 3}

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch(
            "app.routers.admin.publish_pending_job",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_publish,
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/admin/publish", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    assert resp.json() == expected
    mock_publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_returns_500_on_job_error():
    app = _build_app()

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch(
            "app.routers.admin.publish_pending_job",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db error"),
        ),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/admin/publish", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.INTERNAL_SERVER_ERROR


# ---------------------------------------------------------------------------
# POST /admin/send-digests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_digests_defaults_to_dry_run():
    app = _build_app()
    db_ctx = _make_db_ctx()
    expected = {"sent": 2, "skipped": 0, "errored": 0, "total_opted_in": 2, "dry_run": True}

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=db_ctx),
        patch(
            "app.routers.admin.send_daily_digests",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_send,
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/admin/send-digests", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    _, kwargs = mock_send.call_args
    assert kwargs.get("dry_run") is True


@pytest.mark.asyncio
async def test_send_digests_passes_dry_run_false():
    app = _build_app()
    db_ctx = _make_db_ctx()
    expected = {"sent": 2, "skipped": 0, "errored": 0, "total_opted_in": 2, "dry_run": False}

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=db_ctx),
        patch(
            "app.routers.admin.send_daily_digests",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_send,
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/send-digests?dry_run=false", auth=("admin", "")
            )

    assert resp.status_code == http.HTTPStatus.OK
    _, kwargs = mock_send.call_args
    assert kwargs.get("dry_run") is False


@pytest.mark.asyncio
async def test_send_digests_returns_500_on_job_error():
    app = _build_app()
    db_ctx = _make_db_ctx()

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=db_ctx),
        patch(
            "app.routers.admin.send_daily_digests",
            new_callable=AsyncMock,
            side_effect=RuntimeError("resend error"),
        ),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/admin/send-digests", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.INTERNAL_SERVER_ERROR


# ---------------------------------------------------------------------------
# POST /admin/pipeline/run
# ---------------------------------------------------------------------------


def _all_job_mocks(
    sync_result=None,
    ingest_result=None,
    dedup_result=None,
    classify_result=None,
    publish_result=None,
    feeds_result=None,
    digests_result=None,
):
    """Return a dict of patch targets → AsyncMock return values."""
    return {
        "app.routers.admin.sync_fienta_organizers": AsyncMock(
            return_value=sync_result or {"added": [], "stale": []}
        ),
        "app.routers.admin.ingest_all_enabled": AsyncMock(
            return_value=ingest_result or []
        ),
        "app.routers.admin.dedup_pass_drain_now": AsyncMock(
            return_value=dedup_result or {"merged": 0}
        ),
        "app.routers.admin.classify_pending_drain_now": AsyncMock(
            return_value=classify_result or {"classified": 0}
        ),
        "app.routers.admin.publish_pending_job": AsyncMock(
            return_value=publish_result or {"published": 0}
        ),
        "app.routers.admin.build_daily_feeds": AsyncMock(
            return_value=feeds_result
            or {"built": 1, "empty": 0, "total_users": 1, "candidate_events": 5}
        ),
        "app.routers.admin.send_daily_digests": AsyncMock(
            return_value=digests_result
            or {"sent": 1, "skipped": 0, "errored": 0, "total_opted_in": 1, "dry_run": True}
        ),
    }


@pytest.mark.asyncio
async def test_pipeline_run_calls_all_seven_stages_in_order():
    app = _build_app()
    db_ctx = _make_db_ctx()
    mocks = _all_job_mocks()
    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=db_ctx),
        patch("app.routers.admin.sync_fienta_organizers", mocks["app.routers.admin.sync_fienta_organizers"]),
        patch("app.routers.admin.ingest_all_enabled", mocks["app.routers.admin.ingest_all_enabled"]),
        patch("app.routers.admin.dedup_pass_drain_now", mocks["app.routers.admin.dedup_pass_drain_now"]),
        patch("app.routers.admin.classify_pending_drain_now", mocks["app.routers.admin.classify_pending_drain_now"]),
        patch("app.routers.admin.publish_pending_job", mocks["app.routers.admin.publish_pending_job"]),
        patch("app.routers.admin.build_daily_feeds", mocks["app.routers.admin.build_daily_feeds"]),
        patch("app.routers.admin.send_daily_digests", mocks["app.routers.admin.send_daily_digests"]),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/admin/pipeline/run", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    body = resp.json()
    assert body["ok"] is True
    assert list(body["stages"].keys()) == [
        "sync_organizers",
        "ingest",
        "dedup",
        "classify",
        "publish",
        "build_feeds",
        "send_digests",
    ]
    # All seven job mocks were awaited exactly once
    for m in mocks.values():
        m.assert_awaited_once()


@pytest.mark.asyncio
async def test_pipeline_run_defaults_to_dry_run_for_digests():
    app = _build_app()
    db_ctx = _make_db_ctx()
    mocks = _all_job_mocks()

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=db_ctx),
        patch("app.routers.admin.sync_fienta_organizers", mocks["app.routers.admin.sync_fienta_organizers"]),
        patch("app.routers.admin.ingest_all_enabled", mocks["app.routers.admin.ingest_all_enabled"]),
        patch("app.routers.admin.dedup_pass_drain_now", mocks["app.routers.admin.dedup_pass_drain_now"]),
        patch("app.routers.admin.classify_pending_drain_now", mocks["app.routers.admin.classify_pending_drain_now"]),
        patch("app.routers.admin.publish_pending_job", mocks["app.routers.admin.publish_pending_job"]),
        patch("app.routers.admin.build_daily_feeds", mocks["app.routers.admin.build_daily_feeds"]),
        patch("app.routers.admin.send_daily_digests", mocks["app.routers.admin.send_daily_digests"]),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/admin/pipeline/run", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    _, kwargs = mocks["app.routers.admin.send_daily_digests"].call_args
    assert kwargs.get("dry_run") is True


@pytest.mark.asyncio
async def test_pipeline_run_passes_dry_run_false_to_digests():
    app = _build_app()
    db_ctx = _make_db_ctx()
    mocks = _all_job_mocks()

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=db_ctx),
        patch("app.routers.admin.sync_fienta_organizers", mocks["app.routers.admin.sync_fienta_organizers"]),
        patch("app.routers.admin.ingest_all_enabled", mocks["app.routers.admin.ingest_all_enabled"]),
        patch("app.routers.admin.dedup_pass_drain_now", mocks["app.routers.admin.dedup_pass_drain_now"]),
        patch("app.routers.admin.classify_pending_drain_now", mocks["app.routers.admin.classify_pending_drain_now"]),
        patch("app.routers.admin.publish_pending_job", mocks["app.routers.admin.publish_pending_job"]),
        patch("app.routers.admin.build_daily_feeds", mocks["app.routers.admin.build_daily_feeds"]),
        patch("app.routers.admin.send_daily_digests", mocks["app.routers.admin.send_daily_digests"]),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/pipeline/run?dry_run=false", auth=("admin", "")
            )

    assert resp.status_code == http.HTTPStatus.OK
    _, kwargs = mocks["app.routers.admin.send_daily_digests"].call_args
    assert kwargs.get("dry_run") is False


@pytest.mark.asyncio
async def test_pipeline_run_stops_on_ingest_failure():
    """A failure in stage 2 (ingest) must abort and not call later stages."""
    app = _build_app()
    db_ctx = _make_db_ctx()
    mock_ingest = AsyncMock(side_effect=RuntimeError("source timeout"))
    mock_dedup = AsyncMock()

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=db_ctx),
        patch(
            "app.routers.admin.sync_fienta_organizers",
            new_callable=AsyncMock,
            return_value={"added": [], "stale": []},
        ),
        patch("app.routers.admin.ingest_all_enabled", mock_ingest),
        patch("app.routers.admin.dedup_pass_drain_now", mock_dedup),
        patch("app.routers.admin.classify_pending_drain_now", new_callable=AsyncMock),
        patch("app.routers.admin.publish_pending_job", new_callable=AsyncMock),
        patch("app.routers.admin.build_daily_feeds", new_callable=AsyncMock),
        patch("app.routers.admin.send_daily_digests", new_callable=AsyncMock),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/admin/pipeline/run", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    body = resp.json()
    assert body["ok"] is False
    assert "error" in body["stages"]["ingest"]
    # dedup must not have been called
    mock_dedup.assert_not_awaited()


@pytest.mark.asyncio
async def test_pipeline_run_stops_on_sync_failure():
    """A failure in stage 1 (sync_organizers) must abort immediately."""
    app = _build_app()
    db_ctx = _make_db_ctx()
    mock_ingest = AsyncMock()

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=db_ctx),
        patch(
            "app.routers.admin.sync_fienta_organizers",
            new_callable=AsyncMock,
            side_effect=RuntimeError("fienta down"),
        ),
        patch("app.routers.admin.ingest_all_enabled", mock_ingest),
        patch("app.routers.admin.dedup_pass_drain_now", new_callable=AsyncMock),
        patch("app.routers.admin.classify_pending_drain_now", new_callable=AsyncMock),
        patch("app.routers.admin.publish_pending_job", new_callable=AsyncMock),
        patch("app.routers.admin.build_daily_feeds", new_callable=AsyncMock),
        patch("app.routers.admin.send_daily_digests", new_callable=AsyncMock),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/admin/pipeline/run", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    body = resp.json()
    assert body["ok"] is False
    assert "error" in body["stages"]["sync_organizers"]
    mock_ingest.assert_not_awaited()
