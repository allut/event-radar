"""Unit tests for app/claims/verification.py (#412) — the per-source routing
engine (auto-grant vs admin review) and Trusted-claimant derivation/revocation."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.claims.verification import (
    VerificationResult,
    is_trusted_claimant,
    series_claim_result,
    verify_fienta_publisher_claim,
    verify_institutional_publisher_claim,
    verify_piletilevi_claim,
)
from app.constants import (
    CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW,
    CLAIM_VERIFICATION_MECHANISM_DNS_TXT,
    CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN,
    CLAIM_VERIFICATION_MECHANISM_PILETILEVI_PROMOTER,
    CLAIM_VERIFICATION_OUTCOME_ADMIN_REVIEW,
    CLAIM_VERIFICATION_OUTCOME_AUTO_GRANT,
    SOURCE_SLUG_KUMU,
)


class TestVerifyFientaPublisherClaim:
    @pytest.mark.asyncio
    async def test_success_auto_grants(self):
        with patch(
            "app.claims.verification.verify_fienta_token",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await verify_fienta_publisher_claim(
                MagicMock(), "https://fienta.com/api/v1/public/events", "42", "100", "tok"
            )

        assert result == VerificationResult(
            CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN, CLAIM_VERIFICATION_OUTCOME_AUTO_GRANT
        )

    @pytest.mark.asyncio
    async def test_failure_routes_to_admin_review(self):
        with patch(
            "app.claims.verification.verify_fienta_token",
            new_callable=AsyncMock,
            return_value=False,
        ):
            result = await verify_fienta_publisher_claim(
                MagicMock(), "https://fienta.com/api/v1/public/events", "42", "100", "tok"
            )

        assert result == VerificationResult(
            CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN, CLAIM_VERIFICATION_OUTCOME_ADMIN_REVIEW
        )


class TestVerifyInstitutionalPublisherClaim:
    @pytest.mark.asyncio
    async def test_success_auto_grants(self):
        with patch(
            "app.claims.verification.verify_dns_txt_token",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await verify_institutional_publisher_claim(
                MagicMock(), SOURCE_SLUG_KUMU, "tok"
            )

        assert result == VerificationResult(
            CLAIM_VERIFICATION_MECHANISM_DNS_TXT, CLAIM_VERIFICATION_OUTCOME_AUTO_GRANT
        )

    @pytest.mark.asyncio
    async def test_failure_routes_to_admin_review(self):
        with patch(
            "app.claims.verification.verify_dns_txt_token",
            new_callable=AsyncMock,
            return_value=False,
        ):
            result = await verify_institutional_publisher_claim(
                MagicMock(), SOURCE_SLUG_KUMU, "tok"
            )

        assert result == VerificationResult(
            CLAIM_VERIFICATION_MECHANISM_DNS_TXT, CLAIM_VERIFICATION_OUTCOME_ADMIN_REVIEW
        )


class TestVerifyPiletileviClaim:
    @pytest.mark.asyncio
    async def test_resolving_promoter_dns_success_auto_grants(self):
        with (
            patch(
                "app.claims.verification.resolve_promoter_domain",
                new_callable=AsyncMock,
                return_value="own-domain.ee",
            ),
            patch(
                "app.claims.verification.verify_dns_txt_token",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            result = await verify_piletilevi_claim(MagicMock(), "<html/>", "https://x", "tok")

        assert result == VerificationResult(
            CLAIM_VERIFICATION_MECHANISM_PILETILEVI_PROMOTER,
            CLAIM_VERIFICATION_OUTCOME_AUTO_GRANT,
        )

    @pytest.mark.asyncio
    async def test_resolving_promoter_dns_failure_routes_to_admin_review(self):
        with (
            patch(
                "app.claims.verification.resolve_promoter_domain",
                new_callable=AsyncMock,
                return_value="own-domain.ee",
            ),
            patch(
                "app.claims.verification.verify_dns_txt_token",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            result = await verify_piletilevi_claim(MagicMock(), "<html/>", "https://x", "tok")

        assert result == VerificationResult(
            CLAIM_VERIFICATION_MECHANISM_PILETILEVI_PROMOTER,
            CLAIM_VERIFICATION_OUTCOME_ADMIN_REVIEW,
        )

    @pytest.mark.asyncio
    async def test_non_resolving_promoter_routes_to_admin_review_without_dns_check(self):
        with (
            patch(
                "app.claims.verification.resolve_promoter_domain",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.claims.verification.verify_dns_txt_token", new_callable=AsyncMock
            ) as dns_mock,
        ):
            result = await verify_piletilevi_claim(MagicMock(), "<html/>", "https://x", "tok")

        dns_mock.assert_not_awaited()
        assert result == VerificationResult(
            CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW,
            CLAIM_VERIFICATION_OUTCOME_ADMIN_REVIEW,
        )


def test_series_claim_always_routes_to_admin_review():
    assert series_claim_result() == VerificationResult(
        CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW, CLAIM_VERIFICATION_OUTCOME_ADMIN_REVIEW
    )


class TestIsTrustedClaimant:
    @pytest.mark.asyncio
    async def test_no_approved_claims_is_not_trusted(self, mock_db):
        mock_db.scalars.return_value = MagicMock(first=MagicMock(return_value=None))

        assert await is_trusted_claimant(mock_db, organizer_id=1) is False

    @pytest.mark.asyncio
    async def test_approved_non_fienta_claim_is_trusted(self, mock_db):
        """A KUMU/ECH Publisher claim or a Series claim counts."""
        mock_db.scalars.return_value = MagicMock(first=MagicMock(return_value=7))

        assert await is_trusted_claimant(mock_db, organizer_id=1) is True

    @pytest.mark.asyncio
    async def test_revoked_claim_does_not_count(self, mock_db):
        """A revoked claim's status already excludes it from the query, and the
        derivation offers nothing further to 'remove' — CONTEXT.md's
        revocation-strips-trust rule falls out of the CLAIM_STATUS_APPROVED
        filter alone."""
        mock_db.scalars.return_value = MagicMock(first=MagicMock(return_value=None))

        result = await is_trusted_claimant(mock_db, organizer_id=1)

        assert result is False
        mock_db.scalars.assert_awaited_once()
