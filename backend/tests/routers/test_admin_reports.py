"""Tests for the admin content-moderation report queue (issue #125):
GET /admin/reports, POST /admin/reports/{id}/resolve,
POST /admin/reports/{id}/takedown."""

import http
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.constants.admin import (
    ADMIN_ACTION_RESOLVE_REPORTS,
    ADMIN_ACTION_TAKEDOWN_REPORTED_EVENT,
)
from app.constants.core import APP_ENV_DEVELOPMENT
from app.constants.events import (
    EVENT_CANCELLATION_REASON_REPORT_TAKEDOWN,
    EVENT_STATUS_CANCELLED,
)
from tests.routers.conftest import execute_rows, patch_admin_settings, scalars_returning


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
        patch_admin_settings() as mock_settings,
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
        patch_admin_settings() as mock_settings,
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
        patch_admin_settings() as mock_settings,
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
        patch_admin_settings() as mock_settings,
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
        patch_admin_settings() as mock_settings,
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


async def _get_reports(admin_app, db, make_db_ctx, url: str):
    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT
        async with AsyncClient(
            transport=ASGITransport(app=admin_app), base_url="http://test"
        ) as client:
            return await client.get(url, auth=("admin", ""))


@pytest.mark.asyncio
async def test_list_reports_returns_total_past_the_first_page(
    admin_app, make_db_ctx, mock_db
):
    """Spec #551: exact total on every request, not only at offset 0."""
    db = mock_db
    db.scalar = AsyncMock(return_value=120)
    db.execute = AsyncMock(return_value=execute_rows([]))

    resp = await _get_reports(
        admin_app, db, make_db_ctx, "/admin/reports?limit=50&offset=100"
    )

    body = resp.json()
    assert (body["total"], body["limit"], body["offset"]) == (120, 50, 100)
    assert body["report_not_found"] is False


@pytest.mark.asyncio
async def test_list_reports_breaks_ties_on_event_id(admin_app, make_db_ctx, mock_db):
    """has_illegal desc, report_count desc, oldest asc, then event_id: events
    tying on the first three keys keep one order across pages."""
    db = mock_db
    db.scalar = AsyncMock(return_value=0)
    captured: dict = {}

    async def _capture_execute(stmt):
        captured["stmt"] = stmt
        return execute_rows([])

    db.execute = AsyncMock(side_effect=_capture_execute)

    await _get_reports(admin_app, db, make_db_ctx, "/admin/reports")

    sql = str(captured["stmt"].compile(compile_kwargs={"literal_binds": True}))
    order = sql[sql.index("ORDER BY") :]
    keys = [
        "has_illegal_allegation DESC",
        "report_count DESC",
        "oldest_open_report_at ASC",
        "event_reports.event_id ASC",
    ]
    assert [order.index(k) for k in keys] == sorted(order.index(k) for k in keys)


@pytest.mark.asyncio
async def test_list_reports_locates_a_late_page_row(
    admin_app, make_db_ctx, mock_db, make_event, make_report
):
    """report=<id> ignores offset: row 123 (1-based) at limit 50 lives on the
    page starting at offset 100, and the response carries that real offset."""
    event = make_event(event_id=42, status="published")
    event.submitted_by_organizer_id = None
    agg_row = MagicMock(
        event_id=42,
        has_illegal_allegation=False,
        report_count=1,
        oldest_open_report_at="2026-05-13T06:00:00+00:00",
    )
    captured: dict = {}

    async def _capture_execute(stmt):
        captured["stmt"] = stmt
        return execute_rows([agg_row])

    db = mock_db
    db.scalar = AsyncMock(side_effect=[130, 123])  # total, then the row position
    db.execute = AsyncMock(side_effect=_capture_execute)
    db.scalars = AsyncMock(
        side_effect=[
            scalars_returning([event]),
            scalars_returning([make_report(report_id=1, event_id=42)]),
        ]
    )

    resp = await _get_reports(
        admin_app, db, make_db_ctx, "/admin/reports?limit=50&offset=0&report=42"
    )

    body = resp.json()
    assert body["offset"] == 100
    assert body["total"] == 130
    assert body["report_not_found"] is False
    assert [r["event_id"] for r in body["events"]] == [42]
    assert "OFFSET 100" in str(
        captured["stmt"].compile(compile_kwargs={"literal_binds": True})
    )


@pytest.mark.asyncio
async def test_list_reports_locate_on_page_one_keeps_offset_zero(
    admin_app, make_db_ctx, mock_db
):
    db = mock_db
    db.scalar = AsyncMock(side_effect=[10, 3])
    db.execute = AsyncMock(return_value=execute_rows([]))

    resp = await _get_reports(admin_app, db, make_db_ctx, "/admin/reports?report=7")

    assert resp.json()["offset"] == 0
    assert resp.json()["report_not_found"] is False


@pytest.mark.asyncio
async def test_list_reports_already_resolved_report_returns_page_one(
    admin_app, make_db_ctx, mock_db
):
    """A report no longer in the queue: page 1 plus report_not_found, never
    an unrelated row silently selected by the server."""
    db = mock_db
    db.scalar = AsyncMock(side_effect=[130, None])
    db.execute = AsyncMock(return_value=execute_rows([]))

    resp = await _get_reports(
        admin_app, db, make_db_ctx, "/admin/reports?limit=50&offset=100&report=999"
    )

    body = resp.json()
    assert body["report_not_found"] is True
    assert body["offset"] == 0
    assert body["total"] == 130


@pytest.mark.asyncio
async def test_reports_list_uses_the_admin_read_bucket(admin_app, make_db_ctx, mock_db):
    """Refetch-after-action costs a list GET per action: it runs on the
    browse rate in the shared admin-read bucket, not the 10/minute one."""
    from app.constants.rate_limits import RATE_LIMIT_ADMIN, RATE_LIMIT_BROWSE

    admin_burst = int(RATE_LIMIT_ADMIN.split("/")[0])
    browse_burst = int(RATE_LIMIT_BROWSE.split("/")[0])
    db = mock_db
    db.scalar = AsyncMock(return_value=0)
    db.execute = AsyncMock(return_value=execute_rows([]))

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT
        async with AsyncClient(
            transport=ASGITransport(app=admin_app), base_url="http://test"
        ) as client:
            statuses = [
                (await client.get("/admin/reports", auth=("admin", ""))).status_code
                for _ in range(browse_burst + 1)
            ]

    assert statuses[: admin_burst + 1] == [http.HTTPStatus.OK] * (admin_burst + 1)
    assert statuses[browse_burst] == http.HTTPStatus.TOO_MANY_REQUESTS


@pytest.mark.asyncio
async def test_list_reports_walks_tied_events_and_locates_against_postgres(admin_app):
    """Against a real Postgres (skipped without one): seven events tie on
    every aggregate key. Walking the queue three per page returns each event
    exactly once in event-id order, and report=<id> lands on the page holding
    it with that page's real offset. Seeded in a rolled-back transaction."""
    import asyncio
    import os

    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError, SQLAlchemyError
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.pool import NullPool

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        pytest.skip("DATABASE_URL not set")
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        conn = await asyncio.wait_for(engine.connect(), timeout=3)
    except (OSError, asyncio.TimeoutError, SQLAlchemyError):
        await engine.dispose()
        pytest.skip("Postgres unreachable")
    tx = await conn.begin()
    session = AsyncSession(
        bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    try:
        try:
            event_ids: list[int] = []
            for n in range(7):
                event_id = (
                    await session.execute(
                        text(
                            "INSERT INTO events (slug, title_orig, starts_at, status) "
                            "VALUES (:slug, 'Tie', now(), 'published') RETURNING id"
                        ),
                        {"slug": f"report-tie-{n}"},
                    )
                ).scalar_one()
                event_ids.append(event_id)
                user_id = (
                    await session.execute(
                        text("INSERT INTO users (email) VALUES (:email) RETURNING id"),
                        {"email": f"report-tie-{n}@example.test"},
                    )
                ).scalar_one()
                await session.execute(
                    text(
                        "INSERT INTO event_reports (user_id, event_id, reason, "
                        "is_illegal_allegation, status, created_at) VALUES "
                        "(:u, :e, 'spam_or_scam', false, 'open', "
                        "'2999-01-01T00:00:00+00')"
                    ),
                    {"u": user_id, "e": event_id},
                )
        except DBAPIError as exc:
            pytest.skip(f"schema not insertable with minimal columns: {exc}")

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=session)
        ctx.__aexit__ = AsyncMock(return_value=False)
        walked: list[int] = []
        with (
            patch_admin_settings() as mock_settings,
            patch("app.routers.admin.AsyncSessionLocal", return_value=ctx),
        ):
            mock_settings.ADMIN_PASSWORD = ""
            mock_settings.APP_ENV = APP_ENV_DEVELOPMENT
            async with AsyncClient(
                transport=ASGITransport(app=admin_app), base_url="http://test"
            ) as client:
                total = (
                    await client.get("/admin/reports?limit=1", auth=("admin", ""))
                ).json()["total"]
                for offset in range(0, total, 3):
                    body = (
                        await client.get(
                            f"/admin/reports?limit=3&offset={offset}",
                            auth=("admin", ""),
                        )
                    ).json()
                    walked += [row["event_id"] for row in body["events"]]
                located = (
                    await client.get(
                        f"/admin/reports?limit=3&report={event_ids[-1]}",
                        auth=("admin", ""),
                    )
                ).json()
    finally:
        await session.close()
        await tx.rollback()
        await conn.close()
        await engine.dispose()

    assert len(walked) == len(set(walked)) == total
    assert [i for i in walked if i in event_ids] == sorted(event_ids)
    assert event_ids[-1] in [row["event_id"] for row in located["events"]]
    assert located["offset"] == walked.index(event_ids[-1]) // 3 * 3


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
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
        patch(
            "app.events.cancellation.send_report_outcome_email", new=AsyncMock()
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
        http_client=ANY,
    )


@pytest.mark.asyncio
async def test_resolve_reports_requires_nonblank_note(admin_app, make_db_ctx, mock_db, make_event):
    app = admin_app
    event = make_event(event_id=42, status="published")

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
        patch_admin_settings() as mock_settings,
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
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
        patch("app.events.cancellation.send_report_outcome_email", new=AsyncMock()),
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
