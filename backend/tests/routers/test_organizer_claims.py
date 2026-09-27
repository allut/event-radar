"""Tests for routers/organizer_claims.py (#413) — thin HTTP wiring over
app/claims/lifecycle.py, exercised the same way as test_organizer_venues.py:
calling the endpoint functions directly against a mocked db."""

import http
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.claims.lifecycle import ClaimError
from app.constants import (
    CLAIM_KIND_PUBLISHER,
    CLAIM_KIND_SERIES,
    CLAIM_STATUS_APPROVED,
    CLAIM_STATUS_PENDING,
    CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN,
    DETAIL_MAGIC_LINK_SENT,
    ERROR_CLAIM_EVENTS_NOT_PUBLISHER,
    ERROR_CLAIM_NOT_FOUND,
    ERROR_CLAIM_OWN_SUBMISSION,
    ERROR_DAILY_CLAIM_LIMIT,
    ERROR_EVENT_NOT_FOUND,
)


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


class TestGetClaim:
    """#415's pending screen fetch — GET /organizer/claims/{claim_id}."""

    @pytest.mark.asyncio
    async def test_assembles_dns_instructions_for_dns_txt_mechanism(
        self, mock_db, make_request, make_organizer
    ):
        from app.constants import CLAIM_VERIFICATION_MECHANISM_DNS_TXT
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
        from app.constants import CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW
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
        from app.constants import CLAIM_STATUS_DECLINED, CLAIM_STATUS_REVOKED
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
        from app.constants import CLAIM_STATUS_REVOKED
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


class TestListOwnClaims:
    """GET /organizer/claims (#446) — the caller's own claims, newest first."""

    @pytest.mark.asyncio
    async def test_bulk_resolves_publisher_event_and_name(
        self, mock_db, make_request, make_organizer
    ):
        from app.routers.organizer_claims import list_own_claims

        organizer = make_organizer(organizer_id=5)
        claim = _fake_claim(status=CLAIM_STATUS_APPROVED)
        claim.publisher = MagicMock(name="Jazzkaar")
        claim.publisher.name = "Jazzkaar"

        scalars_result = MagicMock()
        scalars_result.all.return_value = [claim]
        mock_db.execute.return_value.scalars.return_value = scalars_result

        event = MagicMock()
        event.id = 42
        event.title_orig = "Jazzkaar Festival Night"

        with patch(
            "app.routers.organizer_claims.bulk_resolve_publisher_events",
            new_callable=AsyncMock,
            return_value={99: event},
        ):
            result = await list_own_claims(
                make_request(method="GET", path="/organizer/claims"),
                current_organizer=organizer,
                db=mock_db,
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
        from app.constants import CLAIM_STATUS_DECLINED, CLAIM_STATUS_REVOKED
        from app.routers.organizer_claims import list_own_claims

        organizer = make_organizer(organizer_id=5)
        claim = _fake_claim(status=CLAIM_STATUS_REVOKED)
        claim.publisher = None

        scalars_result = MagicMock()
        scalars_result.all.return_value = [claim]
        mock_db.execute.return_value.scalars.return_value = scalars_result

        with patch(
            "app.routers.organizer_claims.bulk_resolve_publisher_events",
            new_callable=AsyncMock,
            return_value={},
        ):
            result = await list_own_claims(
                make_request(method="GET", path="/organizer/claims"),
                current_organizer=organizer,
                db=mock_db,
            )

        assert result["claims"][0]["status"] == CLAIM_STATUS_DECLINED

    @pytest.mark.asyncio
    async def test_series_claim_uses_representative_event_scan(
        self, mock_db, make_request, make_organizer
    ):
        from app.routers.organizer_claims import list_own_claims

        organizer = make_organizer(organizer_id=5)
        claim = _fake_claim(kind=CLAIM_KIND_SERIES, publisher_id=None, event_series_key="k")
        claim.publisher = None

        scalars_result = MagicMock()
        scalars_result.all.return_value = [claim]
        mock_db.execute.return_value.scalars.return_value = scalars_result

        event = MagicMock()
        event.id = 7
        event.title_orig = "Winter Market"

        with patch(
            "app.routers.organizer_claims.bulk_resolve_publisher_events",
            new_callable=AsyncMock,
            return_value={},
        ), patch(
            "app.routers.organizer_claims.representative_event_for_claim",
            new_callable=AsyncMock,
            return_value=event,
        ):
            result = await list_own_claims(
                make_request(method="GET", path="/organizer/claims"),
                current_organizer=organizer,
                db=mock_db,
            )

        assert result["claims"][0]["event_id"] == 7
        assert result["claims"][0]["event_title"] == "Winter Market"
        assert result["claims"][0]["publisher_name"] is None


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


def _make_source(event_id: int = 42, source_id: int = 1, publisher_id: int | None = 99) -> MagicMock:
    es = MagicMock()
    es.id = source_id
    es.event_id = event_id
    es.publisher_id = publisher_id
    return es


class TestSearchClaimableEvents(object):
    @pytest.mark.asyncio
    async def test_query_too_short_rejected(self, mock_db, make_request, make_organizer):
        from app.routers.organizer_claims import search_claimable_events

        with pytest.raises(HTTPException) as exc:
            await search_claimable_events(
                make_request(method="GET", path="/organizer/claims/search"),
                q="a",
                current_organizer=make_organizer(),
                db=mock_db,
            )
        assert exc.value.status_code == http.HTTPStatus.UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_excludes_already_claimed_event(self, mock_db, make_event, make_request, make_organizer):
        """An event whose Publisher already has an *approved* claim (#441/ADR
        0004) is filtered out of search results — cross-surface retirement."""
        from app.routers.organizer_claims import search_claimable_events

        claimed_event = make_event(event_id=1, title="Jazz Night")
        claimed_event.sources = [_make_source(event_id=1, publisher_id=99)]
        open_event = make_event(event_id=2, title="Jazz Brunch")
        open_event.sources = [_make_source(event_id=2, publisher_id=100)]

        candidates_result = MagicMock()
        candidates_result.scalars.return_value.all.return_value = [claimed_event, open_event]
        claim_keys_result = MagicMock()
        claim_keys_row = MagicMock(publisher_id=99, event_series_key=None)
        claim_keys_result.all.return_value = [claim_keys_row]
        mock_db.execute.side_effect = [candidates_result, claim_keys_result]

        result = await search_claimable_events(
            make_request(method="GET", path="/organizer/claims/search"),
            q="jazz",
            current_organizer=make_organizer(),
            db=mock_db,
        )

        assert [e["id"] for e in result["events"]] == [2]

    @pytest.mark.asyncio
    async def test_includes_pending_only_claim_event(self, mock_db, make_event, make_request, make_organizer):
        """(#441) A Publisher target with only a *pending* claim must still
        surface in search — a rival claimant needs a product path to start
        proving ownership, per ADR 0004."""
        from app.routers.organizer_claims import search_claimable_events

        pending_event = make_event(event_id=1, title="Jazz Night")
        pending_event.sources = [_make_source(event_id=1, publisher_id=99)]

        candidates_result = MagicMock()
        candidates_result.scalars.return_value.all.return_value = [pending_event]
        claim_keys_result = MagicMock()
        # The DB-side query itself filters to approved claims only, so a
        # pending-only Publisher never appears in this row set.
        claim_keys_result.all.return_value = []
        mock_db.execute.side_effect = [candidates_result, claim_keys_result]

        result = await search_claimable_events(
            make_request(method="GET", path="/organizer/claims/search"),
            q="jazz",
            current_organizer=make_organizer(),
            db=mock_db,
        )

        assert [e["id"] for e in result["events"]] == [1]

    @pytest.mark.asyncio
    async def test_event_with_no_source_excluded(self, mock_db, make_event, make_request, make_organizer):
        """An organizer's own direct submission (no EventSource at all) has
        nothing to claim against and must not appear."""
        from app.routers.organizer_claims import search_claimable_events

        event = make_event(event_id=1)
        event.sources = []

        candidates_result = MagicMock()
        candidates_result.scalars.return_value.all.return_value = [event]
        claim_keys_result = MagicMock()
        claim_keys_result.all.return_value = []
        mock_db.execute.side_effect = [candidates_result, claim_keys_result]

        result = await search_claimable_events(
            make_request(method="GET", path="/organizer/claims/search"),
            q="jazz",
            current_organizer=make_organizer(),
            db=mock_db,
        )

        assert result["events"] == []


class TestSuggestedClaimableEvents:
    @pytest.mark.asyncio
    async def test_free_email_domain_returns_no_suggestions(self, mock_db, make_request, make_organizer):
        from app.routers.organizer_claims import suggested_claimable_events

        organizer = make_organizer()
        organizer.email = "promoter@gmail.com"

        result = await suggested_claimable_events(
            make_request(method="GET", path="/organizer/claims/suggestions"),
            current_organizer=organizer,
            db=mock_db,
        )

        assert result["events"] == []
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_matches_event_url_domain(self, mock_db, make_event, make_request, make_organizer):
        from app.routers.organizer_claims import suggested_claimable_events

        organizer = make_organizer()
        organizer.email = "team@example-promoter.ee"

        matching = make_event(event_id=1, title="Their show")
        matching.url = "https://tickets.example-promoter.ee/event/1"
        matching.sources = [_make_source(event_id=1, publisher_id=1)]

        decoy = make_event(event_id=2, title="Someone else's show")
        decoy.url = "https://notexample-promoter.ee/event/2"
        decoy.sources = [_make_source(event_id=2, publisher_id=2)]

        candidates_result = MagicMock()
        candidates_result.scalars.return_value.all.return_value = [matching, decoy]
        claim_keys_result = MagicMock()
        claim_keys_result.all.return_value = []
        mock_db.execute.side_effect = [candidates_result, claim_keys_result]

        result = await suggested_claimable_events(
            make_request(method="GET", path="/organizer/claims/suggestions"),
            current_organizer=organizer,
            db=mock_db,
        )

        assert [e["id"] for e in result["events"]] == [1]


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
            )

        assert result["total"] == 2
        assert result["limit"] == 20
        assert result["offset"] == 0
        assert result["has_more"] is False
        assert [e["id"] for e in result["events"]] == [1, 2]
        assert result["events"][0]["status"] == "published"

    @pytest.mark.asyncio
    async def test_has_more_true_across_page_boundary(
        self, mock_db, make_event, make_request, make_organizer
    ):
        from app.routers.organizer_claims import list_claim_events

        organizer = make_organizer(organizer_id=5)
        claim = _fake_claim(status=CLAIM_STATUS_APPROVED, publisher_id=99)
        # limit+1 sentinel row past the requested page of 2.
        events = [make_event(event_id=1), make_event(event_id=2), make_event(event_id=3)]

        scalars_result = MagicMock()
        scalars_result.all.return_value = events
        mock_db.scalars.return_value = scalars_result
        mock_db.scalar.return_value = 5

        with patch(
            "app.routers.organizer_claims.own_claim_or_404",
            new_callable=AsyncMock,
            return_value=claim,
        ):
            result = await list_claim_events(
                1,
                make_request(method="GET", path="/organizer/claims/1/events"),
                limit=2,
                offset=0,
                current_organizer=organizer,
                db=mock_db,
            )

        assert result["has_more"] is True
        assert [e["id"] for e in result["events"]] == [1, 2]

    @pytest.mark.asyncio
    async def test_total_omitted_past_first_page(
        self, mock_db, make_event, make_request, make_organizer
    ):
        from app.routers.organizer_claims import list_claim_events

        organizer = make_organizer(organizer_id=5)
        claim = _fake_claim(status=CLAIM_STATUS_APPROVED, publisher_id=99)

        scalars_result = MagicMock()
        scalars_result.all.return_value = [make_event(event_id=3)]
        mock_db.scalars.return_value = scalars_result

        with patch(
            "app.routers.organizer_claims.own_claim_or_404",
            new_callable=AsyncMock,
            return_value=claim,
        ):
            result = await list_claim_events(
                1,
                make_request(method="GET", path="/organizer/claims/1/events"),
                limit=2,
                offset=2,
                current_organizer=organizer,
                db=mock_db,
            )

        assert result["total"] is None
        mock_db.scalar.assert_not_called()

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
                )

        assert exc.value.status_code == http.HTTPStatus.NOT_FOUND
        assert exc.value.detail == ERROR_CLAIM_NOT_FOUND
