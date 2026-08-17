"""Tests for the admin organizer-submission review queue (Phase 2 §2.2):
GET /admin/submissions, POST /admin/submissions/{id}/retract,
POST /admin/submissions/{id}/approve."""

import http
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.constants import APP_ENV_DEVELOPMENT, EVENT_STATUS_CANCELLED


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
# GET /admin/submissions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_submissions_empty_page():
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
            resp = await client.get("/admin/submissions", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    body = resp.json()
    assert body["total"] == 0
    assert body["events"] == []
    assert body["has_more"] is False


@pytest.mark.asyncio
async def test_list_submissions_populated_page(make_event):
    app = _build_app()
    event = make_event(event_id=42, status="published")
    event.submitted_by_organizer_id = 7
    event.needs_review = True

    db = AsyncMock()
    db.scalar = AsyncMock(return_value=1)  # total
    db.scalars = AsyncMock(return_value=_scalars_returning([event]))

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=_make_db_ctx(db)),
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
async def test_list_submissions_excludes_cancelled():
    """A cancelled submission must never surface in the queue, regardless of
    its needs_review flag — retract() already clears it, but this filter is
    defense-in-depth against that invariant drifting."""
    app = _build_app()
    db = AsyncMock()
    db.scalar = AsyncMock(return_value=0)
    db.scalars = AsyncMock(return_value=_scalars_returning([]))

    captured: dict = {}

    def _capture_scalar(stmt):
        captured["count_stmt"] = stmt
        return 0

    db.scalar = AsyncMock(side_effect=_capture_scalar)

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=_make_db_ctx(db)),
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
async def test_retract_submission_cancels_event(make_event):
    app = _build_app()
    event = make_event(event_id=42, status="published")
    event.submitted_by_organizer_id = 7

    db = AsyncMock()
    db.get = AsyncMock(return_value=event)
    db.commit = AsyncMock()

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=_make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/submissions/42/retract", auth=("admin", "")
            )

    assert resp.status_code == http.HTTPStatus.OK
    assert event.status == EVENT_STATUS_CANCELLED
    assert event.needs_review is False  # resolves the review-queue entry outright
    assert resp.json() == {"id": 42, "status": EVENT_STATUS_CANCELLED}


@pytest.mark.asyncio
async def test_retract_non_submission_returns_404():
    """An event with no submitted_by_organizer_id (a normally-scraped event)
    is not a "submission" and must not be retractable via this route."""
    app = _build_app()
    event = MagicMock()
    event.submitted_by_organizer_id = None

    db = AsyncMock()
    db.get = AsyncMock(return_value=event)

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=_make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/submissions/42/retract", auth=("admin", "")
            )

    assert resp.status_code == http.HTTPStatus.NOT_FOUND


# ---------------------------------------------------------------------------
# POST /admin/submissions/{id}/approve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_submission_clears_needs_review(make_event, make_organizer):
    app = _build_app()
    event = make_event(event_id=42, status="published")
    event.submitted_by_organizer_id = 7
    event.needs_review = True
    organizer = make_organizer(organizer_id=7)
    organizer.verified = False

    db = AsyncMock()

    async def _get(model, pk):
        from app.models.models import Event, Organizer

        if model is Event:
            return event
        if model is Organizer:
            return organizer
        raise AssertionError(f"unexpected db.get({model!r}, {pk!r})")

    db.get = AsyncMock(side_effect=_get)
    db.commit = AsyncMock()

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=_make_db_ctx(db)),
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
                "/admin/submissions/42/approve", auth=("admin", "")
            )

    assert resp.status_code == http.HTTPStatus.OK
    assert event.needs_review is False
    assert resp.json() == {"id": 42, "needs_review": False}
    # M2: a first approval is what makes the organizer trusted going forward.
    assert organizer.verified is True
    # The publish gate must run inline so this event (now eligible) goes live
    # immediately rather than waiting for the next scheduled pass.
    mock_publish.assert_awaited_once_with(db, diagnostics=False)


@pytest.mark.asyncio
async def test_approve_submission_with_no_submitting_organizer_still_publishes(
    make_event,
):
    """Defense-in-depth: submitted_by_organizer_id is set (this event passed
    _submission_or_404's filter), but the referenced Organizer row is
    somehow already gone — the handler must not crash and must still run
    the publish gate."""
    app = _build_app()
    event = make_event(event_id=42, status="published")
    event.submitted_by_organizer_id = 7
    event.needs_review = True

    db = AsyncMock()

    async def _get(model, pk):
        from app.models.models import Event, Organizer

        if model is Event:
            return event
        if model is Organizer:
            return None
        raise AssertionError(f"unexpected db.get({model!r}, {pk!r})")

    db.get = AsyncMock(side_effect=_get)
    db.commit = AsyncMock()

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=_make_db_ctx(db)),
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
                "/admin/submissions/42/approve", auth=("admin", "")
            )

    assert resp.status_code == http.HTTPStatus.OK
    mock_publish.assert_awaited_once_with(db, diagnostics=False)
