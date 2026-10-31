"""Tests for routers/organizer_claims.py (#413) — thin HTTP wiring over
app/claims/lifecycle.py, exercised the same way as test_organizer_venues.py:
calling the endpoint functions directly against a mocked db."""

import http
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.claims.lifecycle import ClaimError
from app._generated.shared_constants import (
    CLAIM_ERROR_CODE_JUSTIFICATION_REQUIRED,
    CLAIM_KIND_PUBLISHER,
    CLAIM_KIND_SERIES,
    CLAIM_STATUS_APPROVED,
    CLAIM_STATUS_PENDING,
    CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN,
    ORGANIZER_OWN_CLAIMS_PAGE_SIZE,
)
from app.constants.auth import DETAIL_MAGIC_LINK_SENT
from app.constants.claims import (
    ERROR_CLAIM_EVENTS_NOT_PUBLISHER,
    ERROR_CLAIM_JUSTIFICATION_REQUIRED,
    ERROR_CLAIM_NOT_FOUND,
    ERROR_CLAIM_OWN_SUBMISSION,
    ERROR_DAILY_CLAIM_LIMIT,
)
from app.constants.events import ERROR_EVENT_NOT_FOUND


def _fake_claim(**overrides) -> MagicMock:
    c = MagicMock()
    c.id = 1
    c.kind = CLAIM_KIND_PUBLISHER
    c.publisher_id = 99
    c.event_series_key = None
    c.status = CLAIM_STATUS_PENDING
    c.dormant = False
    c.verification_mechanism = CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN
    c.verification_domain = None
    c.proof_token = "er-verify-abc"
    c.created_at = "2026-09-20T06:00:00+00:00"
    c.last_checked_at = "2026-09-20T06:00:00+00:00"
    c.resolved_at = None
    for k, v in overrides.items():
        setattr(c, k, v)
    return c


class TestCreateOwnClaim:
    @pytest.mark.asyncio
    async def test_returns_serialized_claim(self, mock_db, make_request, make_organizer):
        from app.routers.organizer_claims import CreateClaimBody, create_own_claim

        organizer = make_organizer(organizer_id=5)
        claim = _fake_claim(status=CLAIM_STATUS_APPROVED)

        response = MagicMock()
        with patch(
            "app.routers.organizer_claims.create_claim",
            new_callable=AsyncMock,
            return_value=(claim, True),
        ):
            result = await create_own_claim(
                CreateClaimBody(event_id=10),
                make_request(method="POST", path="/organizer/claims"),
                response=response,
                current_organizer=organizer,
                db=mock_db,
            )

        assert result["id"] == 1
        assert result["status"] == CLAIM_STATUS_APPROVED

    @pytest.mark.asyncio
    async def test_own_pending_returns_existing_claim_as_200(
        self, mock_db, make_request, make_organizer
    ):
        """(#448) When create_claim reports created=False (the caller already
        had a pending claim on the resolved target), the endpoint overrides
        the 201 default to 200 — nothing new was created."""
        from app.routers.organizer_claims import CreateClaimBody, create_own_claim

        organizer = make_organizer(organizer_id=5)
        claim = _fake_claim(status=CLAIM_STATUS_PENDING)

        response = MagicMock()
        with patch(
            "app.routers.organizer_claims.create_claim",
            new_callable=AsyncMock,
            return_value=(claim, False),
        ):
            result = await create_own_claim(
                CreateClaimBody(event_id=10),
                make_request(method="POST", path="/organizer/claims"),
                response=response,
                current_organizer=organizer,
                db=mock_db,
            )

        assert result["id"] == 1
        assert response.status_code == http.HTTPStatus.OK

    @pytest.mark.asyncio
    async def test_daily_cap_maps_to_429(self, mock_db, make_request, make_organizer):
        from app.routers.organizer_claims import CreateClaimBody, create_own_claim

        organizer = make_organizer(organizer_id=5)

        with patch(
            "app.routers.organizer_claims.create_claim",
            new_callable=AsyncMock,
            side_effect=ClaimError(http.HTTPStatus.TOO_MANY_REQUESTS, ERROR_DAILY_CLAIM_LIMIT),
        ):
            with pytest.raises(HTTPException) as exc:
                await create_own_claim(
                    CreateClaimBody(event_id=10),
                    make_request(method="POST", path="/organizer/claims"),
                    response=MagicMock(),
                    current_organizer=organizer,
                    db=mock_db,
                )

        assert exc.value.status_code == http.HTTPStatus.TOO_MANY_REQUESTS
        assert exc.value.detail == ERROR_DAILY_CLAIM_LIMIT

    @pytest.mark.asyncio
    async def test_not_published_or_canonical_maps_to_404(
        self, mock_db, make_request, make_organizer
    ):
        """Draft, cancelled, or non-canonical-duplicate events are rejected
        the same way a nonexistent event_id is (#429)."""
        from app.routers.organizer_claims import CreateClaimBody, create_own_claim

        organizer = make_organizer(organizer_id=5)

        with patch(
            "app.routers.organizer_claims.create_claim",
            new_callable=AsyncMock,
            side_effect=ClaimError(http.HTTPStatus.NOT_FOUND, ERROR_EVENT_NOT_FOUND),
        ):
            with pytest.raises(HTTPException) as exc:
                await create_own_claim(
                    CreateClaimBody(event_id=10),
                    make_request(method="POST", path="/organizer/claims"),
                    response=MagicMock(),
                    current_organizer=organizer,
                    db=mock_db,
                )

        assert exc.value.status_code == http.HTTPStatus.NOT_FOUND
        assert exc.value.detail == ERROR_EVENT_NOT_FOUND

    @pytest.mark.asyncio
    async def test_own_submission_maps_to_422(self, mock_db, make_request, make_organizer):
        """An organizer's own direct submission is rejected via the explicit
        ERROR_CLAIM_OWN_SUBMISSION guard, not the generic not-claimable
        error (#429)."""
        from app.routers.organizer_claims import CreateClaimBody, create_own_claim

        organizer = make_organizer(organizer_id=5)

        with patch(
            "app.routers.organizer_claims.create_claim",
            new_callable=AsyncMock,
            side_effect=ClaimError(
                http.HTTPStatus.UNPROCESSABLE_ENTITY, ERROR_CLAIM_OWN_SUBMISSION
            ),
        ):
            with pytest.raises(HTTPException) as exc:
                await create_own_claim(
                    CreateClaimBody(event_id=10),
                    make_request(method="POST", path="/organizer/claims"),
                    response=MagicMock(),
                    current_organizer=organizer,
                    db=mock_db,
                )

        assert exc.value.status_code == http.HTTPStatus.UNPROCESSABLE_ENTITY
        assert exc.value.detail == ERROR_CLAIM_OWN_SUBMISSION

    @pytest.mark.asyncio
    async def test_missing_justification_carries_its_code(
        self, mock_db, make_request, make_organizer
    ):
        """The UI reveals the justification field off `code`, not the English message."""
        from app.routers.organizer_claims import CreateClaimBody, create_own_claim

        organizer = make_organizer(organizer_id=5)

        with patch(
            "app.routers.organizer_claims.create_claim",
            new_callable=AsyncMock,
            side_effect=ClaimError(
                http.HTTPStatus.UNPROCESSABLE_ENTITY,
                ERROR_CLAIM_JUSTIFICATION_REQUIRED,
                code=CLAIM_ERROR_CODE_JUSTIFICATION_REQUIRED,
            ),
        ):
            with pytest.raises(HTTPException) as exc:
                await create_own_claim(
                    CreateClaimBody(event_id=10),
                    make_request(method="POST", path="/organizer/claims"),
                    response=MagicMock(),
                    current_organizer=organizer,
                    db=mock_db,
                )

        assert exc.value.status_code == http.HTTPStatus.UNPROCESSABLE_ENTITY
        assert exc.value.detail == {
            "message": ERROR_CLAIM_JUSTIFICATION_REQUIRED,
            "code": CLAIM_ERROR_CODE_JUSTIFICATION_REQUIRED,
        }


class TestCancelOwnClaim:
    @pytest.mark.asyncio
    async def test_returns_cancelled_claim(self, mock_db, make_request, make_organizer):
        from app.routers.organizer_claims import cancel_own_claim

        organizer = make_organizer(organizer_id=5)
        claim = _fake_claim(status="cancelled")

        with patch(
            "app.routers.organizer_claims.cancel_claim", new_callable=AsyncMock, return_value=claim
        ):
            result = await cancel_own_claim(
                1,
                make_request(method="POST", path="/organizer/claims/1/cancel"),
                current_organizer=organizer,
                db=mock_db,
            )

        assert result["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_not_found_maps_to_404(self, mock_db, make_request, make_organizer):
        from app.routers.organizer_claims import cancel_own_claim

        organizer = make_organizer(organizer_id=5)

        with patch(
            "app.routers.organizer_claims.cancel_claim",
            new_callable=AsyncMock,
            side_effect=ClaimError(http.HTTPStatus.NOT_FOUND, ERROR_CLAIM_NOT_FOUND),
        ):
            with pytest.raises(HTTPException) as exc:
                await cancel_own_claim(
                    1,
                    make_request(method="POST", path="/organizer/claims/1/cancel"),
                    current_organizer=organizer,
                    db=mock_db,
                )

        assert exc.value.status_code == http.HTTPStatus.NOT_FOUND


class TestRecheckOwnClaim:
    @pytest.mark.asyncio
    async def test_returns_rechecked_claim(self, mock_db, make_request, make_organizer):
        from app.routers.organizer_claims import recheck_own_claim

        organizer = make_organizer(organizer_id=5)
        claim = _fake_claim(status=CLAIM_STATUS_APPROVED)

        with patch(
            "app.routers.organizer_claims.recheck_claim", new_callable=AsyncMock, return_value=claim
        ):
            result = await recheck_own_claim(
                1,
                make_request(method="POST", path="/organizer/claims/1/recheck"),
                current_organizer=organizer,
                db=mock_db,
            )

        assert result["status"] == CLAIM_STATUS_APPROVED


class TestGetClaimForEvent:
    """(#451) GET /organizer/claims/for-event/{event_id} — the caller's own
    pending/approved claim on the event's target, or null. Backs the public
    page's claimant-only pending pill without ever exposing a rival
    claimant's pending state."""

    @pytest.mark.asyncio
    async def test_404_when_event_not_found(self, mock_db, make_request, make_organizer):
        from app.routers.organizer_claims import get_claim_for_event

        mock_db.scalar = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_claim_for_event(
                999,
                make_request(method="GET", path="/organizer/claims/for-event/999"),
                current_organizer=make_organizer(organizer_id=5),
                db=mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.NOT_FOUND
        assert exc_info.value.detail == ERROR_EVENT_NOT_FOUND

    @pytest.mark.asyncio
    async def test_null_claim_when_no_own_active_claim(self, mock_db, make_request, make_organizer, make_event):
        from app.routers.organizer_claims import get_claim_for_event

        mock_db.scalar = AsyncMock(return_value=make_event())

        with patch(
            "app.routers.organizer_claims.own_claim_for_event",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await get_claim_for_event(
                42,
                make_request(method="GET", path="/organizer/claims/for-event/42"),
                current_organizer=make_organizer(organizer_id=5),
                db=mock_db,
            )

        assert result == {"claim": None}

    @pytest.mark.asyncio
    async def test_returns_serialized_own_claim(self, mock_db, make_request, make_organizer, make_event):
        from app.routers.organizer_claims import get_claim_for_event

        mock_db.scalar = AsyncMock(return_value=make_event())
        claim = _fake_claim(status=CLAIM_STATUS_PENDING)

        with patch(
            "app.routers.organizer_claims.own_claim_for_event",
            new_callable=AsyncMock,
            return_value=claim,
        ):
            result = await get_claim_for_event(
                42,
                make_request(method="GET", path="/organizer/claims/for-event/42"),
                current_organizer=make_organizer(organizer_id=5),
                db=mock_db,
            )

        assert result["claim"]["id"] == claim.id
        assert result["claim"]["status"] == CLAIM_STATUS_PENDING


class TestGetClaim:
    """#415's pending screen fetch — GET /organizer/claims/{claim_id}."""

    @pytest.mark.asyncio
    async def test_assembles_dns_instructions_for_dns_txt_mechanism(
        self, mock_db, make_request, make_organizer
    ):
        from app._generated.shared_constants import CLAIM_VERIFICATION_MECHANISM_DNS_TXT
        from app.routers.organizer_claims import get_claim

        organizer = make_organizer(organizer_id=5)
        claim = _fake_claim(
            verification_mechanism=CLAIM_VERIFICATION_MECHANISM_DNS_TXT,
            verification_domain="kumu.ekm.ee",
        )

        with patch(
            "app.routers.organizer_claims.get_own_claim", new_callable=AsyncMock, return_value=claim
        ):
            result = await get_claim(
                1,
                make_request(method="GET", path="/organizer/claims/1"),
                current_organizer=organizer,
                db=mock_db,
            )

        assert result["dns_record_name"] == "_eventradar-verify.kumu.ekm.ee"
        assert result["dns_record_value"] == "er-verify-abc"
        assert result["can_recheck"] is True

    @pytest.mark.asyncio
    async def test_exposes_dormant_flag(self, mock_db, make_request, make_organizer):
        """#444: the frontend needs `dormant` on the claim itself (not just
        the 409 from the editor) to explain an approved-but-dormant claim on
        ClaimPending."""
        from app.routers.organizer_claims import get_claim

        organizer = make_organizer(organizer_id=5)
        claim = _fake_claim(status=CLAIM_STATUS_APPROVED, dormant=True)

        with patch(
            "app.routers.organizer_claims.get_own_claim", new_callable=AsyncMock, return_value=claim
        ):
            result = await get_claim(
                1,
                make_request(method="GET", path="/organizer/claims/1"),
                current_organizer=organizer,
                db=mock_db,
            )

        assert result["dormant"] is True

    @pytest.mark.asyncio
    async def test_no_dns_instructions_for_admin_review_mechanism(
        self, mock_db, make_request, make_organizer
    ):
        from app._generated.shared_constants import (
            CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW,
        )
        from app.routers.organizer_claims import get_claim

        organizer = make_organizer(organizer_id=5)
        claim = _fake_claim(verification_mechanism=CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW)

        with patch(
            "app.routers.organizer_claims.get_own_claim", new_callable=AsyncMock, return_value=claim
        ):
            result = await get_claim(
                1,
                make_request(method="GET", path="/organizer/claims/1"),
                current_organizer=organizer,
                db=mock_db,
            )

        assert result["dns_record_name"] is None
        assert result["can_recheck"] is False

    @pytest.mark.asyncio
    async def test_404_when_not_the_organizers_own_claim(self, mock_db, make_request, make_organizer):
        from app.routers.organizer_claims import get_claim

        organizer = make_organizer(organizer_id=5)
        mock_db.scalar.return_value = None  # no revoke AdminAction on record either

        with patch(
            "app.routers.organizer_claims.get_own_claim",
            new_callable=AsyncMock,
            side_effect=ClaimError(http.HTTPStatus.NOT_FOUND, ERROR_CLAIM_NOT_FOUND),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_claim(
                    1,
                    make_request(method="GET", path="/organizer/claims/1"),
                    current_organizer=organizer,
                    db=mock_db,
                )

        assert exc_info.value.status_code == http.HTTPStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_reports_declined_not_revoked_for_a_declined_row(
        self, mock_db, make_request, make_organizer
    ):
        """(#447) A still-existing row's stored CLAIM_STATUS_REVOKED always
        means admin_decline_claim/auto_decline_other_pending_claims declined
        a *pending* claim — a real admin revoke of a *granted* claim deletes
        the row outright (see the tombstone test below), so the API
        translates the stored value to CLAIM_STATUS_DECLINED here."""
        from app._generated.shared_constants import (
            CLAIM_STATUS_DECLINED,
            CLAIM_STATUS_REVOKED,
        )
        from app.routers.organizer_claims import get_claim

        organizer = make_organizer(organizer_id=5)
        claim = _fake_claim(status=CLAIM_STATUS_REVOKED)

        with patch(
            "app.routers.organizer_claims.get_own_claim", new_callable=AsyncMock, return_value=claim
        ):
            result = await get_claim(
                1,
                make_request(method="GET", path="/organizer/claims/1"),
                current_organizer=organizer,
                db=mock_db,
            )

        assert result["status"] == CLAIM_STATUS_DECLINED

    @pytest.mark.asyncio
    async def test_revoked_tombstone_when_admin_action_matches_organizer(
        self, mock_db, make_request, make_organizer
    ):
        """#446: the row is gone (admin_revoke_claim deletes it), but the
        AdminAction audit row it left behind lets the pending screen render
        CLAIM_STATUS_REVOKED instead of a bare 404."""
        from app._generated.shared_constants import CLAIM_STATUS_REVOKED
        from app.routers.organizer_claims import get_claim

        organizer = make_organizer(organizer_id=5)
        admin_action = MagicMock()
        admin_action.result = {"organizer_id": 5, "kind": CLAIM_KIND_PUBLISHER, "event_id": 42}
        admin_action.created_at = "2026-09-25T06:00:00+00:00"
        mock_db.scalar.return_value = admin_action

        with patch(
            "app.routers.organizer_claims.get_own_claim",
            new_callable=AsyncMock,
            side_effect=ClaimError(http.HTTPStatus.NOT_FOUND, ERROR_CLAIM_NOT_FOUND),
        ):
            result = await get_claim(
                1,
                make_request(method="GET", path="/organizer/claims/1"),
                current_organizer=organizer,
                db=mock_db,
            )

        assert result["status"] == CLAIM_STATUS_REVOKED
        assert result["kind"] == CLAIM_KIND_PUBLISHER

    @pytest.mark.asyncio
    async def test_no_tombstone_when_admin_action_belongs_to_other_organizer(
        self, mock_db, make_request, make_organizer
    ):
        from app.routers.organizer_claims import get_claim

        organizer = make_organizer(organizer_id=5)
        admin_action = MagicMock()
        admin_action.result = {"organizer_id": 999, "kind": CLAIM_KIND_PUBLISHER}
        mock_db.scalar.return_value = admin_action

        with patch(
            "app.routers.organizer_claims.get_own_claim",
            new_callable=AsyncMock,
            side_effect=ClaimError(http.HTTPStatus.NOT_FOUND, ERROR_CLAIM_NOT_FOUND),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await get_claim(
                    1,
                    make_request(method="GET", path="/organizer/claims/1"),
                    current_organizer=organizer,
                    db=mock_db,
                )

        assert exc_info.value.status_code == http.HTTPStatus.NOT_FOUND


def _mock_own_claims_page(
    mock_db, claims: list, total: int | None = None, pending: int | None = 0
) -> None:
    """One own-claims page: `claims` from the page query, and `(total,
    pending)` from the counts query (`total` defaults to the page's length)."""
    mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=claims))
    counts = MagicMock()
    counts.one.return_value = (len(claims) if total is None else total, pending)
    mock_db.execute.return_value = counts


class TestListOwnClaims:
    """GET /organizer/claims (#446) — the caller's own claims, newest first,
    paged for the Your claims page (spec #551)."""

    @staticmethod
    async def _list_page(mock_db, make_request, organizer, offset, claims, total, pending=0):
        from app.routers.organizer_claims import list_own_claims

        _mock_own_claims_page(mock_db, claims, total, pending)
        with patch(
            "app.routers.organizer_claims.bulk_resolve_publisher_events",
            new_callable=AsyncMock,
            return_value={},
        ), patch(
            "app.routers.organizer_claims.bulk_resolve_series_events",
            new_callable=AsyncMock,
            return_value={},
        ):
            return await list_own_claims(
                make_request(method="GET", path="/organizer/claims"),
                locale=None,
                limit=2,
                offset=offset,
                current_organizer=organizer,
                db=mock_db,
            )

    @pytest.mark.asyncio
    async def test_returns_paging_envelope_on_every_page(
        self, mock_db, make_request, make_organizer
    ):
        """The numbered pager needs total/limit/offset/has_more on every
        request, not only the first page."""
        organizer = make_organizer(organizer_id=5)
        rows = [_fake_claim(id=n, publisher=None) for n in (1, 2)]

        first = await self._list_page(mock_db, make_request, organizer, 0, rows, 5)
        middle = await self._list_page(mock_db, make_request, organizer, 2, rows, 5)
        last = await self._list_page(mock_db, make_request, organizer, 4, rows[:1], 5)

        keys = ("total", "limit", "offset", "has_more")
        assert {k: first[k] for k in keys} == {
            "total": 5, "limit": 2, "offset": 0, "has_more": True,
        }
        assert {k: middle[k] for k in keys} == {
            "total": 5, "limit": 2, "offset": 2, "has_more": True,
        }
        assert {k: last[k] for k in keys} == {
            "total": 5, "limit": 2, "offset": 4, "has_more": False,
        }
        assert [c["id"] for c in first["claims"]] == [1, 2]

    @pytest.mark.asyncio
    async def test_reports_the_pending_count_on_every_page(
        self, mock_db, make_request, make_organizer
    ):
        """The dashboard's "You have N claims (M pending)" summary reads
        `total` and `pending_count` — counted over every claim, not the page."""
        organizer = make_organizer(organizer_id=5)
        rows = [_fake_claim(id=1, status=CLAIM_STATUS_APPROVED, publisher=None)]

        result = await self._list_page(mock_db, make_request, organizer, 2, rows, 37, pending=3)

        assert (result["total"], result["pending_count"]) == (37, 3)
        counts_stmt = mock_db.execute.call_args.args[0]
        sql = str(counts_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "claims.organizer_id = 5" in sql
        assert f"claims.status = '{CLAIM_STATUS_PENDING}'" in sql

    @pytest.mark.asyncio
    async def test_no_claims_has_zero_counts(self, mock_db, make_request, make_organizer):
        organizer = make_organizer(organizer_id=5)
        result = await self._list_page(mock_db, make_request, organizer, 0, [], None, None)
        assert (result["total"], result["pending_count"], result["has_more"], result["claims"]) == (
            0, 0, False, [],
        )

    @pytest.mark.asyncio
    async def test_pages_share_a_created_at_then_id_order(
        self, mock_db, make_request, make_organizer
    ):
        """Tie-breaker stability: two claims made in the same instant never
        swap between pages, so every page orders by created_at desc then id
        desc, and only LIMIT/OFFSET differ between pages."""
        organizer = make_organizer(organizer_id=5)
        sqls = []
        for offset in (0, 2):
            await self._list_page(mock_db, make_request, organizer, offset, [], 3)
            stmt = mock_db.scalars.call_args.args[0]
            sqls.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))

        for sql in sqls:
            assert "ORDER BY claims.created_at DESC, claims.id DESC" in sql
            assert "claims.organizer_id = 5" in sql
        assert "LIMIT 2 OFFSET 0" in sqls[0]
        assert "LIMIT 2 OFFSET 2" in sqls[1]
        assert sqls[0].replace("OFFSET 0", "OFFSET 2") == sqls[1]

    def test_page_size_defaults_to_the_own_claims_constant(self):
        """Your claims pages at 20 (spec #551), replacing the old 200-row cap."""
        from app.routers.organizer_claims import router

        route = next(r for r in router.routes if getattr(r, "name", "") == "list_own_claims")
        params = {p.name: p for p in route.dependant.query_params}
        assert ORGANIZER_OWN_CLAIMS_PAGE_SIZE == 20
        assert params["limit"].field_info.default == ORGANIZER_OWN_CLAIMS_PAGE_SIZE
        assert params["offset"].field_info.default == 0

    @pytest.mark.asyncio
    async def test_bulk_resolves_publisher_event_and_name(
        self, mock_db, make_request, make_organizer
    ):
        from app.routers.organizer_claims import list_own_claims

        organizer = make_organizer(organizer_id=5)
        claim = _fake_claim(status=CLAIM_STATUS_APPROVED)
        claim.publisher = MagicMock(name="Jazzkaar")
        claim.publisher.name = "Jazzkaar"

        _mock_own_claims_page(mock_db, [claim])

        event = MagicMock()
        event.id = 42
        event.title_orig = "Jazzkaar Festival Night"
        event.title_localized = None

        with patch(
            "app.routers.organizer_claims.bulk_resolve_publisher_events",
            new_callable=AsyncMock,
            return_value={99: event},
        ):
            result = await list_own_claims(
                make_request(method="GET", path="/organizer/claims"),
                current_organizer=organizer,
                db=mock_db,
                locale=None,
                limit=ORGANIZER_OWN_CLAIMS_PAGE_SIZE,
                offset=0,
            )

        assert result["claims"] == [
            {
                "id": 1,
                "kind": CLAIM_KIND_PUBLISHER,
                "status": CLAIM_STATUS_APPROVED,
                "verification_mechanism": CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN,
                "dormant": False,
                "publisher_name": "Jazzkaar",
                "event_id": 42,
                "event_title": "Jazzkaar Festival Night",
                "created_at": "2026-09-20T06:00:00+00:00",
                "resolved_at": None,
            }
        ]

    @pytest.mark.asyncio
    async def test_reports_declined_not_revoked_for_a_declined_claim(
        self, mock_db, make_request, make_organizer
    ):
        """(#447) list_own_claims only ever lists rows that still exist — a
        real admin revoke deletes its row — so a stored CLAIM_STATUS_REVOKED
        here is always a decline and must be reported as such."""
        from app._generated.shared_constants import (
            CLAIM_STATUS_DECLINED,
            CLAIM_STATUS_REVOKED,
        )
        from app.routers.organizer_claims import list_own_claims

        organizer = make_organizer(organizer_id=5)
        claim = _fake_claim(status=CLAIM_STATUS_REVOKED)
        claim.publisher = None

        _mock_own_claims_page(mock_db, [claim])

        with patch(
            "app.routers.organizer_claims.bulk_resolve_publisher_events",
            new_callable=AsyncMock,
            return_value={},
        ):
            result = await list_own_claims(
                make_request(method="GET", path="/organizer/claims"),
                current_organizer=organizer,
                db=mock_db,
                locale=None,
                limit=ORGANIZER_OWN_CLAIMS_PAGE_SIZE,
                offset=0,
            )

        assert result["claims"][0]["status"] == CLAIM_STATUS_DECLINED

    @pytest.mark.asyncio
    async def test_series_claim_uses_bulk_series_scan(
        self, mock_db, make_request, make_organizer
    ):
        from app.routers.organizer_claims import list_own_claims

        organizer = make_organizer(organizer_id=5)
        claim = _fake_claim(kind=CLAIM_KIND_SERIES, publisher_id=None, event_series_key="k")
        claim.publisher = None

        _mock_own_claims_page(mock_db, [claim])

        event = MagicMock()
        event.id = 7
        event.title_orig = "Winter Market"
        event.title_localized = None

        with patch(
            "app.routers.organizer_claims.bulk_resolve_publisher_events",
            new_callable=AsyncMock,
            return_value={},
        ), patch(
            "app.routers.organizer_claims.bulk_resolve_series_events",
            new_callable=AsyncMock,
            return_value={"k": event},
        ) as bulk_series:
            result = await list_own_claims(
                make_request(method="GET", path="/organizer/claims"),
                current_organizer=organizer,
                db=mock_db,
                locale=None,
                limit=ORGANIZER_OWN_CLAIMS_PAGE_SIZE,
                offset=0,
            )

        bulk_series.assert_awaited_once_with(mock_db, {"k"})
        assert result["claims"][0]["event_id"] == 7
        assert result["claims"][0]["event_title"] == "Winter Market"
        assert result["claims"][0]["publisher_name"] is None

    @pytest.mark.asyncio
    async def test_locale_query_param_wins_over_stored_organizer_locale(
        self, mock_db, make_request, make_organizer
    ):
        """(#454) A ?locale= param must localize event_title even when it
        disagrees with the organizer's stored (DB) locale — the UI-language
        switch never writes that column, so falling back to it is the bug."""
        from app.routers.organizer_claims import list_own_claims

        organizer = make_organizer(organizer_id=5, locale="en")
        claim = _fake_claim(status=CLAIM_STATUS_APPROVED)
        claim.publisher = None

        _mock_own_claims_page(mock_db, [claim])

        event = MagicMock()
        event.id = 42
        event.title_orig = "Jazzkaar Festival Night"
        event.title_localized = {"ru": "Ночь Джазкаар", "en": "Jazzkaar Festival Night"}

        with patch(
            "app.routers.organizer_claims.bulk_resolve_publisher_events",
            new_callable=AsyncMock,
            return_value={99: event},
        ):
            result = await list_own_claims(
                make_request(method="GET", path="/organizer/claims"),
                locale="ru",
                limit=ORGANIZER_OWN_CLAIMS_PAGE_SIZE,
                offset=0,
                current_organizer=organizer,
                db=mock_db,
            )

        assert result["claims"][0]["event_title"] == "Ночь Джазкаар"


class TestRequestClaimLink:
    @pytest.mark.asyncio
    async def test_always_returns_sent_detail(self, mock_db, make_request, make_organizer):
        from app.routers.organizer_claims import ClaimLinkRequestBody, request_claim_link

        organizer = make_organizer(organizer_id=5)

        with (
            patch(
                "app.routers.organizer_claims.get_or_create_organizer",
                new_callable=AsyncMock,
                return_value=organizer,
            ),
            patch(
                "app.routers.organizer_claims.recent_unused_link_exists",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch("app.routers.organizer_claims.send_magic_link", new_callable=AsyncMock),
        ):
            result = await request_claim_link(
                ClaimLinkRequestBody(email="organizer@example.com", event_id=10),
                make_request(method="POST", path="/organizer/claims/request-link"),
                db=mock_db,
            )

        assert result == {"detail": DETAIL_MAGIC_LINK_SENT}


class TestVerifyClaimLink:
    @pytest.mark.asyncio
    async def test_signs_in_and_creates_claim(self, mock_db, make_request, make_organizer):
        from app.auth.tokens import generate_organizer_claim_link_token
        from app.routers.organizer_claims import ClaimLinkVerifyBody, verify_claim_link

        organizer = make_organizer(organizer_id=5)
        token, _, _ = generate_organizer_claim_link_token(organizer_id=5, event_id=10)
        claim = _fake_claim(status=CLAIM_STATUS_APPROVED)

        execute_result = MagicMock()
        execute_result.fetchone.return_value = (5,)
        mock_db.execute.return_value = execute_result
        mock_db.get.return_value = organizer

        with patch(
            "app.routers.organizer_claims.create_claim",
            new_callable=AsyncMock,
            return_value=(claim, True),
        ):
            result = await verify_claim_link(
                make_request(method="POST", path="/organizer/claims/verify-link"),
                ClaimLinkVerifyBody(token=token),
                response=MagicMock(),
                db=mock_db,
            )

        assert result["organizer"]["id"] == 5
        assert result["claim"]["status"] == CLAIM_STATUS_APPROVED

    @pytest.mark.asyncio
    async def test_series_claim_needing_justification_still_signs_in(
        self, mock_db, make_request, make_organizer
    ):
        """The link is spent, so a series claim without a justification returns
        the sign-in with no claim instead of raising (#428)."""
        from app.auth.tokens import generate_organizer_claim_link_token
        from app.routers.organizer_claims import ClaimLinkVerifyBody, verify_claim_link

        organizer = make_organizer(organizer_id=5)
        token, _, _ = generate_organizer_claim_link_token(organizer_id=5, event_id=10)

        execute_result = MagicMock()
        execute_result.fetchone.return_value = (5,)
        mock_db.execute.return_value = execute_result
        mock_db.get.return_value = organizer

        with patch(
            "app.routers.organizer_claims.create_claim",
            new_callable=AsyncMock,
            side_effect=ClaimError(
                http.HTTPStatus.UNPROCESSABLE_ENTITY,
                ERROR_CLAIM_JUSTIFICATION_REQUIRED,
                code=CLAIM_ERROR_CODE_JUSTIFICATION_REQUIRED,
            ),
        ):
            result = await verify_claim_link(
                make_request(method="POST", path="/organizer/claims/verify-link"),
                ClaimLinkVerifyBody(token=token),
                response=MagicMock(),
                db=mock_db,
            )

        assert result["organizer"]["id"] == 5
        assert result["claim"] is None
        assert result["needs_justification"] is True

    @pytest.mark.asyncio
    async def test_already_used_token_rejected(self, mock_db, make_request):
        from app.auth.tokens import generate_organizer_claim_link_token
        from app.routers.organizer_claims import ClaimLinkVerifyBody, verify_claim_link

        token, _, _ = generate_organizer_claim_link_token(organizer_id=5, event_id=10)
        execute_result = MagicMock()
        execute_result.fetchone.return_value = None
        mock_db.execute.return_value = execute_result

        with pytest.raises(HTTPException) as exc:
            await verify_claim_link(
                make_request(method="POST", path="/organizer/claims/verify-link"),
                ClaimLinkVerifyBody(token=token),
                response=MagicMock(),
                db=mock_db,
            )

        assert exc.value.status_code == http.HTTPStatus.BAD_REQUEST

    @pytest.mark.asyncio
    async def test_plain_organizer_sign_in_token_rejected_not_500(self, mock_db, make_request):
        """A regular organizer sign-in token shares this salt but carries no
        "eid" claim — must 400, not raise an uncaught KeyError (code-review
        finding)."""
        from app.auth.tokens import generate_organizer_magic_token
        from app.routers.organizer_claims import ClaimLinkVerifyBody, verify_claim_link

        token, _, _ = generate_organizer_magic_token(organizer_id=5)

        with pytest.raises(HTTPException) as exc:
            await verify_claim_link(
                make_request(method="POST", path="/organizer/claims/verify-link"),
                ClaimLinkVerifyBody(token=token),
                response=MagicMock(),
                db=mock_db,
            )

        assert exc.value.status_code == http.HTTPStatus.BAD_REQUEST


class TestListClaimEvents:
    """GET /organizer/claims/{claim_id}/events (#436) — the Publisher-claim
    event list, paginated the same limit/offset/has_more/total shape as the
    admin queues (see tests/routers/test_admin.py's pagination tests)."""

    @pytest.mark.asyncio
    async def test_returns_paginated_events(
        self, mock_db, make_event, make_request, make_organizer
    ):
        from app.routers.organizer_claims import list_claim_events

        organizer = make_organizer(organizer_id=5)
        claim = _fake_claim(status=CLAIM_STATUS_APPROVED, publisher_id=99)
        events = [make_event(event_id=1), make_event(event_id=2)]

        scalars_result = MagicMock()
        scalars_result.all.return_value = events
        mock_db.scalars.return_value = scalars_result
        mock_db.scalar.return_value = 2

        with patch(
            "app.routers.organizer_claims.own_claim_or_404",
            new_callable=AsyncMock,
            return_value=claim,
        ):
            result = await list_claim_events(
                1,
                make_request(method="GET", path="/organizer/claims/1/events"),
                limit=20,
                offset=0,
                current_organizer=organizer,
                db=mock_db,
                locale=None,
            )

        assert result["total"] == 2
        assert result["limit"] == 20
        assert result["offset"] == 0
        assert result["has_more"] is False
        assert [e["id"] for e in result["events"]] == [1, 2]
        assert result["events"][0]["status"] == "published"

    @pytest.mark.asyncio
    async def test_locale_param_localizes_event_titles(
        self, mock_db, make_event, make_request, make_organizer
    ):
        """(#454) locale=ru must localize each covered event's title
        regardless of the organizer's stored locale."""
        from app.routers.organizer_claims import list_claim_events

        organizer = make_organizer(organizer_id=5, locale="en")
        claim = _fake_claim(status=CLAIM_STATUS_APPROVED, publisher_id=99)
        event = make_event(event_id=1, title="Jazz Night")
        event.title_localized = {"ru": "Джазовая ночь"}

        scalars_result = MagicMock()
        scalars_result.all.return_value = [event]
        mock_db.scalars.return_value = scalars_result
        mock_db.scalar.return_value = 1

        with patch(
            "app.routers.organizer_claims.own_claim_or_404",
            new_callable=AsyncMock,
            return_value=claim,
        ):
            result = await list_claim_events(
                1,
                make_request(method="GET", path="/organizer/claims/1/events"),
                limit=20,
                offset=0,
                locale="ru",
                current_organizer=organizer,
                db=mock_db,
            )

        assert result["events"][0]["title"] == "Джазовая ночь"

    @staticmethod
    async def _list_page(mock_db, make_request, organizer, offset, rows, total):
        """One Claim events page of 2: `rows` from the page query, `total`
        from the COUNT, for an approved Publisher claim on publisher 99."""
        from app.routers.organizer_claims import list_claim_events

        claim = _fake_claim(status=CLAIM_STATUS_APPROVED, publisher_id=99)
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=rows))
        mock_db.scalar = AsyncMock(return_value=total)
        with patch(
            "app.routers.organizer_claims.own_claim_or_404",
            new_callable=AsyncMock,
            return_value=claim,
        ):
            return await list_claim_events(
                1,
                make_request(method="GET", path="/organizer/claims/1/events"),
                limit=2,
                offset=offset,
                current_organizer=organizer,
                db=mock_db,
                locale=None,
            )

    @pytest.mark.asyncio
    async def test_has_more_true_across_page_boundary(
        self, mock_db, make_event, make_request, make_organizer
    ):
        organizer = make_organizer(organizer_id=5)
        rows = [make_event(event_id=1), make_event(event_id=2)]

        result = await self._list_page(mock_db, make_request, organizer, 0, rows, 5)

        assert result["has_more"] is True
        assert [e["id"] for e in result["events"]] == [1, 2]

    @pytest.mark.asyncio
    async def test_returns_paging_envelope_on_every_page(
        self, mock_db, make_event, make_request, make_organizer
    ):
        """Spec #551: the numbered pager needs total/limit/offset/has_more on
        every request, not only the first page."""
        organizer = make_organizer(organizer_id=5)
        rows = [make_event(event_id=1), make_event(event_id=2)]

        first = await self._list_page(mock_db, make_request, organizer, 0, rows, 5)
        middle = await self._list_page(mock_db, make_request, organizer, 2, rows, 5)
        last = await self._list_page(mock_db, make_request, organizer, 4, rows[:1], 5)

        keys = ("total", "limit", "offset", "has_more")
        assert {k: first[k] for k in keys} == {
            "total": 5, "limit": 2, "offset": 0, "has_more": True,
        }
        assert {k: middle[k] for k in keys} == {
            "total": 5, "limit": 2, "offset": 2, "has_more": True,
        }
        assert {k: last[k] for k in keys} == {
            "total": 5, "limit": 2, "offset": 4, "has_more": False,
        }

    @pytest.mark.asyncio
    async def test_empty_claim_has_zero_total(
        self, mock_db, make_request, make_organizer
    ):
        organizer = make_organizer(organizer_id=5)
        result = await self._list_page(mock_db, make_request, organizer, 0, [], None)
        assert (result["total"], result["has_more"], result["events"]) == (0, False, [])

    @pytest.mark.asyncio
    async def test_pages_share_a_starts_at_then_id_order(
        self, mock_db, make_request, make_organizer
    ):
        """Tie-breaker stability across pages: two events starting at the
        same instant must never swap between page 1 and page 2, so every
        page query orders by starts_at desc then id desc, and only
        LIMIT/OFFSET differ between pages."""
        organizer = make_organizer(organizer_id=5)
        sqls = []
        for offset in (0, 2):
            await self._list_page(mock_db, make_request, organizer, offset, [], 3)
            stmt = mock_db.scalars.call_args.args[0]
            sqls.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))

        for sql in sqls:
            assert "ORDER BY events.starts_at DESC, events.id DESC" in sql
            assert "event_sources.publisher_id = 99" in sql
        assert "LIMIT 2 OFFSET 0" in sqls[0]
        assert "LIMIT 2 OFFSET 2" in sqls[1]
        assert sqls[0].replace("OFFSET 0", "OFFSET 2") == sqls[1]

    @pytest.mark.asyncio
    async def test_series_claim_rejected_404(
        self, mock_db, make_request, make_organizer
    ):
        from app.routers.organizer_claims import list_claim_events

        organizer = make_organizer(organizer_id=5)
        claim = _fake_claim(
            kind=CLAIM_KIND_SERIES,
            publisher_id=None,
            event_series_key="the-show|the-venue",
            status=CLAIM_STATUS_APPROVED,
        )

        with patch(
            "app.routers.organizer_claims.own_claim_or_404",
            new_callable=AsyncMock,
            return_value=claim,
        ):
            with pytest.raises(HTTPException) as exc:
                await list_claim_events(
                    1,
                    make_request(method="GET", path="/organizer/claims/1/events"),
                    limit=20,
                    offset=0,
                    current_organizer=organizer,
                    db=mock_db,
                    locale=None,
                )

        assert exc.value.status_code == http.HTTPStatus.NOT_FOUND
        assert exc.value.detail == ERROR_CLAIM_EVENTS_NOT_PUBLISHER

    @pytest.mark.asyncio
    async def test_publisher_claim_with_no_publisher_id_rejected_404(
        self, mock_db, make_request, make_organizer
    ):
        from app.routers.organizer_claims import list_claim_events

        organizer = make_organizer(organizer_id=5)
        claim = _fake_claim(
            kind=CLAIM_KIND_PUBLISHER, publisher_id=None, status=CLAIM_STATUS_APPROVED
        )

        with patch(
            "app.routers.organizer_claims.own_claim_or_404",
            new_callable=AsyncMock,
            return_value=claim,
        ):
            with pytest.raises(HTTPException) as exc:
                await list_claim_events(
                    1,
                    make_request(method="GET", path="/organizer/claims/1/events"),
                    limit=20,
                    offset=0,
                    current_organizer=organizer,
                    db=mock_db,
                    locale=None,
                )

        assert exc.value.status_code == http.HTTPStatus.NOT_FOUND
        assert exc.value.detail == ERROR_CLAIM_EVENTS_NOT_PUBLISHER

    @pytest.mark.asyncio
    async def test_not_yet_approved_claim_rejected_404(
        self, mock_db, make_request, make_organizer
    ):
        from app.routers.organizer_claims import list_claim_events

        organizer = make_organizer(organizer_id=5)
        claim = _fake_claim(
            kind=CLAIM_KIND_PUBLISHER, publisher_id=99, status=CLAIM_STATUS_PENDING
        )

        with patch(
            "app.routers.organizer_claims.own_claim_or_404",
            new_callable=AsyncMock,
            return_value=claim,
        ):
            with pytest.raises(HTTPException) as exc:
                await list_claim_events(
                    1,
                    make_request(method="GET", path="/organizer/claims/1/events"),
                    limit=20,
                    offset=0,
                    current_organizer=organizer,
                    db=mock_db,
                    locale=None,
                )

        assert exc.value.status_code == http.HTTPStatus.NOT_FOUND
        assert exc.value.detail == ERROR_CLAIM_EVENTS_NOT_PUBLISHER

    @pytest.mark.asyncio
    async def test_claim_not_found_propagates_404(
        self, mock_db, make_request, make_organizer
    ):
        from app.routers.organizer_claims import list_claim_events

        organizer = make_organizer(organizer_id=5)

        with patch(
            "app.routers.organizer_claims.own_claim_or_404",
            new_callable=AsyncMock,
            side_effect=ClaimError(http.HTTPStatus.NOT_FOUND, ERROR_CLAIM_NOT_FOUND),
        ):
            with pytest.raises(HTTPException) as exc:
                await list_claim_events(
                    1,
                    make_request(method="GET", path="/organizer/claims/1/events"),
                    limit=20,
                    offset=0,
                    current_organizer=organizer,
                    db=mock_db,
                    locale=None,
                )

        assert exc.value.status_code == http.HTTPStatus.NOT_FOUND
        assert exc.value.detail == ERROR_CLAIM_NOT_FOUND
