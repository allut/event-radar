"""Tests for the admin content-moderation report queue (issue #125):
GET /admin/reports, POST /admin/reports/{id}/resolve,
POST /admin/reports/{id}/takedown."""

import http
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.constants import (
    ADMIN_ACTION_RESOLVE_REPORTS,
    ADMIN_ACTION_TAKEDOWN_REPORTED_EVENT,
    APP_ENV_DEVELOPMENT,
    EVENT_CANCELLATION_REASON_REPORT_TAKEDOWN,
    EVENT_STATUS_CANCELLED,
)
from tests.routers.conftest import execute_rows, scalars_returning


# ---------------------------------------------------------------------------
# GET /admin/reports
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_reports_empty_page(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db = mock_db
    db.scalar = AsyncMock(return_value=0)
    db.execute = AsyncMock(return_value=execute_rows([]))

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/admin/reports", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    body = resp.json()
    assert body["total"] == 0
    assert body["events"] == []
    assert body["has_more"] is False


@pytest.mark.asyncio
async def test_list_reports_groups_one_row_per_event(
    admin_app, make_db_ctx, mock_db, make_event, make_report
):
    """A 2-times-reported event must render as one queue row aggregating
    both reports, not two rows."""
    app = admin_app
    event = make_event(event_id=42, status="published")
    event.submitted_by_organizer_id = None

    agg_row = MagicMock(
        event_id=42,
        has_illegal_allegation=True,
        report_count=2,
        oldest_open_report_at="2026-05-13T06:00:00+00:00",
    )
    report_a = make_report(
        report_id=1, event_id=42, reason="spam_or_scam", is_illegal_allegation=True
    )
    report_b = make_report(
        report_id=2, event_id=42, reason="wrong_location", is_illegal_allegation=False
    )

    db = mock_db
    db.scalar = AsyncMock(return_value=1)  # total
    db.execute = AsyncMock(return_value=execute_rows([agg_row]))
    db.scalars = AsyncMock(
        side_effect=[
            scalars_returning([event]),  # bulk Event load
            scalars_returning([report_a, report_b]),  # bulk EventReport load
        ]
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
            resp = await client.get("/admin/reports", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    body = resp.json()
    assert body["total"] == 1
    assert len(body["events"]) == 1
    row = body["events"][0]
    assert row["event_id"] == 42
    assert row["report_count"] == 2
    assert row["has_illegal_allegation"] is True
    assert sorted(row["reasons"]) == ["spam_or_scam", "wrong_location"]
    assert len(row["reports"]) == 2


@pytest.mark.asyncio
async def test_list_reports_venue_prefers_joined_venue_when_linked(
    admin_app, make_db_ctx, mock_db, make_event, make_venue, make_report
):
    """#177: the reports queue must prefer the joined Venue over Event's own
    (write-time-NULL) venue_name once venue_id is set."""
    app = admin_app
    venue = make_venue(name="Telliskivi Creative City", name_en="Telliskivi Loomelinnak")
    event = make_event(event_id=42, status="published", venue_id=1, venue=venue, venue_name=None)
    event.submitted_by_organizer_id = None

    agg_row = MagicMock(
        event_id=42,
        has_illegal_allegation=False,
        report_count=1,
        oldest_open_report_at="2026-05-13T06:00:00+00:00",
    )
    report_a = make_report(report_id=1, event_id=42, reason="spam_or_scam")

    db = mock_db
    db.scalar = AsyncMock(return_value=1)
    db.execute = AsyncMock(return_value=execute_rows([agg_row]))
    db.scalars = AsyncMock(
        side_effect=[scalars_returning([event]), scalars_returning([report_a])]
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
            resp = await client.get("/admin/reports", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    row = resp.json()["events"][0]
    # admin console has no locale/i18n loop — DEFAULT_USER_LOCALE ("en") applies.
    assert row["venue"] == "Telliskivi Loomelinnak"


@pytest.mark.asyncio
async def test_list_reports_invalid_reason_rejected(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db = mock_db

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/admin/reports", params={"reason": "not_a_real_reason"}, auth=("admin", "")
            )

    assert resp.status_code == http.HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_list_reports_excludes_cancelled(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db = mock_db
    captured: dict = {}

    async def _capture_execute(stmt):
        captured["agg_stmt"] = stmt
        return execute_rows([])

    db.scalar = AsyncMock(return_value=0)
    db.execute = AsyncMock(side_effect=_capture_execute)

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/admin/reports", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    sql = str(captured["agg_stmt"])
    assert "events.status !=" in sql or "events.status IS DISTINCT FROM" in sql


# ---------------------------------------------------------------------------
# POST /admin/reports/{id}/resolve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_reports_closes_open_reports_no_event_mutation(
    admin_app, make_db_ctx, mock_db, make_event, make_report, make_user, caplog
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
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
        patch(
            "app.routers.utils.send_report_outcome_email", new=AsyncMock()
        ) as mock_send,
        caplog.at_level("INFO"),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/reports/42/resolve",
                json={"resolution_note": "Looked into it, event is fine."},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.OK
    assert resp.json() == {"event_id": 42, "resolved_count": 1}
    assert report.status == "resolved"
    assert report.resolution_note == "Looked into it, event is fine."
    assert report.resolved_at is not None

    admin_action_records = [
        r for r in caplog.records if getattr(r, "event", None) == "admin_action"
    ]
    assert len(admin_action_records) == 1
    assert admin_action_records[0].action == ADMIN_ACTION_RESOLVE_REPORTS
    assert admin_action_records[0].target == 42
    assert event.status == "published"  # resolve never mutates the event
    mock_send.assert_awaited_once_with(
        reporter.email,
        event,
        "Looked into it, event is fine.",
        reporter.locale,
        reporter.theme_preference,
        http_client=ANY,
    )


@pytest.mark.asyncio
async def test_resolve_reports_requires_nonblank_note(admin_app, make_db_ctx, mock_db, make_event):
    app = admin_app
    event = make_event(event_id=42, status="published")

    db = mock_db
    db.get = AsyncMock(return_value=event)

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/reports/42/resolve",
                json={"resolution_note": "   "},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_resolve_reports_event_not_found(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db = mock_db
    db.get = AsyncMock(return_value=None)

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
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


# ---------------------------------------------------------------------------
# POST /admin/reports/{id}/takedown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_takedown_cancels_event_and_resolves_reports(
    admin_app, make_db_ctx, mock_db, make_event, make_report, make_user, caplog
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
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
        patch("app.routers.utils.send_report_outcome_email", new=AsyncMock()),
        caplog.at_level("INFO"),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/reports/42/takedown",
                json={"resolution_note": "Confirmed spam, taken down."},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.OK
    body = resp.json()
    assert body == {
        "event_id": 42,
        "status": EVENT_STATUS_CANCELLED,
        "resolved_count": 1,
    }
    assert event.status == EVENT_STATUS_CANCELLED
    assert event.cancellation_reason == EVENT_CANCELLATION_REASON_REPORT_TAKEDOWN
    assert report.status == "resolved"
    assert report.resolution_note == "Confirmed spam, taken down."

    admin_action_records = [
        r for r in caplog.records if getattr(r, "event", None) == "admin_action"
    ]
    assert len(admin_action_records) == 1
    assert admin_action_records[0].action == ADMIN_ACTION_TAKEDOWN_REPORTED_EVENT
    assert admin_action_records[0].target == 42
