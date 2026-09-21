"""Tests for the admin claims queue (#420): GET /admin/claims,
POST /admin/claims/{id}/grant, /decline, /revoke."""

import http
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.constants import (
    ADMIN_ACTION_DECLINE_CLAIM,
    ADMIN_ACTION_GRANT_CLAIM,
    ADMIN_ACTION_REVOKE_CLAIM,
    APP_ENV_DEVELOPMENT,
    CLAIM_KIND_PUBLISHER,
    CLAIM_KIND_SERIES,
    CLAIM_STATUS_APPROVED,
    CLAIM_STATUS_PENDING,
    CLAIM_STATUS_REVOKED,
    CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW,
    CLAIM_VERIFICATION_MECHANISM_DNS_TXT,
)
from tests.routers.conftest import scalars_returning


def _make_claim(
    *,
    claim_id: int = 1,
    kind: str = CLAIM_KIND_PUBLISHER,
    status: str = CLAIM_STATUS_PENDING,
    publisher_id: int | None = 5,
    event_series_key: str | None = None,
    verification_mechanism: str | None = CLAIM_VERIFICATION_MECHANISM_DNS_TXT,
    verification_domain: str | None = "example.ee",
    proof_token: str = "er-verify-abc123",
    pinned_fields: list[str] | None = None,
) -> MagicMock:
    claim = MagicMock()
    claim.id = claim_id
    claim.kind = kind
    claim.status = status
    claim.publisher_id = publisher_id
    claim.event_series_key = event_series_key
    claim.verification_mechanism = verification_mechanism
    claim.verification_domain = verification_domain
    claim.proof_token = proof_token
    claim.resolved_at = None
    claim.created_at = datetime(2026, 5, 1, tzinfo=timezone.utc)
    organizer = MagicMock()
    organizer.id = 9
    organizer.email = "organizer@example.com"
    organizer.name = "Test Organizer"
    claim.organizer = organizer
    if kind == CLAIM_KIND_PUBLISHER:
        publisher = MagicMock()
        publisher.id = publisher_id
        publisher.name = "Test Publisher"
        claim.publisher = publisher
    else:
        claim.publisher = None
    return claim


def _make_event(*, event_id: int = 42, pinned_fields: list[str] | None = None) -> MagicMock:
    event = MagicMock()
    event.id = event_id
    event.title_orig = "Test Event"
    event.pinned_fields = pinned_fields if pinned_fields is not None else []
    return event


def _admin_settings(mock_settings):
    mock_settings.ADMIN_PASSWORD = ""
    mock_settings.APP_ENV = APP_ENV_DEVELOPMENT


# ---------------------------------------------------------------------------
# GET /admin/claims
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_claims_defaults_to_pending(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db = mock_db
    db.scalar = AsyncMock(return_value=0)
    db.scalars = AsyncMock(return_value=scalars_returning([]))

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        _admin_settings(mock_settings)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/admin/claims", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    body = resp.json()
    assert body["total"] == 0
    assert body["claims"] == []


@pytest.mark.asyncio
async def test_list_claims_rejects_invalid_status(admin_app, make_db_ctx, mock_db):
    app = admin_app
    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(mock_db)),
    ):
        _admin_settings(mock_settings)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/admin/claims?status=revoked", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
async def test_list_pending_claims_shows_dns_evidence_and_resolves_publisher_event(
    admin_app, make_db_ctx, mock_db
):
    app = admin_app
    claim = _make_claim(
        claim_id=1,
        kind=CLAIM_KIND_PUBLISHER,
        publisher_id=5,
        verification_mechanism=CLAIM_VERIFICATION_MECHANISM_DNS_TXT,
        verification_domain="kesklinnajazz.ee",
    )
    event = _make_event(event_id=42)
    es = MagicMock()
    es.publisher_id = 5
    es.event_id = 42

    db = mock_db
    db.scalar = AsyncMock(return_value=1)
    # Three `db.scalars()` calls in list order: the claims page itself, the
    # bulk EventSource lookup (one row per distinct publisher_id), then the
    # bulk Event lookup — the N+1 fix's two-fixed-query bulk-load pair.
    db.scalars = AsyncMock(
        side_effect=[
            scalars_returning([claim]),
            scalars_returning([es]),
            scalars_returning([event]),
        ]
    )

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        _admin_settings(mock_settings)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/admin/claims?status=pending", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    row = resp.json()["claims"][0]
    assert row["verification_mechanism"] == CLAIM_VERIFICATION_MECHANISM_DNS_TXT
    assert row["dns_record_name"] == "_eventradar-verify.kesklinnajazz.ee"
    assert row["event_id"] == 42
    assert row["organizer"]["email"] == "organizer@example.com"
    assert row["publisher"]["name"] == "Test Publisher"


@pytest.mark.asyncio
async def test_list_pending_claims_series_has_no_publisher_or_event(
    admin_app, make_db_ctx, mock_db
):
    app = admin_app
    claim = _make_claim(
        claim_id=2,
        kind=CLAIM_KIND_SERIES,
        publisher_id=None,
        event_series_key="vinyl-nights\x1fkultuurikatel",
        verification_mechanism=CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW,
        verification_domain=None,
    )

    db = mock_db
    db.scalar = AsyncMock(return_value=1)
    db.scalars = AsyncMock(return_value=scalars_returning([claim]))

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        _admin_settings(mock_settings)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/admin/claims?status=pending", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    row = resp.json()["claims"][0]
    assert row["publisher"] is None
    assert row["event_id"] is None
    assert row["dns_record_name"] is None
    assert row["counts_toward_trust"] is True


# ---------------------------------------------------------------------------
# POST /admin/claims/{id}/grant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grant_claim_approves_pending_claim(admin_app, make_db_ctx, mock_db, caplog):
    app = admin_app
    claim = _make_claim(claim_id=1, status=CLAIM_STATUS_PENDING)

    db = mock_db
    db.get = AsyncMock(return_value=claim)

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
        caplog.at_level("INFO"),
    ):
        _admin_settings(mock_settings)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/admin/claims/1/grant",
                json={"resolution_note": "DNS record confirmed manually."},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.OK
    assert claim.status == CLAIM_STATUS_APPROVED
    assert claim.resolved_at is not None
    assert resp.json() == {"id": 1, "status": CLAIM_STATUS_APPROVED, "note": "DNS record confirmed manually."}

    admin_action_records = [r for r in caplog.records if getattr(r, "event", None) == "admin_action"]
    assert len(admin_action_records) == 1
    assert admin_action_records[0].action == ADMIN_ACTION_GRANT_CLAIM
    assert admin_action_records[0].target == 1


@pytest.mark.asyncio
async def test_grant_already_resolved_claim_conflicts(admin_app, make_db_ctx, mock_db):
    app = admin_app
    claim = _make_claim(claim_id=1, status=CLAIM_STATUS_APPROVED)

    db = mock_db
    db.get = AsyncMock(return_value=claim)

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        _admin_settings(mock_settings)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/admin/claims/1/grant",
                json={"resolution_note": "note"},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.CONFLICT


@pytest.mark.asyncio
async def test_grant_missing_claim_404s(admin_app, make_db_ctx, mock_db):
    app = admin_app
    db = mock_db
    db.get = AsyncMock(return_value=None)

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        _admin_settings(mock_settings)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/admin/claims/999/grant",
                json={"resolution_note": "note"},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_grant_requires_nonblank_note(admin_app, make_db_ctx, mock_db):
    app = admin_app
    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(mock_db)),
    ):
        _admin_settings(mock_settings)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/admin/claims/1/grant",
                json={"resolution_note": "   "},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.UNPROCESSABLE_ENTITY


# ---------------------------------------------------------------------------
# POST /admin/claims/{id}/decline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decline_claim_revokes_status_without_deleting_row(admin_app, make_db_ctx, mock_db, caplog):
    app = admin_app
    claim = _make_claim(claim_id=1, status=CLAIM_STATUS_PENDING)

    db = mock_db
    db.get = AsyncMock(return_value=claim)
    db.delete = AsyncMock()

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
        caplog.at_level("INFO"),
    ):
        _admin_settings(mock_settings)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/admin/claims/1/decline",
                json={"resolution_note": "Domain didn't match the Fienta listing."},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.OK
    assert claim.status == CLAIM_STATUS_REVOKED
    assert claim.resolved_at is not None
    db.delete.assert_not_called()

    admin_action_records = [r for r in caplog.records if getattr(r, "event", None) == "admin_action"]
    assert admin_action_records[0].action == ADMIN_ACTION_DECLINE_CLAIM


@pytest.mark.asyncio
async def test_decline_already_resolved_claim_conflicts(admin_app, make_db_ctx, mock_db):
    app = admin_app
    claim = _make_claim(claim_id=1, status=CLAIM_STATUS_REVOKED)

    db = mock_db
    db.get = AsyncMock(return_value=claim)

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        _admin_settings(mock_settings)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/admin/claims/1/decline",
                json={"resolution_note": "note"},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.CONFLICT


# ---------------------------------------------------------------------------
# POST /admin/claims/{id}/revoke
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoke_claim_deletes_row_and_clears_pins(admin_app, make_db_ctx, mock_db, caplog):
    app = admin_app
    claim = _make_claim(claim_id=1, status=CLAIM_STATUS_APPROVED, kind=CLAIM_KIND_PUBLISHER)
    event = _make_event(event_id=42, pinned_fields=["title", "price_min"])

    db = mock_db
    db.get = AsyncMock(return_value=claim)
    db.delete = AsyncMock()

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
        patch("app.routers.admin.representative_event_for_claim", new=AsyncMock(return_value=event)),
        caplog.at_level("INFO"),
    ):
        _admin_settings(mock_settings)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/admin/claims/1/revoke",
                json={"resolution_note": "Escalated from a content report."},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.OK
    assert event.pinned_fields == []
    db.delete.assert_awaited_once_with(claim)
    assert resp.json() == {
        "id": 1,
        "event_id": 42,
        "note": "Escalated from a content report.",
    }

    admin_action_records = [r for r in caplog.records if getattr(r, "event", None) == "admin_action"]
    assert admin_action_records[0].action == ADMIN_ACTION_REVOKE_CLAIM
    assert admin_action_records[0].target == 1


@pytest.mark.asyncio
async def test_revoke_pending_claim_conflicts(admin_app, make_db_ctx, mock_db):
    app = admin_app
    claim = _make_claim(claim_id=1, status=CLAIM_STATUS_PENDING)

    db = mock_db
    db.get = AsyncMock(return_value=claim)

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        _admin_settings(mock_settings)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/admin/claims/1/revoke",
                json={"resolution_note": "note"},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.CONFLICT


@pytest.mark.asyncio
async def test_revoke_claim_with_no_resolvable_event_still_deletes(admin_app, make_db_ctx, mock_db):
    """A claim whose target event can no longer be resolved (e.g. it was
    cancelled/deleted since granting) must still be revocable — the row
    deletion and trust-strip don't depend on a live event."""
    app = admin_app
    claim = _make_claim(claim_id=1, status=CLAIM_STATUS_APPROVED)

    db = mock_db
    db.get = AsyncMock(return_value=claim)
    db.delete = AsyncMock()

    with (
        patch("app.routers.admin.settings") as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
        patch("app.routers.admin.representative_event_for_claim", new=AsyncMock(return_value=None)),
    ):
        _admin_settings(mock_settings)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/admin/claims/1/revoke",
                json={"resolution_note": "note"},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.OK
    db.delete.assert_awaited_once_with(claim)
    assert resp.json()["event_id"] is None
