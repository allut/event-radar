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
    CLAIM_STATUS_APPROVED,
    CLAIM_STATUS_PENDING,
    CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN,
    DETAIL_MAGIC_LINK_SENT,
    ERROR_CLAIM_NOT_FOUND,
    ERROR_DAILY_CLAIM_LIMIT,
)


def _fake_claim(**overrides) -> MagicMock:
    c = MagicMock()
    c.id = 1
    c.kind = CLAIM_KIND_PUBLISHER
    c.publisher_id = 99
    c.event_series_key = None
    c.status = CLAIM_STATUS_PENDING
    c.verification_mechanism = CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN
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

        with patch(
            "app.routers.organizer_claims.create_claim", new_callable=AsyncMock, return_value=claim
        ):
            result = await create_own_claim(
                CreateClaimBody(event_id=10),
                make_request(method="POST", path="/organizer/claims"),
                current_organizer=organizer,
                db=mock_db,
            )

        assert result["id"] == 1
        assert result["status"] == CLAIM_STATUS_APPROVED

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
                    current_organizer=organizer,
                    db=mock_db,
                )

        assert exc.value.status_code == http.HTTPStatus.TOO_MANY_REQUESTS
        assert exc.value.detail == ERROR_DAILY_CLAIM_LIMIT


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
            "app.routers.organizer_claims.create_claim", new_callable=AsyncMock, return_value=claim
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
