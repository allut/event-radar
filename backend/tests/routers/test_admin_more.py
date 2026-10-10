"""Coverage for admin endpoints/branches not exercised by test_admin.py:
session-only auth on /stats, /ingest, /ingest/{slug}, /dedup, /dedup/groups,
/classify, /refetch, /stats.

Every /admin/* route — /stats and /counts included (OWASP audit #4) — requires
the TOTP-backed session cookie; HTTP Basic is not accepted anywhere. GET
/admin/dedup/groups moved off Basic earlier (OWASP audit G-5) — see
test_dedup_groups_rejects_basic_auth_alone below."""

import http
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.constants import APP_ENV_DEVELOPMENT
from tests.routers.conftest import ndjson_lines, patch_admin_settings, scalars_returning


# ---------------------------------------------------------------------------
# session-only auth on /stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stats_rejects_correct_basic_credentials_alone(admin_app):
    """OWASP audit #4: password-only access to /admin/stats is gone — correct
    Basic credentials no longer reach TOTP-less read access (and so no longer
    act as a password-guess oracle)."""
    app = admin_app
    with patch_admin_settings() as mock_settings:
        mock_settings.ADMIN_PASSWORD = "s3cret"
        mock_settings.ADMIN_USERNAME = "realadmin"
        mock_settings.APP_ENV = "production"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/admin/stats", auth=("realadmin", "s3cret"))

    assert resp.status_code == http.HTTPStatus.UNAUTHORIZED


@pytest.mark.asyncio
async def test_counts_rejects_correct_basic_credentials_alone(admin_app):
    app = admin_app
    with patch_admin_settings() as mock_settings:
        mock_settings.ADMIN_PASSWORD = "s3cret"
        mock_settings.ADMIN_USERNAME = "realadmin"
        mock_settings.APP_ENV = "production"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/admin/counts", auth=("realadmin", "s3cret"))

    assert resp.status_code == http.HTTPStatus.UNAUTHORIZED


@pytest.mark.asyncio
async def test_wrong_credentials_returns_401(admin_app):
    app = admin_app
    with patch_admin_settings() as mock_settings:
        mock_settings.ADMIN_PASSWORD = "s3cret"
        mock_settings.ADMIN_USERNAME = "realadmin"
        mock_settings.APP_ENV = "production"

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/admin/stats", auth=("realadmin", "wrong"))

    assert resp.status_code == http.HTTPStatus.UNAUTHORIZED


# ---------------------------------------------------------------------------
# POST /admin/ingest  &  POST /admin/ingest/{slug}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_all_returns_results(admin_app):
    app = admin_app
    with (
        patch_admin_settings() as mock_settings,
        patch(
            "app.routers.admin.ingest_all_enabled",
            new_callable=AsyncMock,
            return_value=[{"slug": "fienta", "raw_count": 5}],
        ),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/admin/ingest", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    assert resp.headers["cache-control"] == "no-store"
    lines = ndjson_lines(resp)
    assert len(lines) == 1
    assert lines[0]["status"] == "ok"
    assert lines[0]["result"]["results"] == [{"slug": "fienta", "raw_count": 5}]


@pytest.mark.asyncio
async def test_ingest_source_unknown_slug_404(admin_app):
    app = admin_app
    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.ADAPTER_REGISTRY", {}),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/admin/ingest/nope", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_ingest_source_value_error_400(admin_app):
    app = admin_app
    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.ADAPTER_REGISTRY", {"fienta": MagicMock()}),
        patch(
            "app.routers.admin.ingest_source",
            new_callable=AsyncMock,
            side_effect=ValueError("disabled"),
        ),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/admin/ingest/fienta", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    lines = ndjson_lines(resp)
    assert lines[0]["status"] == "error"
    assert lines[0]["error"] == "disabled"


@pytest.mark.asyncio
async def test_ingest_source_success(admin_app):
    app = admin_app
    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.ADAPTER_REGISTRY", {"fienta": MagicMock()}),
        patch(
            "app.routers.admin.ingest_source",
            new_callable=AsyncMock,
            return_value={"slug": "fienta", "raw_count": 3, "new_count": 1},
        ),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/admin/ingest/fienta", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    lines = ndjson_lines(resp)
    assert lines[0]["result"]["new_count"] == 1


# ---------------------------------------------------------------------------
# POST /admin/dedup, /admin/classify, /admin/refetch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,target",
    [
        ("/admin/dedup", "app.routers.admin.dedup_pass_drain_now"),
        ("/admin/classify", "app.routers.admin.classify_pending_drain_now"),
        ("/admin/refetch", "app.routers.admin.refetch_event_details_job"),
    ],
)
async def test_simple_job_triggers(path, target, admin_app):
    app = admin_app
    with (
        patch_admin_settings() as mock_settings,
        patch(target, new_callable=AsyncMock, return_value={"done": 1}) as mock_job,
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(path, auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    assert resp.headers["cache-control"] == "no-store"
    lines = ndjson_lines(resp)
    assert len(lines) == 1
    assert lines[0]["status"] == "ok"
    assert lines[0]["result"] == {"done": 1}
    mock_job.assert_awaited_once()


# ---------------------------------------------------------------------------
# GET /admin/dedup/groups
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
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
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
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
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
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
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


# ---------------------------------------------------------------------------
# GET /admin/stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stats_returns_counts(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db = mock_db
    # one execute() for (total, canonical); scalar() for sources_total, sources_enabled
    counts = MagicMock()
    counts.one.return_value = (100, 60)
    db.execute = AsyncMock(return_value=counts)
    db.scalar = AsyncMock(side_effect=[8, 5])

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        mock_settings.ADMIN_PASSWORD = ""
        mock_settings.APP_ENV = APP_ENV_DEVELOPMENT

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/admin/stats", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    body = resp.json()
    assert body["events"] == {"total": 100, "canonical": 60}
    assert body["sources"] == {"total": 8, "enabled": 5}
