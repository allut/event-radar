"""Tests for the admin organizer-submission review queue:
GET /admin/submissions, POST /admin/submissions/{id}/retract,
POST /admin/submissions/{id}/approve."""

import http
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.constants import (
    ADMIN_ACTION_APPROVE_SUBMISSION,
    ADMIN_ACTION_RETRACT_SUBMISSION,
    APP_ENV_DEVELOPMENT,
    EVENT_STATUS_CANCELLED,
)
from tests.routers.conftest import patch_admin_settings, scalars_returning


# ---------------------------------------------------------------------------
# GET /admin/submissions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_submissions_empty_page(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db = mock_db
    db.scalar = AsyncMock(return_value=0)
    db.scalars = AsyncMock(return_value=scalars_returning([]))

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/admin/submissions", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    body = resp.json()
    assert body["total"] == 0
    assert body["events"] == []
    assert body["has_more"] is False


@pytest.mark.asyncio
async def test_list_submissions_populated_page(admin_app, make_db_ctx, mock_db, make_event):
    app = admin_app
    event = make_event(event_id=42, status="published")
    event.submitted_by_organizer_id = 7
    event.needs_review = True

    db = mock_db
    db.scalar = AsyncMock(return_value=1)  # total
    db.scalars = AsyncMock(return_value=scalars_returning([event]))

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/admin/submissions", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    body = resp.json()
    assert body["total"] == 1
    assert body["events"][0]["id"] == 42
    assert body["events"][0]["status"] == "published"
    assert body["events"][0]["submitted_by_organizer_id"] == 7


@pytest.mark.asyncio
async def test_list_submissions_excludes_cancelled(admin_app, make_db_ctx, mock_db):
    """A cancelled submission must never surface in the queue, regardless of
    its needs_review flag — retract() already clears it, but this filter is
    defense-in-depth against that invariant drifting."""
    app = admin_app
    db = mock_db
    db.scalar = AsyncMock(return_value=0)
    db.scalars = AsyncMock(return_value=scalars_returning([]))

    captured: dict = {}

    def _capture_scalar(stmt):
        captured["count_stmt"] = stmt
        return 0

    db.scalar = AsyncMock(side_effect=_capture_scalar)

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/admin/submissions", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    sql = str(captured["count_stmt"])
    assert "events.status !=" in sql or "events.status IS DISTINCT FROM" in sql


# ---------------------------------------------------------------------------
# POST /admin/submissions/{id}/retract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retract_submission_cancels_event(admin_app, make_db_ctx, mock_db, make_event, caplog):
    app = admin_app
    event = make_event(event_id=42, status="published")
    event.submitted_by_organizer_id = 7

    db = mock_db
    db.get = AsyncMock(return_value=event)
    db.execute = AsyncMock(return_value=MagicMock(scalars=lambda: scalars_returning([])))

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
        caplog.at_level("INFO"),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/submissions/42/retract",
                json={"resolution_note": "Duplicate of an existing listing."},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.OK
    assert event.status == EVENT_STATUS_CANCELLED
    assert event.needs_review is False  # resolves the review-queue entry outright
    assert resp.json() == {
        "id": 42,
        "status": EVENT_STATUS_CANCELLED,
        "note": "Duplicate of an existing listing.",
    }

    admin_action_records = [
        r for r in caplog.records if getattr(r, "event", None) == "admin_action"
    ]
    assert len(admin_action_records) == 1
    assert admin_action_records[0].action == ADMIN_ACTION_RETRACT_SUBMISSION
    assert admin_action_records[0].target == 42


@pytest.mark.asyncio
async def test_retract_submission_auto_resolves_open_reports(
    admin_app, make_db_ctx, mock_db, make_event, make_report, make_user
):
    """Cancelling via retract must auto-resolve the event's open reports
    through the shared resolve_open_reports() helper (issue #125), so a
    reporter isn't left with a permanently "open" report on a dead event."""
    app = admin_app
    event = make_event(event_id=42, status="published")
    event.submitted_by_organizer_id = 7
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
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
        patch("app.events.cancellation.send_report_outcome_email", new=AsyncMock()),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/submissions/42/retract",
                json={"resolution_note": "Duplicate of an existing listing."},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.OK
    assert report.status == "resolved"
    assert report.resolution_note == "auto-resolved: event cancelled"


@pytest.mark.asyncio
async def test_retract_non_submission_returns_404(admin_app, make_db_ctx, mock_db):
    """An event with no submitted_by_organizer_id (a normally-scraped event)
    is not a "submission" and must not be retractable via this route."""
    app = admin_app
    event = MagicMock()
    event.submitted_by_organizer_id = None

    db = mock_db
    db.get = AsyncMock(return_value=event)

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/submissions/42/retract",
                json={"resolution_note": "Duplicate of an existing listing."},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_retract_submission_requires_nonblank_note(admin_app, make_db_ctx, mock_db, make_event):
    app = admin_app
    event = make_event(event_id=42, status="published")
    event.submitted_by_organizer_id = 7

    db = mock_db
    db.get = AsyncMock(return_value=event)

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/submissions/42/retract",
                json={"resolution_note": "   "},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.UNPROCESSABLE_ENTITY


# ---------------------------------------------------------------------------
# POST /admin/submissions/{id}/approve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_submission_clears_needs_review(admin_app, make_db_ctx, mock_db, make_event, make_organizer, caplog):
    app = admin_app
    event = make_event(event_id=42, status="published")
    event.submitted_by_organizer_id = 7
    event.needs_review = True
    organizer = make_organizer(organizer_id=7)
    organizer.verified = False

    db = mock_db

    async def _get(model, pk):
        from app.models.models import Event, Organizer

        if model is Event:
            return event
        if model is Organizer:
            return organizer
        raise AssertionError(f"unexpected db.get({model!r}, {pk!r})")

    db.get = AsyncMock(side_effect=_get)

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
        patch(
            "app.routers.admin.publish_pending", new_callable=AsyncMock
        ) as mock_publish,
        caplog.at_level("INFO"),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/submissions/42/approve",
                json={"resolution_note": "Looks good."},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.OK
    assert event.needs_review is False
    assert resp.json() == {"id": 42, "needs_review": False, "note": "Looks good."}
    # M2: a first approval is what makes the organizer trusted going forward.
    assert organizer.verified is True
    # The publish gate must run inline so this event (now eligible) goes live
    # immediately rather than waiting for the next scheduled pass.
    mock_publish.assert_awaited_once_with(db, diagnostics=False)

    admin_action_records = [
        r for r in caplog.records if getattr(r, "event", None) == "admin_action"
    ]
    assert len(admin_action_records) == 1
    assert admin_action_records[0].action == ADMIN_ACTION_APPROVE_SUBMISSION
    assert admin_action_records[0].target == 42


@pytest.mark.asyncio
async def test_approve_submission_requires_nonblank_note(admin_app, make_db_ctx, mock_db, make_event):
    app = admin_app
    event = make_event(event_id=42, status="published")
    event.submitted_by_organizer_id = 7

    db = mock_db
    db.get = AsyncMock(return_value=event)

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/submissions/42/approve",
                json={"resolution_note": "   "},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_approve_submission_with_no_submitting_organizer_still_publishes(
    admin_app, make_db_ctx, mock_db, make_event,
):
    """Defense-in-depth: submitted_by_organizer_id is set (this event passed
    _submission_or_404's filter), but the referenced Organizer row is
    somehow already gone — the handler must not crash and must still run
    the publish gate."""
    app = admin_app
    event = make_event(event_id=42, status="published")
    event.submitted_by_organizer_id = 7
    event.needs_review = True

    db = mock_db

    async def _get(model, pk):
        from app.models.models import Event, Organizer

        if model is Event:
            return event
        if model is Organizer:
            return None
        raise AssertionError(f"unexpected db.get({model!r}, {pk!r})")

    db.get = AsyncMock(side_effect=_get)

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
        patch(
            "app.routers.admin.publish_pending", new_callable=AsyncMock
        ) as mock_publish,
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/submissions/42/approve",
                json={"resolution_note": "Looks good."},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.OK
    mock_publish.assert_awaited_once_with(db, diagnostics=False)
