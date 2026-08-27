"""Tests for the admin event inspector (issue #157): GET /admin/events/{id}."""

import http
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.constants import APP_ENV_DEVELOPMENT, ERROR_EVENT_NOT_FOUND
from tests.routers.conftest import execute_rows, scalars_returning


def _fill_event_detail_fields(e: MagicMock) -> MagicMock:
    """make_event doesn't set every column the inspector serializer touches
    (submitted_by_organizer_id, needs_review, cancellation_reason,
    updated_at, detail_refetched_at, geocode_attempted_at, and the
    classification's model_used/classified_at) — fill them so the response
    is JSON-serializable, mirroring how test_admin_reports.py mutates
    make_event output ad hoc rather than growing the shared fixture."""
    e.submitted_by_organizer_id = None
    e.needs_review = False
    e.cancellation_reason = None
    e.updated_at = datetime(2026, 5, 13, 6, 0, 0, tzinfo=timezone.utc)
    e.detail_refetched_at = None
    e.geocode_attempted_at = None
    e.classification.model_used = "groq-llama"
    e.classification.classified_at = datetime(2026, 5, 13, 6, 0, 0, tzinfo=timezone.utc)
    return e


async def _get(db: AsyncMock, app, make_db_ctx, event_id: int = 42):
    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get(f"/admin/events/{event_id}", auth=("admin", ""))


@pytest.mark.asyncio
async def test_event_not_found(admin_app, make_db_ctx, mock_db):
    db = mock_db
    db.scalar = AsyncMock(return_value=None)

    resp = await _get(db, admin_app, make_db_ctx, event_id=999)

    assert resp.status_code == http.HTTPStatus.NOT_FOUND
    assert resp.json()["detail"] == ERROR_EVENT_NOT_FOUND


@pytest.mark.asyncio
async def test_curated_field_set_no_siblings_no_reports_no_raw(
    admin_app, make_db_ctx, mock_db, make_event
):
    event = make_event(event_id=42, status="draft")
    event.dedup_group_id = None
    _fill_event_detail_fields(event)

    db = mock_db
    db.scalar = AsyncMock(side_effect=[event, None])  # event fetch, feed check
    db.scalars = AsyncMock(side_effect=[scalars_returning([])])  # reports only
    db.execute = AsyncMock(return_value=execute_rows([]))  # raw_events join

    resp = await _get(db, admin_app, make_db_ctx)

    assert resp.status_code == http.HTTPStatus.OK
    body = resp.json()
    assert body["event"]["id"] == 42
    assert body["event"]["status"] == "draft"
    assert body["event"]["classification"]["model_used"] == "groq-llama"
    assert body["dedup_siblings"] == []
    assert body["reports"] == []
    assert body["raw_events"] == []
    assert body["in_todays_feed"] is False


@pytest.mark.asyncio
async def test_dedup_siblings_and_reports_included(
    admin_app, make_db_ctx, mock_db, make_event, make_report
):
    event = make_event(event_id=42, status="published")
    event.dedup_group_id = 7
    _fill_event_detail_fields(event)

    sibling = make_event(event_id=43, status="draft")
    report = make_report(report_id=1, event_id=42, reason="spam_or_scam")

    db = mock_db
    db.scalar = AsyncMock(side_effect=[event, None])
    db.scalars = AsyncMock(
        side_effect=[
            scalars_returning([sibling]),  # dedup siblings
            scalars_returning([report]),  # reports
        ]
    )
    db.execute = AsyncMock(return_value=execute_rows([]))

    resp = await _get(db, admin_app, make_db_ctx)

    assert resp.status_code == http.HTTPStatus.OK
    body = resp.json()
    assert body["dedup_siblings"] == [
        {
            "id": 43,
            "title": sibling.title_orig,
            "starts_at": sibling.starts_at.isoformat(),
            "venue": sibling.venue_name,
            "status": "draft",
            "url": sibling.url,
            "is_explicit": False,
        }
    ]
    assert len(body["reports"]) == 1
    assert body["reports"][0]["reason"] == "spam_or_scam"


@pytest.mark.asyncio
async def test_raw_events_payload_included_as_data_not_html(
    admin_app, make_db_ctx, mock_db, make_event
):
    event = make_event(event_id=42, status="draft")
    event.dedup_group_id = None
    _fill_event_detail_fields(event)

    raw = MagicMock()
    raw.id = 1
    raw.external_id = "ext-1"
    raw.payload = {"title": "<script>alert(1)</script>"}
    raw.fetched_at = datetime(2026, 5, 12, 6, 0, 0, tzinfo=timezone.utc)
    raw.processed_at = None

    db = mock_db
    db.scalar = AsyncMock(side_effect=[event, None])
    db.scalars = AsyncMock(side_effect=[scalars_returning([])])
    db.execute = AsyncMock(return_value=execute_rows([(raw, "fienta")]))

    resp = await _get(db, admin_app, make_db_ctx)

    assert resp.status_code == http.HTTPStatus.OK
    body = resp.json()
    assert body["raw_events"] == [
        {
            "id": 1,
            "source_slug": "fienta",
            "external_id": "ext-1",
            "payload": {"title": "<script>alert(1)</script>"},
            "fetched_at": raw.fetched_at.isoformat(),
            "processed_at": None,
        }
    ]


@pytest.mark.asyncio
async def test_in_todays_feed_true(admin_app, make_db_ctx, mock_db):
    event = MagicMock()
    event.id = 42
    event.dedup_group_id = None
    event.slug = "s"
    event.title_orig = "t"
    event.description_orig = None
    event.important_info = None
    event.price_hint = None
    event.starts_at = datetime(2026, 5, 15, 18, 0, 0, tzinfo=timezone.utc)
    event.ends_at = None
    event.venue_name = None
    event.venue_address = None
    event.lat = None
    event.lng = None
    event.url = None
    event.image_url = None
    event.price_min = None
    event.price_max = None
    event.currency = None
    event.status = "published"
    event.is_explicit = False
    event.is_out_of_area = False
    event.is_non_event = False
    event.has_free_tier = False
    event.submitted_by_organizer_id = None
    event.needs_review = False
    event.cancellation_reason = None
    event.created_at = datetime(2026, 5, 13, 6, 0, 0, tzinfo=timezone.utc)
    event.updated_at = datetime(2026, 5, 13, 6, 0, 0, tzinfo=timezone.utc)
    event.detail_refetched_at = None
    event.geocode_attempted_at = None
    event.classification = None

    db = mock_db
    db.scalar = AsyncMock(side_effect=[event, 42])  # feed row's id, truthy
    db.scalars = AsyncMock(side_effect=[scalars_returning([])])
    db.execute = AsyncMock(return_value=execute_rows([]))

    resp = await _get(db, admin_app, make_db_ctx)

    assert resp.status_code == http.HTTPStatus.OK
    assert resp.json()["in_todays_feed"] is True
