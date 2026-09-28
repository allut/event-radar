"""Unit tests for new manual-trigger admin endpoints.

Uses a minimal FastAPI app with the admin router. ADMIN_PASSWORD is left
unset so APP_ENV=development lets any credentials through (mirrors the
behaviour tested in test_webhooks.py for RESEND_WEBHOOK_SECRET).
"""
import http
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.constants import APP_ENV_DEVELOPMENT
from tests.routers.conftest import ndjson_lines, patch_admin_settings


# ---------------------------------------------------------------------------
# POST /admin/sync-organizers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_organizers_calls_job_and_returns_result(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db_ctx = make_db_ctx(mock_db)
    expected = {"added": [], "stale": []}

    with (
        patch_admin_settings() as mock_settings,
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
    lines = ndjson_lines(resp)
    assert len(lines) == 1
    assert lines[0]["status"] == "ok"
    assert lines[0]["result"] == expected
    mock_sync.assert_awaited_once()


@pytest.mark.asyncio
async def test_sync_organizers_returns_500_on_job_error(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db_ctx = make_db_ctx(mock_db)

    with (
        patch_admin_settings() as mock_settings,
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

    assert resp.status_code == http.HTTPStatus.OK
    lines = ndjson_lines(resp)
    assert len(lines) == 1
    assert lines[0]["status"] == "error"
    assert lines[0]["result"] is None
    assert "fienta down" not in lines[0]["error"]


# ---------------------------------------------------------------------------
# POST /admin/cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cleanup_defaults_to_dry_run_and_does_not_commit(admin_app, make_db_ctx, mock_db):
    """Matches every other destructive admin/maintenance tool's dry-run-first convention."""
    app = admin_app
    db_ctx = make_db_ctx(mock_db)
    expected = {"auth_magic_links": 3, "llm_calls": 10}

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.utils.AsyncSessionLocal", return_value=db_ctx),
        patch(
            "app.routers.admin.cleanup_stale_data",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_cleanup,
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/admin/cleanup", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    lines = ndjson_lines(resp)
    assert lines[0]["status"] == "ok"
    assert lines[0]["result"] == expected
    mock_cleanup.assert_awaited_once_with(db_ctx.__aenter__.return_value, dry_run=True)
    db_ctx.__aenter__.return_value.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_cleanup_dry_run_false_actually_deletes_and_commits(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db_ctx = make_db_ctx(mock_db)

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.utils.AsyncSessionLocal", return_value=db_ctx),
        patch(
            "app.routers.admin.cleanup_stale_data",
            new_callable=AsyncMock,
            return_value={},
        ) as mock_cleanup,
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/admin/cleanup?dry_run=false", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    mock_cleanup.assert_awaited_once_with(db_ctx.__aenter__.return_value, dry_run=False)
    db_ctx.__aenter__.return_value.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_cleanup_returns_500_on_job_error(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db_ctx = make_db_ctx(mock_db)

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.utils.AsyncSessionLocal", return_value=db_ctx),
        patch(
            "app.routers.admin.cleanup_stale_data",
            new_callable=AsyncMock,
            side_effect=RuntimeError("db down"),
        ),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/admin/cleanup", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    lines = ndjson_lines(resp)
    assert lines[0]["status"] == "error"
    assert lines[0]["result"] is None


# ---------------------------------------------------------------------------
# POST /admin/build-feeds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_feeds_calls_job_and_returns_result(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db_ctx = make_db_ctx(mock_db)
    expected = {"built": 3, "empty": 0, "total_users": 3, "candidate_events": 12}

    with (
        patch_admin_settings() as mock_settings,
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
    lines = ndjson_lines(resp)
    assert lines[0]["status"] == "ok"
    assert lines[0]["result"] == expected
    mock_build.assert_awaited_once()


@pytest.mark.asyncio
async def test_build_feeds_returns_500_on_job_error(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db_ctx = make_db_ctx(mock_db)

    with (
        patch_admin_settings() as mock_settings,
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

    assert resp.status_code == http.HTTPStatus.OK
    lines = ndjson_lines(resp)
    assert lines[0]["status"] == "error"
    assert lines[0]["result"] is None


# ---------------------------------------------------------------------------
# POST /admin/publish
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_calls_job_and_returns_result(admin_app):
    app = admin_app
    expected = {"published": 3}

    with (
        patch_admin_settings() as mock_settings,
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
    lines = ndjson_lines(resp)
    assert lines[0]["status"] == "ok"
    assert lines[0]["result"] == expected
    mock_publish.assert_awaited_once()


@pytest.mark.asyncio
async def test_publish_returns_500_on_job_error(admin_app):
    app = admin_app

    with (
        patch_admin_settings() as mock_settings,
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

    assert resp.status_code == http.HTTPStatus.OK
    lines = ndjson_lines(resp)
    assert lines[0]["status"] == "error"
    assert lines[0]["result"] is None


# ---------------------------------------------------------------------------
# POST /admin/geocode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_geocode_calls_job_and_returns_result(admin_app):
    app = admin_app
    expected = {"geocoded": 4}

    with (
        patch_admin_settings() as mock_settings,
        patch(
            "app.routers.admin.geocode_pending_job",
            new_callable=AsyncMock,
            return_value=expected,
        ) as mock_geocode,
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/admin/geocode", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    lines = ndjson_lines(resp)
    assert lines[0]["status"] == "ok"
    assert lines[0]["result"] == expected
    mock_geocode.assert_awaited_once()


@pytest.mark.asyncio
async def test_geocode_returns_500_on_job_error(admin_app):
    app = admin_app

    with (
        patch_admin_settings() as mock_settings,
        patch(
            "app.routers.admin.geocode_pending_job",
            new_callable=AsyncMock,
            side_effect=RuntimeError("nominatim error"),
        ),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/admin/geocode", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    lines = ndjson_lines(resp)
    assert lines[0]["status"] == "error"
    assert lines[0]["result"] is None


# ---------------------------------------------------------------------------
# POST /admin/send-digests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_digests_defaults_to_dry_run(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db_ctx = make_db_ctx(mock_db)
    expected = {"sent": 2, "skipped": 0, "errored": 0, "total_opted_in": 2, "dry_run": True}

    with (
        patch_admin_settings() as mock_settings,
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
async def test_send_digests_passes_dry_run_false(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db_ctx = make_db_ctx(mock_db)
    expected = {"sent": 2, "skipped": 0, "errored": 0, "total_opted_in": 2, "dry_run": False}

    with (
        patch_admin_settings() as mock_settings,
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
async def test_send_digests_returns_500_on_job_error(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db_ctx = make_db_ctx(mock_db)

    with (
        patch_admin_settings() as mock_settings,
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

    assert resp.status_code == http.HTTPStatus.OK
    lines = ndjson_lines(resp)
    assert lines[0]["status"] == "error"
    assert lines[0]["result"] is None


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
async def test_pipeline_run_calls_all_seven_stages_in_order(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db_ctx = make_db_ctx(mock_db)
    mocks = _all_job_mocks()
    with (
        patch_admin_settings() as mock_settings,
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
    lines = ndjson_lines(resp)
    assert [line["stage"] for line in lines] == [
        "sync_organizers",
        "ingest",
        "dedup",
        "classify",
        "publish",
        "build_feeds",
        "send_digests",
    ]
    assert all(line["status"] == "ok" for line in lines)
    # All seven job mocks were awaited exactly once
    for m in mocks.values():
        m.assert_awaited_once()


@pytest.mark.asyncio
async def test_pipeline_run_defaults_to_dry_run_for_digests(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db_ctx = make_db_ctx(mock_db)
    mocks = _all_job_mocks()

    with (
        patch_admin_settings() as mock_settings,
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
async def test_pipeline_run_passes_dry_run_false_to_digests(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db_ctx = make_db_ctx(mock_db)
    mocks = _all_job_mocks()

    with (
        patch_admin_settings() as mock_settings,
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
async def test_pipeline_run_stops_on_ingest_failure(admin_app, make_db_ctx, mock_db):
    """A failure in stage 2 (ingest) must abort and not call later stages."""
    app = admin_app
    db_ctx = make_db_ctx(mock_db)
    mock_ingest = AsyncMock(side_effect=RuntimeError("source timeout"))
    mock_dedup = AsyncMock()

    with (
        patch_admin_settings() as mock_settings,
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
    lines = ndjson_lines(resp)
    assert [line["stage"] for line in lines] == ["sync_organizers", "ingest"]
    assert lines[-1]["status"] == "error"
    assert lines[-1]["stage"] == "ingest"
    # dedup must not have been called
    mock_dedup.assert_not_awaited()


@pytest.mark.asyncio
async def test_pipeline_run_stops_on_sync_failure(admin_app, make_db_ctx, mock_db):
    """A failure in stage 1 (sync_organizers) must abort immediately."""
    app = admin_app
    db_ctx = make_db_ctx(mock_db)
    mock_ingest = AsyncMock()

    with (
        patch_admin_settings() as mock_settings,
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
    lines = ndjson_lines(resp)
    assert [line["stage"] for line in lines] == ["sync_organizers"]
    assert lines[0]["status"] == "error"
    mock_ingest.assert_not_awaited()
