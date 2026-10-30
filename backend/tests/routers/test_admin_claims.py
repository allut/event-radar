"""Tests for the admin claims queue (#420): GET /admin/claims,
POST /admin/claims/{id}/grant, /decline, /revoke."""

import http
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.constants.admin import (
    ADMIN_ACTION_DECLINE_CLAIM,
    ADMIN_ACTION_GRANT_CLAIM,
    ADMIN_ACTION_REVOKE_CLAIM,
)
from app._generated.shared_constants import (
    CLAIM_KIND_PUBLISHER,
    CLAIM_KIND_SERIES,
    CLAIM_STATUS_APPROVED,
    CLAIM_STATUS_PENDING,
    CLAIM_STATUS_REVOKED,
    CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW,
    CLAIM_VERIFICATION_MECHANISM_DNS_TXT,
    CLAIM_VERIFICATION_MECHANISM_PILETILEVI_MAILBOX,
)
from app.constants.claims import ERROR_CLAIM_TARGET_ALREADY_APPROVED
from app.constants.core import APP_ENV_DEVELOPMENT
from tests.conftest import build_event
from tests.routers.conftest import (
    execute_rows,
    patch_admin_settings,
    scalars_returning,
)


def _make_claim(
    *,
    claim_id: int = 1,
    kind: str = CLAIM_KIND_PUBLISHER,
    status: str = CLAIM_STATUS_PENDING,
    publisher_id: int | None = 5,
    event_series_key: str | None = None,
    verification_mechanism: str | None = CLAIM_VERIFICATION_MECHANISM_DNS_TXT,
    verification_domain: str | None = "example.ee",
    verification_contact: str | None = None,
    justification: str | None = None,
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
    claim.verification_contact = verification_contact
    claim.justification = justification
    claim.proof_token = proof_token
    claim.resolved_at = None
    claim.created_at = datetime(2026, 5, 1, tzinfo=timezone.utc)
    claim.organizer_id = 9
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
    return build_event(
        event_id=event_id,
        pinned_fields=pinned_fields if pinned_fields is not None else [],
    )


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
        patch_admin_settings() as mock_settings,
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
async def test_list_claims_returns_total_past_the_first_page(admin_app, make_db_ctx, mock_db):
    """Spec #551: the numbered pager needs an exact total on every request,
    not only at offset 0, on both tabs."""
    db = mock_db
    db.scalar = AsyncMock(return_value=120)
    db.scalars = AsyncMock(return_value=scalars_returning([]))

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        _admin_settings(mock_settings)
        async with AsyncClient(transport=ASGITransport(app=admin_app), base_url="http://test") as client:
            pending = (await client.get("/admin/claims?limit=50&offset=100", auth=("admin", ""))).json()
            granted = (
                await client.get("/admin/claims?status=approved&limit=50&offset=100", auth=("admin", ""))
            ).json()

    assert (pending["total"], pending["limit"], pending["offset"]) == (120, 50, 100)
    assert (granted["total"], granted["limit"], granted["offset"]) == (120, 50, 100)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("", "ORDER BY claims.created_at DESC, claims.id DESC"),
        ("?status=approved", "ORDER BY claims.resolved_at DESC, claims.id DESC"),
    ],
)
async def test_list_claims_breaks_ties_on_id(admin_app, make_db_ctx, mock_db, query, expected):
    """Rows sharing a sort value must keep one order across pages (spec #551)."""
    db = mock_db
    db.scalar = AsyncMock(return_value=0)
    captured: dict = {}

    def _capture_scalars(stmt):
        captured["list_stmt"] = stmt
        return scalars_returning([])

    db.scalars = AsyncMock(side_effect=_capture_scalars)

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        _admin_settings(mock_settings)
        async with AsyncClient(transport=ASGITransport(app=admin_app), base_url="http://test") as client:
            await client.get(f"/admin/claims{query}", auth=("admin", ""))

    sql = str(captured["list_stmt"].compile(compile_kwargs={"literal_binds": True}))
    assert expected in sql


@pytest.mark.asyncio
async def test_claims_list_uses_the_admin_read_bucket(admin_app, make_db_ctx, mock_db):
    """Spec #551 decision: refetch-after-action costs a list GET per action,
    so the claims list runs on the browse rate in the shared admin-read
    bucket, not the 10/minute admin action bucket."""
    from app.constants.rate_limits import RATE_LIMIT_ADMIN, RATE_LIMIT_BROWSE

    admin_burst = int(RATE_LIMIT_ADMIN.split("/")[0])
    browse_burst = int(RATE_LIMIT_BROWSE.split("/")[0])
    db = mock_db
    db.scalar = AsyncMock(return_value=0)
    db.scalars = AsyncMock(return_value=scalars_returning([]))

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        _admin_settings(mock_settings)
        async with AsyncClient(transport=ASGITransport(app=admin_app), base_url="http://test") as client:
            statuses = [
                (await client.get("/admin/claims", auth=("admin", ""))).status_code
                for _ in range(browse_burst + 1)
            ]

    assert statuses[: admin_burst + 1] == [http.HTTPStatus.OK] * (admin_burst + 1)
    assert statuses[:browse_burst] == [http.HTTPStatus.OK] * browse_burst
    assert statuses[browse_burst] == http.HTTPStatus.TOO_MANY_REQUESTS


@pytest.mark.asyncio
async def test_list_claims_rejects_invalid_status(admin_app, make_db_ctx, mock_db):
    app = admin_app
    with (
        patch_admin_settings() as mock_settings,
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
    # `db.scalars()` calls in list order: the claims page itself, then the
    # bulk Event lookup; the bulk EventSource lookup is a DISTINCT ON
    # `db.execute()` returning (publisher_id, event_id) rows.
    db.execute = AsyncMock(return_value=execute_rows([(es.publisher_id, es.event_id)]))
    db.scalars = AsyncMock(
        side_effect=[
            scalars_returning([claim]),
            scalars_returning([event]),
        ]
    )

    with (
        patch_admin_settings() as mock_settings,
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
        justification="I've run this listing for three years.",
    )

    db = mock_db
    db.scalar = AsyncMock(return_value=1)
    db.scalars = AsyncMock(return_value=scalars_returning([claim]))

    with (
        patch_admin_settings() as mock_settings,
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
    assert row["justification"] == "I've run this listing for three years."


@pytest.mark.asyncio
async def test_list_pending_claims_shows_mailbox_mismatch_evidence(
    admin_app, make_db_ctx, mock_db
):
    """(#428) A piletilevi_mailbox claim that fell back to admin review still
    surfaces the claimant's account email alongside the resolved contact
    mailbox it didn't match."""
    app = admin_app
    claim = _make_claim(
        claim_id=3,
        kind=CLAIM_KIND_PUBLISHER,
        publisher_id=7,
        verification_mechanism=CLAIM_VERIFICATION_MECHANISM_PILETILEVI_MAILBOX,
        verification_domain=None,
        verification_contact="promoter@other.com",
    )

    db = mock_db
    db.scalar = AsyncMock(return_value=1)
    db.scalars = AsyncMock(
        side_effect=[
            scalars_returning([claim]),
            scalars_returning([]),
            scalars_returning([]),
        ]
    )

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        _admin_settings(mock_settings)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/admin/claims?status=pending", auth=("admin", ""))

    assert resp.status_code == http.HTTPStatus.OK
    row = resp.json()["claims"][0]
    assert row["verification_mechanism"] == CLAIM_VERIFICATION_MECHANISM_PILETILEVI_MAILBOX
    assert row["verification_contact"] == "promoter@other.com"
    assert row["organizer"]["email"] == "organizer@example.com"


# ---------------------------------------------------------------------------
# POST /admin/claims/{id}/grant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_grant_claim_approves_pending_claim(admin_app, make_db_ctx, mock_db, caplog):
    app = admin_app
    claim = _make_claim(claim_id=1, status=CLAIM_STATUS_PENDING)

    db = mock_db
    db.get = AsyncMock(return_value=claim)
    # No pre-existing approved claim on this target, and no other pending
    # siblings to auto-decline (#431 guard/preemption in admin_grant_claim).
    db.scalar = AsyncMock(return_value=None)

    with (
        patch_admin_settings() as mock_settings,
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
        patch_admin_settings() as mock_settings,
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
        patch_admin_settings() as mock_settings,
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
async def test_grant_claim_sends_granted_email(admin_app, make_db_ctx, mock_db):
    """#421: approving a pending claim notifies the claimant, using the
    admin's typed note and the claim's representative event title."""
    app = admin_app
    claim = _make_claim(claim_id=1, status=CLAIM_STATUS_PENDING)
    organizer = MagicMock(id=9, email="organizer@example.com", locale="en")
    event = _make_event(event_id=42)
    event.title_orig = "Jazz Night"

    db = mock_db
    db.get = AsyncMock(side_effect=[claim, organizer])
    db.scalar = AsyncMock(return_value=None)
    send_mock = AsyncMock()

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
        patch("app.routers.admin.representative_event_for_claim", new=AsyncMock(return_value=event)),
        patch("app.routers.admin.send_claim_granted_email", new=send_mock),
    ):
        _admin_settings(mock_settings)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/admin/claims/1/grant",
                json={"resolution_note": "DNS record confirmed manually."},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.OK
    send_mock.assert_awaited_once_with(
        "organizer@example.com", "Jazz Night", "DNS record confirmed manually.", "en"
    )


@pytest.mark.asyncio
async def test_grant_requires_nonblank_note(admin_app, make_db_ctx, mock_db):
    app = admin_app
    with (
        patch_admin_settings() as mock_settings,
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


@pytest.mark.asyncio
async def test_grant_claim_conflicts_when_target_already_approved(admin_app, make_db_ctx, mock_db):
    """#431: admin_grant_claim must apply the same approved-target guard as
    the organizer-facing auto-grant path. Since migration 0048, multiple
    pending claims can coexist on one target — granting one of them, then
    granting a sibling, must 409 (ERROR_CLAIM_TARGET_ALREADY_APPROVED)
    instead of crashing on the narrowed unique index."""
    app = admin_app
    claim = _make_claim(claim_id=2, status=CLAIM_STATUS_PENDING, publisher_id=5)

    db = mock_db
    db.get = AsyncMock(return_value=claim)
    db.scalar = AsyncMock(return_value=1)  # an approved claim already exists on this target

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
    ):
        _admin_settings(mock_settings)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/admin/claims/2/grant",
                json={"resolution_note": "note"},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.CONFLICT
    assert resp.json()["detail"] == ERROR_CLAIM_TARGET_ALREADY_APPROVED
    assert claim.status == CLAIM_STATUS_PENDING  # never flipped
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_grant_claim_auto_declines_other_pending_claims_on_target(admin_app, make_db_ctx, mock_db):
    """#431: manually granting one pending claim must auto-decline every
    other still-pending claim on the same target and notify each declined
    claimant — otherwise sibling pending claims are stuck forever with no
    automatic path to resolution."""
    app = admin_app
    claim = _make_claim(claim_id=1, status=CLAIM_STATUS_PENDING, publisher_id=5)
    organizer = MagicMock(id=9, email="organizer@example.com", locale="en")

    other_organizer = MagicMock(id=6, email="other@example.com", locale="en")
    loser = _make_claim(claim_id=2, status=CLAIM_STATUS_PENDING, publisher_id=5)
    loser.organizer = other_organizer
    loser_event = _make_event(event_id=43)
    loser_event.title_orig = "Loser's own listing"

    db = mock_db
    db.get = AsyncMock(side_effect=[claim, organizer])
    db.scalar = AsyncMock(return_value=None)  # no existing approved claim on this target
    db.scalars.return_value = MagicMock(all=MagicMock(return_value=[loser]))

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
        patch(
            "app.routers.admin.representative_event_for_claim",
            new=AsyncMock(return_value=_make_event(event_id=42)),
        ),
        patch("app.routers.admin.send_claim_granted_email", new=AsyncMock()),
        patch(
            "app.claims.pinning.representative_event_for_claim",
            new_callable=AsyncMock,
            return_value=loser_event,
        ),
        patch(
            "app.claims.lifecycle.send_claim_declined_email", new_callable=AsyncMock
        ) as decline_mock,
    ):
        _admin_settings(mock_settings)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/admin/claims/1/grant",
                json={"resolution_note": "Verified manually."},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.OK
    assert claim.status == CLAIM_STATUS_APPROVED
    assert loser.status == CLAIM_STATUS_REVOKED
    assert loser.resolved_at is not None
    decline_mock.assert_awaited_once()
    args, kwargs = decline_mock.call_args
    assert args[0] == "other@example.com"
    assert args[1] == "Loser's own listing"


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
        patch_admin_settings() as mock_settings,
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
async def test_decline_claim_sends_declined_email(admin_app, make_db_ctx, mock_db):
    """#421: declining a pending claim notifies the claimant — and must not
    also fire the granted email."""
    app = admin_app
    claim = _make_claim(claim_id=1, status=CLAIM_STATUS_PENDING)
    organizer = MagicMock(id=9, email="organizer@example.com", locale="et")
    event = _make_event(event_id=42)
    event.title_orig = "Jazz Night"

    db = mock_db
    db.get = AsyncMock(side_effect=[claim, organizer])
    declined_mock = AsyncMock()
    granted_mock = AsyncMock()

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
        patch("app.routers.admin.representative_event_for_claim", new=AsyncMock(return_value=event)),
        patch("app.routers.admin.send_claim_declined_email", new=declined_mock),
        patch("app.routers.admin.send_claim_granted_email", new=granted_mock),
    ):
        _admin_settings(mock_settings)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/admin/claims/1/decline",
                json={"resolution_note": "Domain didn't match the Fienta listing."},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.OK
    declined_mock.assert_awaited_once_with(
        "organizer@example.com", "Jazz Night", "Domain didn't match the Fienta listing.", "et"
    )
    granted_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_decline_already_resolved_claim_conflicts(admin_app, make_db_ctx, mock_db):
    app = admin_app
    claim = _make_claim(claim_id=1, status=CLAIM_STATUS_REVOKED)

    db = mock_db
    db.get = AsyncMock(return_value=claim)

    with (
        patch_admin_settings() as mock_settings,
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
    """clear_claim_pins() (#442) — not just the representative event's own
    pinned_fields attribute — is the thing that must run on revoke; its
    own bulk-coverage behavior is covered by tests/claims/test_pinning.py."""
    app = admin_app
    claim = _make_claim(claim_id=1, status=CLAIM_STATUS_APPROVED, kind=CLAIM_KIND_PUBLISHER)
    event = _make_event(event_id=42, pinned_fields=["title", "price_min"])
    clear_pins_mock = AsyncMock(return_value=[42, 43])

    db = mock_db
    db.get = AsyncMock(return_value=claim)
    db.delete = AsyncMock()

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
        patch("app.routers.admin.representative_event_for_claim", new=AsyncMock(return_value=event)),
        patch("app.routers.admin.clear_claim_pins", new=clear_pins_mock),
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
    clear_pins_mock.assert_awaited_once_with(db, claim)
    db.delete.assert_awaited_once_with(claim)
    assert resp.json() == {
        "id": 1,
        "event_id": 42,
        "note": "Escalated from a content report.",
        "organizer_id": 9,
        "kind": CLAIM_KIND_PUBLISHER,
    }

    admin_action_records = [r for r in caplog.records if getattr(r, "event", None) == "admin_action"]
    assert admin_action_records[0].action == ADMIN_ACTION_REVOKE_CLAIM
    assert admin_action_records[0].target == 1


@pytest.mark.asyncio
async def test_revoke_claim_sends_no_resolution_email(admin_app, make_db_ctx, mock_db):
    """#421 acceptance criteria: revoke is a distinct action from decline —
    it never fires the decline (or any other claim-resolution) email."""
    app = admin_app
    claim = _make_claim(claim_id=1, status=CLAIM_STATUS_APPROVED, kind=CLAIM_KIND_PUBLISHER)
    event = _make_event(event_id=42, pinned_fields=["title"])

    db = mock_db
    db.get = AsyncMock(return_value=claim)
    db.delete = AsyncMock()
    declined_mock = AsyncMock()
    granted_mock = AsyncMock()

    with (
        patch_admin_settings() as mock_settings,
        patch("app.routers.admin.AsyncSessionLocal", return_value=make_db_ctx(db)),
        patch("app.routers.admin.representative_event_for_claim", new=AsyncMock(return_value=event)),
        patch("app.routers.admin.send_claim_declined_email", new=declined_mock),
        patch("app.routers.admin.send_claim_granted_email", new=granted_mock),
    ):
        _admin_settings(mock_settings)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/admin/claims/1/revoke",
                json={"resolution_note": "Escalated from a content report."},
                auth=("admin", ""),
            )

    assert resp.status_code == http.HTTPStatus.OK
    declined_mock.assert_not_awaited()
    granted_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_revoke_pending_claim_conflicts(admin_app, make_db_ctx, mock_db):
    app = admin_app
    claim = _make_claim(claim_id=1, status=CLAIM_STATUS_PENDING)

    db = mock_db
    db.get = AsyncMock(return_value=claim)

    with (
        patch_admin_settings() as mock_settings,
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
        patch_admin_settings() as mock_settings,
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
