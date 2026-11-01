"""Coverage for the durable AdminAction audit row written by
log_admin_action() (app/routers/utils/admin.py) for the report queue — resolve and
takedown each add exactly one AdminAction to the caller's db session with the
expected action/target, and no row is added when the lookup 404s before
log_admin_action is ever called."""

import http
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.constants.admin import (
    ADMIN_ACTION_RESOLVE_REPORTS,
    ADMIN_ACTION_TAKEDOWN_REPORTED_EVENT,
)
from app.constants.core import APP_ENV_DEVELOPMENT
from tests.routers.conftest import admin_action_calls, patch_admin_settings, scalars_returning


# ---------------------------------------------------------------------------
# POST /admin/reports/{id}/resolve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_reports_writes_one_admin_action_row(
    admin_app, make_db_ctx, mock_db, make_event, make_report, make_user
):
    app = admin_app
    event = make_event(event_id=42, status="published")
    report = make_report(report_id=1, event_id=42, status="open")
    reporter = make_user(user_id=report.user_id)

    db = mock_db
    db.get = AsyncMock(return_value=event)
    db.execute = AsyncMock(
        return_value=MagicMock(scalars=lambda: scalars_returning([report]))
    )
    db.scalars = AsyncMock(return_value=scalars_returning([reporter]))

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin_reports.AsyncSessionLocal", return_value=make_db_ctx(db)),
        patch("app.events.cancellation.send_report_outcome_email", new=AsyncMock()),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/reports/42/resolve",
                json={"resolution_note": "Looked into it."},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.OK
    rows = admin_action_calls(db)
    assert len(rows) == 1
    assert rows[0].action == ADMIN_ACTION_RESOLVE_REPORTS
    assert rows[0].target == "42"


@pytest.mark.asyncio
async def test_resolve_reports_writes_no_admin_action_row_when_not_found(
    admin_app, make_db_ctx, mock_db
):
    app = admin_app
    db = mock_db
    db.get = AsyncMock(return_value=None)

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin_reports.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/reports/999/resolve",
                json={"resolution_note": "n/a"},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.NOT_FOUND
    assert admin_action_calls(db) == []


# ---------------------------------------------------------------------------
# POST /admin/reports/{id}/takedown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_takedown_writes_one_admin_action_row(
    admin_app, make_db_ctx, mock_db, make_event, make_report, make_user
):
    app = admin_app
    event = make_event(event_id=42, status="published")
    report = make_report(report_id=1, event_id=42, status="open")
    reporter = make_user(user_id=report.user_id)

    db = mock_db
    db.get = AsyncMock(return_value=event)
    db.execute = AsyncMock(
        return_value=MagicMock(scalars=lambda: scalars_returning([report]))
    )
    db.scalars = AsyncMock(return_value=scalars_returning([reporter]))

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin_reports.AsyncSessionLocal", return_value=make_db_ctx(db)),
        patch("app.events.cancellation.send_report_outcome_email", new=AsyncMock()),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/reports/42/takedown",
                json={"resolution_note": "Content violates policy."},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.OK
    rows = admin_action_calls(db)
    assert len(rows) == 1
    assert rows[0].action == ADMIN_ACTION_TAKEDOWN_REPORTED_EVENT
    assert rows[0].target == "42"


@pytest.mark.asyncio
async def test_takedown_writes_no_admin_action_row_when_not_found(
    admin_app, make_db_ctx, mock_db
):
    app = admin_app
    db = mock_db
    db.get = AsyncMock(return_value=None)

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin_reports.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/reports/999/takedown",
                json={"resolution_note": "n/a"},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.NOT_FOUND
    assert admin_action_calls(db) == []
