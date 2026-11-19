"""Unit tests for app/claims/verification.py (#412, #428) — the per-source
routing engine deciding auto-grant vs admin review."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.claims.piletilevi_promoter import PromoterContact
from app.claims.verification import (
    VerificationResult,
    series_claim_result,
    verify_fienta_publisher_claim,
    verify_institutional_publisher_claim,
    verify_piletilevi_claim,
)
from app._generated.shared_constants import (
    CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW,
    CLAIM_VERIFICATION_MECHANISM_DNS_TXT,
    CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN,
    CLAIM_VERIFICATION_MECHANISM_PILETILEVI_MAILBOX,
    CLAIM_VERIFICATION_MECHANISM_PILETILEVI_PROMOTER,
)
from app.constants.claims import (
    CLAIM_VERIFICATION_OUTCOME_ADMIN_REVIEW,
    CLAIM_VERIFICATION_OUTCOME_AUTO_GRANT,
)
from app.constants.ingestion import KUMU_VERIFICATION_DOMAIN, SOURCE_SLUG_KUMU


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
            CLAIM_VERIFICATION_MECHANISM_DNS_TXT,
            CLAIM_VERIFICATION_OUTCOME_AUTO_GRANT,
            domain=KUMU_VERIFICATION_DOMAIN,
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
            CLAIM_VERIFICATION_MECHANISM_DNS_TXT,
            CLAIM_VERIFICATION_OUTCOME_ADMIN_REVIEW,
            domain=KUMU_VERIFICATION_DOMAIN,
        )


class TestVerifyPiletileviClaim:
    @pytest.mark.asyncio
    async def test_resolving_promoter_dns_success_auto_grants(self):
        with (
            patch(
                "app.claims.verification.resolve_promoter_contact",
                new_callable=AsyncMock,
                return_value=PromoterContact(domain="own-domain.example", email=None),
            ),
            patch(
                "app.claims.verification.verify_dns_txt_token",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            result = await verify_piletilevi_claim(
                MagicMock(), "<html/>", "https://x", "tok", "organizer@example.com"
            )

        assert result == VerificationResult(
            CLAIM_VERIFICATION_MECHANISM_PILETILEVI_PROMOTER,
            CLAIM_VERIFICATION_OUTCOME_AUTO_GRANT,
            domain="own-domain.example",
        )

    @pytest.mark.asyncio
    async def test_resolving_promoter_dns_failure_routes_to_admin_review(self):
        with (
            patch(
                "app.claims.verification.resolve_promoter_contact",
                new_callable=AsyncMock,
                return_value=PromoterContact(domain="own-domain.example", email=None),
            ),
            patch(
                "app.claims.verification.verify_dns_txt_token",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            result = await verify_piletilevi_claim(
                MagicMock(), "<html/>", "https://x", "tok", "organizer@example.com"
            )

        assert result == VerificationResult(
            CLAIM_VERIFICATION_MECHANISM_PILETILEVI_PROMOTER,
            CLAIM_VERIFICATION_OUTCOME_ADMIN_REVIEW,
            domain="own-domain.example",
        )

    @pytest.mark.asyncio
    async def test_mailbox_exact_match_auto_grants(self):
        """(#428) No domain-provable channel, but the promoter's published
        contact mailbox exactly matches (case-insensitively) the claiming
        organizer's own account email."""
        with patch(
            "app.claims.verification.resolve_promoter_contact",
            new_callable=AsyncMock,
            return_value=PromoterContact(domain=None, email="organizer@example.com"),
        ):
            result = await verify_piletilevi_claim(
                MagicMock(), "<html/>", "https://x", "tok", "Organizer@Example.com"
            )

        assert result == VerificationResult(
            CLAIM_VERIFICATION_MECHANISM_PILETILEVI_MAILBOX,
            CLAIM_VERIFICATION_OUTCOME_AUTO_GRANT,
            contact="organizer@example.com",
        )

    @pytest.mark.asyncio
    async def test_mailbox_mismatch_routes_to_admin_review_with_evidence(self):
        with patch(
            "app.claims.verification.resolve_promoter_contact",
            new_callable=AsyncMock,
            return_value=PromoterContact(domain=None, email="promoter@other.example"),
        ):
            result = await verify_piletilevi_claim(
                MagicMock(), "<html/>", "https://x", "tok", "organizer@example.com"
            )

        assert result == VerificationResult(
            CLAIM_VERIFICATION_MECHANISM_PILETILEVI_MAILBOX,
            CLAIM_VERIFICATION_OUTCOME_ADMIN_REVIEW,
            contact="promoter@other.example",
        )

    @pytest.mark.asyncio
    async def test_no_contact_info_routes_to_admin_review_with_no_evidence(self):
        with patch(
            "app.claims.verification.resolve_promoter_contact",
            new_callable=AsyncMock,
            return_value=PromoterContact(domain=None, email=None),
        ):
            result = await verify_piletilevi_claim(
                MagicMock(), "<html/>", "https://x", "tok", "organizer@example.com"
            )

        assert result == VerificationResult(
            CLAIM_VERIFICATION_MECHANISM_PILETILEVI_MAILBOX,
            CLAIM_VERIFICATION_OUTCOME_ADMIN_REVIEW,
            contact=None,
        )

    @pytest.mark.asyncio
    async def test_non_resolving_promoter_routes_to_admin_review_without_dns_check(self):
        with (
            patch(
                "app.claims.verification.resolve_promoter_contact",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "app.claims.verification.verify_dns_txt_token", new_callable=AsyncMock
            ) as dns_mock,
        ):
            result = await verify_piletilevi_claim(
                MagicMock(), "<html/>", "https://x", "tok", "organizer@example.com"
            )

        dns_mock.assert_not_awaited()
        assert result == VerificationResult(
            CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW,
            CLAIM_VERIFICATION_OUTCOME_ADMIN_REVIEW,
        )


def test_series_claim_always_routes_to_admin_review():
    """(#428) No Trusted-claimant fast-track exists any more — this is the
    only outcome a Series claim can ever get from the verification engine."""
    assert series_claim_result() == VerificationResult(
        CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW, CLAIM_VERIFICATION_OUTCOME_ADMIN_REVIEW
    )


def test_trusted_claimant_fast_track_no_longer_exists():
    """Regression guard (#428 acceptance criteria): the Trusted-claimant
    derivation function itself must be gone, not merely unused."""
    import app.claims.verification as verification_module

    assert not hasattr(verification_module, "is_trusted_claimant")
