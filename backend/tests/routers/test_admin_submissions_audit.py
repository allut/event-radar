"""Coverage for the durable AdminAction audit row written by
log_admin_action() (app/routers/utils.py) for the submission queue — approve and
retract each add exactly one AdminAction to the caller's db session with the
expected action/target, and no row is added when the mutation itself raises
before log_admin_action is ever called (e.g. a 404 lookup)."""

import http
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.constants.admin import (
    ADMIN_ACTION_APPROVE_SUBMISSION,
    ADMIN_ACTION_RETRACT_SUBMISSION,
)
from app.constants.core import APP_ENV_DEVELOPMENT
from tests.routers.conftest import admin_action_calls, patch_admin_settings, scalars_returning


# ---------------------------------------------------------------------------
# POST /admin/submissions/{id}/retract
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retract_writes_one_admin_action_row(admin_app, make_db_ctx, mock_db, make_event):
    app = admin_app
    event = make_event(event_id=42, status="published")
    event.submitted_by_organizer_id = 7

    db = mock_db
    db.get = AsyncMock(return_value=event)
    db.execute = AsyncMock(return_value=MagicMock(scalars=lambda: scalars_returning([])))

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin_submissions.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/submissions/42/retract",
                json={"resolution_note": "Duplicate."},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.OK
    rows = admin_action_calls(db)
    assert len(rows) == 1
    assert rows[0].action == ADMIN_ACTION_RETRACT_SUBMISSION
    assert rows[0].target == "42"


@pytest.mark.asyncio
async def test_retract_writes_no_admin_action_row_when_not_found(
    admin_app, make_db_ctx, mock_db
):
    app = admin_app
    event = MagicMock()
    event.submitted_by_organizer_id = None

    db = mock_db
    db.get = AsyncMock(return_value=event)

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin_submissions.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/submissions/42/retract",
                json={"resolution_note": "Duplicate."},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.NOT_FOUND
    assert admin_action_calls(db) == []


# ---------------------------------------------------------------------------
# POST /admin/submissions/{id}/approve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_writes_one_admin_action_row(
    admin_app, make_db_ctx, mock_db, make_event, make_organizer
):
    app = admin_app
    event = make_event(event_id=42, status="published")
    event.submitted_by_organizer_id = 7
    event.needs_review = True
    organizer = make_organizer(organizer_id=7)
    organizer.verified = False

    db = mock_db

    async def _get(model, pk):
        from app.models.events import Event
        from app.models.organizers import Organizer

        if model is Event:
            return event
        if model is Organizer:
            return organizer
        raise AssertionError(f"unexpected db.get({model!r}, {pk!r})")

    db.get = AsyncMock(side_effect=_get)

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin_submissions.AsyncSessionLocal", return_value=make_db_ctx(db)),
        patch("app.routers.admin_submissions.publish_pending", new_callable=AsyncMock),
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
    rows = admin_action_calls(db)
    assert len(rows) == 1
    assert rows[0].action == ADMIN_ACTION_APPROVE_SUBMISSION
    assert rows[0].target == "42"


@pytest.mark.asyncio
async def test_approve_writes_no_admin_action_row_when_not_found(
    admin_app, make_db_ctx, mock_db
):
    app = admin_app
    event = MagicMock()
    event.submitted_by_organizer_id = None

    db = mock_db
    db.get = AsyncMock(return_value=event)

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin_submissions.AsyncSessionLocal", return_value=make_db_ctx(db)),
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

    assert resp.status_code == http.HTTPStatus.NOT_FOUND
    assert admin_action_calls(db) == []


# ---------------------------------------------------------------------------
# Ordering: the Axiom log line must not fire if the commit itself fails.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_logs_nothing_when_commit_fails(
    admin_app, make_db_ctx, mock_db, make_event, make_organizer, caplog
):
    """A commit failure must not leave an Axiom admin_action line asserting
    an approval that the database never durably recorded (the ordering bug
    this audit-log rework fixes)."""
    app = admin_app
    event = make_event(event_id=42, status="published")
    event.submitted_by_organizer_id = 7
    event.needs_review = True
    organizer = make_organizer(organizer_id=7)
    organizer.verified = False

    db = mock_db

    async def _get(model, pk):
        from app.models.events import Event
        from app.models.organizers import Organizer

        if model is Event:
            return event
        if model is Organizer:
            return organizer
        raise AssertionError(f"unexpected db.get({model!r}, {pk!r})")

    db.get = AsyncMock(side_effect=_get)
    db.commit = AsyncMock(side_effect=RuntimeError("relation does not exist"))

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin_submissions.AsyncSessionLocal", return_value=make_db_ctx(db)),
        patch("app.routers.admin_submissions.publish_pending", new_callable=AsyncMock),
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

    assert resp.status_code == http.HTTPStatus.INTERNAL_SERVER_ERROR
    # The row was still added to the session (rides the same transaction the
    # commit rolled back) ...
    assert len(admin_action_calls(db)) == 1
    # ... but the Axiom log line must never fire for a commit that failed.
    admin_action_records = [
        r for r in caplog.records if getattr(r, "event", None) == "admin_action"
    ]
    assert admin_action_records == []
