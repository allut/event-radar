"""Coverage for GET /admin/dedup/groups (routers/admin_events.py): session-only
auth (HTTP Basic moved off earlier, OWASP audit G-5), paging, rate-limit buckets
and the joined-venue preference."""

import http
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.constants.core import APP_ENV_DEVELOPMENT
from tests.routers.conftest import patch_admin_settings, scalars_returning


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dedup_groups_rejects_basic_auth_alone(admin_app):
    """OWASP audit G-5: unpublished/moderation-sensitive event content
    (title, venue, url, is_explicit for draft/classified/rejected rows) must
    require the TOTP-backed session cookie — correct HTTP Basic credentials
    alone are no longer sufficient, even though they used to be (this route
    was one of the three _require_admin Basic-eligible GETs)."""
    app = admin_app
    with patch_admin_settings() as mock_settings:
        mock_settings.ADMIN_PASSWORD = "s3cret"
        mock_settings.ADMIN_USERNAME = "admin"
        mock_settings.APP_ENV = "production"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/admin/dedup/groups", auth=("admin", "s3cret"))

    assert resp.status_code == http.HTTPStatus.UNAUTHORIZED


@pytest.mark.asyncio
async def test_dedup_groups_empty_page(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db = mock_db
    db.scalar = AsyncMock(return_value=0)
    db.scalars = AsyncMock(return_value=scalars_returning([]))

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin_events.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/admin/dedup/groups", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    body = resp.json()
    assert body["group_count"] == 0
    assert body["groups"] == []
    assert body["has_more"] is False


@pytest.mark.asyncio
async def test_dedup_groups_populated_page(admin_app, make_db_ctx, mock_db):
    from datetime import datetime, timezone

    app = admin_app
    ev = MagicMock()
    ev.id = 11
    ev.dedup_group_id = 5
    ev.title_orig = "Jazz"
    ev.starts_at = datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc)
    ev.venue_name = "Club"
    ev.venue_id = None
    ev.venue = None
    ev.status = "published"
    ev.url = "https://x"
    ev.is_explicit = False

    db = mock_db
    db.scalar = AsyncMock(return_value=1)  # total_groups
    # first scalars() -> page group ids; second -> event rows
    db.scalars = AsyncMock(
        side_effect=[scalars_returning([5]), scalars_returning([ev])]
    )

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin_events.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/admin/dedup/groups", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    body = resp.json()
    assert body["group_count"] == 1
    assert body["event_count"] == 1
    assert body["groups"][0]["dedup_group_id"] == 5
    assert body["groups"][0]["events"][0]["id"] == 11
    assert body["groups"][0]["events"][0]["venue"] == "Club"


def _dedup_event(event_id: int, group_id: int) -> MagicMock:
    from datetime import datetime, timezone

    ev = MagicMock()
    ev.id = event_id
    ev.dedup_group_id = group_id
    ev.title_orig = f"Event {event_id}"
    ev.starts_at = datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc)
    ev.venue_name = "Club"
    ev.venue_id = None
    ev.venue = None
    ev.status = "published"
    ev.url = None
    ev.is_explicit = False
    return ev


@pytest.mark.asyncio
async def test_dedup_groups_walks_pages_with_total_on_every_request(
    admin_app, make_db_ctx, mock_db
):
    """#552: total/limit/offset come back on every page, not only at offset 0,
    and the old total_groups key is gone. Walks page 1 and page 2 of a
    three-group queue at limit=2."""
    app = admin_app
    db = mock_db
    db.scalar = AsyncMock(return_value=3)
    db.scalars = AsyncMock(
        side_effect=[
            # page 1: limit+1 sentinel row (7) signals has_more
            scalars_returning([5, 6, 7]),
            scalars_returning([_dedup_event(11, 5), _dedup_event(12, 6)]),
            # page 2: only the last group remains
            scalars_returning([7]),
            scalars_returning([_dedup_event(13, 7)]),
        ]
    )

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin_events.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            first = (await client.get("/admin/dedup/groups?limit=2&offset=0")).json()
            second = (await client.get("/admin/dedup/groups?limit=2&offset=2")).json()

    assert "total_groups" not in first
    assert "total_groups" not in second
    assert (first["total"], first["limit"], first["offset"]) == (3, 2, 0)
    assert (second["total"], second["limit"], second["offset"]) == (3, 2, 2)
    assert [g["dedup_group_id"] for g in first["groups"]] == [5, 6]
    assert [g["dedup_group_id"] for g in second["groups"]] == [7]
    assert first["has_more"] is True
    assert second["has_more"] is False


@pytest.mark.asyncio
async def test_dedup_groups_past_end_page_still_reports_total(
    admin_app, make_db_ctx, mock_db
):
    """#552: a past-end offset returns an empty page that still carries the
    exact total, so the client can clamp to the real last page."""
    app = admin_app
    db = mock_db
    db.scalar = AsyncMock(return_value=3)
    db.scalars = AsyncMock(return_value=scalars_returning([]))

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin_events.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            body = (await client.get("/admin/dedup/groups?limit=2&offset=50")).json()

    assert body["groups"] == []
    assert (body["total"], body["limit"], body["offset"]) == (3, 2, 50)
    assert "total_groups" not in body


@pytest.mark.asyncio
async def test_dedup_groups_list_uses_browse_rate_not_admin_bucket(
    admin_app, make_db_ctx, mock_db
):
    """Spec #551 decision: the Dedup list GET moves off the 10/minute admin
    action bucket onto the browse rate, so quick pager clicks don't 429.
    A full RATE_LIMIT_ADMIN burst plus one must all succeed, while a full
    RATE_LIMIT_BROWSE burst plus one is cut off."""
    from app.constants.rate_limits import RATE_LIMIT_ADMIN, RATE_LIMIT_BROWSE

    admin_burst = int(RATE_LIMIT_ADMIN.split("/")[0])
    browse_burst = int(RATE_LIMIT_BROWSE.split("/")[0])
    app = admin_app
    db = mock_db
    db.scalar = AsyncMock(return_value=0)
    db.scalars = AsyncMock(return_value=scalars_returning([]))

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin_events.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            statuses = [
                (await client.get("/admin/dedup/groups")).status_code
                for _ in range(browse_burst + 1)
            ]

    assert statuses[: admin_burst + 1] == [http.HTTPStatus.OK] * (admin_burst + 1)
    assert statuses[:browse_burst] == [http.HTTPStatus.OK] * browse_burst
    assert statuses[browse_burst] == http.HTTPStatus.TOO_MANY_REQUESTS


@pytest.mark.asyncio
async def test_dedup_groups_list_does_not_spend_the_admin_action_bucket(
    admin_app, make_db_ctx, mock_db
):
    """Browsing Dedup pages must leave the shared admin action bucket intact:
    after a burst of list GETs, an admin write still goes through."""
    from app.constants.rate_limits import RATE_LIMIT_ADMIN

    admin_burst = int(RATE_LIMIT_ADMIN.split("/")[0])
    app = admin_app
    db = mock_db
    db.scalar = AsyncMock(return_value=0)
    db.scalars = AsyncMock(return_value=scalars_returning([]))

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin_events.AsyncSessionLocal", return_value=make_db_ctx(db)),
        patch(
            "app.routers.admin_jobs.publish_pending_job",
            new_callable=AsyncMock,
            return_value={"published": 0},
        ),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for _ in range(admin_burst + 1):
                await client.get("/admin/dedup/groups")
            write = await client.post("/admin/publish")

    assert write.status_code != http.HTTPStatus.TOO_MANY_REQUESTS


@pytest.mark.asyncio
async def test_dedup_groups_prefers_joined_venue_when_linked(
    admin_app, make_db_ctx, mock_db, make_venue
):
    """#177: the dedup-groups listing must prefer the joined Venue over
    Event's own (write-time-NULL) venue_name once venue_id is set."""
    from datetime import datetime, timezone

    app = admin_app
    venue = make_venue(name="Telliskivi Creative City", name_en="Telliskivi Loomelinnak")
    ev = MagicMock()
    ev.id = 11
    ev.dedup_group_id = 5
    ev.title_orig = "Jazz"
    ev.starts_at = datetime(2026, 7, 21, 20, 0, tzinfo=timezone.utc)
    ev.venue_name = None
    ev.venue_id = 1
    ev.venue = venue
    ev.status = "published"
    ev.url = "https://x"
    ev.is_explicit = False

    db = mock_db
    db.scalar = AsyncMock(return_value=1)
    db.scalars = AsyncMock(
        side_effect=[scalars_returning([5]), scalars_returning([ev])]
    )

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin_events.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/admin/dedup/groups", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    body = resp.json()
    # admin console has no locale/i18n loop — the resolver's DEFAULT_USER_LOCALE
    # ("en") applies, so name_en wins over the base name.
    assert body["groups"][0]["events"][0]["venue"] == "Telliskivi Loomelinnak"
