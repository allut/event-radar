"""Tests for app/claims/lifecycle.py (#413) — create/cancel/recheck/expire,
wired to #412's verification engine via mocked db + httpx client."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.claims.lifecycle import (
    ClaimError,
    cancel_claim,
    create_claim,
    expire_stale_claims,
    recheck_claim,
)
from app.claims.verification import VerificationResult
from app.constants import (
    CLAIM_KIND_PUBLISHER,
    CLAIM_KIND_SERIES,
    CLAIM_STATUS_APPROVED,
    CLAIM_STATUS_CANCELLED,
    CLAIM_STATUS_PENDING,
    CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW,
    CLAIM_VERIFICATION_MECHANISM_DNS_TXT,
    CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN,
    CLAIM_VERIFICATION_OUTCOME_ADMIN_REVIEW,
    CLAIM_VERIFICATION_OUTCOME_AUTO_GRANT,
    KUMU_VERIFICATION_DOMAIN,
    ORGANIZER_DAILY_CLAIM_CAP,
    SOURCE_SLUG_FIENTA,
    SOURCE_SLUG_KUMU,
)


def _fake_event_source(
    *, publisher_id: int | None = None, external_id: str = "100", source_slug: str = SOURCE_SLUG_FIENTA
) -> MagicMock:
    es = MagicMock()
    es.event_id = 10
    es.external_id = external_id
    es.publisher_id = publisher_id
    source = MagicMock()
    source.slug = source_slug
    source.config = {}
    es.source = source
    if publisher_id is not None:
        publisher = MagicMock()
        publisher.id = publisher_id
        publisher.external_id = "42"
        es.publisher = publisher
    else:
        es.publisher = None
    return es


def _fake_claim(**overrides) -> MagicMock:
    c = MagicMock()
    c.id = 1
    c.organizer_id = 5
    c.kind = CLAIM_KIND_PUBLISHER
    c.publisher_id = 99
    c.event_series_key = None
    c.status = CLAIM_STATUS_PENDING
    c.verification_mechanism = CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN
    c.proof_token = "er-verify-abc"
    c.last_checked_at = datetime.now(timezone.utc) - timedelta(days=1)
    c.resolved_at = None
    for k, v in overrides.items():
        setattr(c, k, v)
    return c


class TestCreateClaim:
    @pytest.mark.asyncio
    async def test_daily_cap_blocks_before_any_insert(self, mock_db, make_organizer):
        mock_db.scalar.return_value = ORGANIZER_DAILY_CLAIM_CAP
        organizer = make_organizer(organizer_id=5)

        with pytest.raises(ClaimError) as exc:
            await create_claim(mock_db, AsyncMock(), organizer, event_id=10)

        assert exc.value.status_code == 429
        mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_event_not_found_404(self, mock_db, make_organizer):
        mock_db.scalar.return_value = 0
        mock_db.get.return_value = None
        organizer = make_organizer(organizer_id=5)

        with pytest.raises(ClaimError) as exc:
            await create_claim(mock_db, AsyncMock(), organizer, event_id=999)

        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_no_resolvable_source_422(self, mock_db, make_organizer, make_event):
        mock_db.scalar = AsyncMock(side_effect=[0, None])
        mock_db.get.return_value = make_event()
        organizer = make_organizer(organizer_id=5)

        with pytest.raises(ClaimError) as exc:
            await create_claim(mock_db, AsyncMock(), organizer, event_id=10)

        assert exc.value.status_code == 422

    @pytest.mark.asyncio
    async def test_fienta_publisher_claim_auto_grants(self, mock_db, make_organizer, make_event):
        es = _fake_event_source(publisher_id=99)
        mock_db.scalar = AsyncMock(side_effect=[0, es])
        mock_db.get.return_value = make_event()
        organizer = make_organizer(organizer_id=5)

        with patch(
            "app.claims.lifecycle.verify_fienta_publisher_claim",
            new_callable=AsyncMock,
            return_value=VerificationResult(
                CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN, CLAIM_VERIFICATION_OUTCOME_AUTO_GRANT
            ),
        ):
            claim = await create_claim(mock_db, AsyncMock(), organizer, event_id=10)

        assert claim.kind == CLAIM_KIND_PUBLISHER
        assert claim.publisher_id == 99
        assert claim.status == CLAIM_STATUS_APPROVED
        assert claim.verification_mechanism == CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN
        assert claim.resolved_at is not None
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dns_txt_grant_persists_verification_domain(
        self, mock_db, make_organizer, make_event
    ):
        """#415's pending screen needs the domain a DNS-TXT check ran against
        to render its record-name instructions, so it's persisted on the
        Claim row rather than only living in the transient VerificationResult."""
        es = _fake_event_source(publisher_id=99, source_slug=SOURCE_SLUG_KUMU)
        mock_db.scalar = AsyncMock(side_effect=[0, es])
        mock_db.get.return_value = make_event()
        organizer = make_organizer(organizer_id=5)

        with patch(
            "app.claims.lifecycle.verify_institutional_publisher_claim",
            new_callable=AsyncMock,
            return_value=VerificationResult(
                CLAIM_VERIFICATION_MECHANISM_DNS_TXT,
                CLAIM_VERIFICATION_OUTCOME_AUTO_GRANT,
                domain=KUMU_VERIFICATION_DOMAIN,
            ),
        ):
            claim = await create_claim(mock_db, AsyncMock(), organizer, event_id=10)

        assert claim.verification_domain == KUMU_VERIFICATION_DOMAIN

    @pytest.mark.asyncio
    async def test_series_claim_not_trusted_stays_pending_admin_review(
        self, mock_db, make_organizer, make_event
    ):
        es = _fake_event_source(publisher_id=None)
        mock_db.scalar = AsyncMock(side_effect=[0, es])
        mock_db.get.return_value = make_event()
        organizer = make_organizer(organizer_id=5)

        with patch(
            "app.claims.lifecycle.is_trusted_claimant", new_callable=AsyncMock, return_value=False
        ):
            claim = await create_claim(mock_db, AsyncMock(), organizer, event_id=10)

        assert claim.kind == CLAIM_KIND_SERIES
        assert claim.event_series_key is not None
        assert claim.status == CLAIM_STATUS_PENDING
        assert claim.verification_mechanism == CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW

    @pytest.mark.asyncio
    async def test_series_claim_trusted_claimant_auto_grants(
        self, mock_db, make_organizer, make_event
    ):
        es = _fake_event_source(publisher_id=None)
        mock_db.scalar = AsyncMock(side_effect=[0, es])
        mock_db.get.return_value = make_event()
        organizer = make_organizer(organizer_id=5)

        with patch(
            "app.claims.lifecycle.is_trusted_claimant", new_callable=AsyncMock, return_value=True
        ):
            claim = await create_claim(mock_db, AsyncMock(), organizer, event_id=10)

        assert claim.status == CLAIM_STATUS_APPROVED

    @pytest.mark.asyncio
    async def test_race_rejected_with_409(self, mock_db, make_organizer, make_event):
        es = _fake_event_source(publisher_id=99)
        mock_db.scalar = AsyncMock(side_effect=[0, es])
        mock_db.get.return_value = make_event()
        mock_db.flush = AsyncMock(side_effect=IntegrityError("stmt", "params", Exception("dup")))
        organizer = make_organizer(organizer_id=5)

        with pytest.raises(ClaimError) as exc:
            await create_claim(mock_db, AsyncMock(), organizer, event_id=10)

        assert exc.value.status_code == 409
        mock_db.rollback.assert_awaited_once()


class TestGetOwnClaim:
    @pytest.mark.asyncio
    async def test_returns_claim_regardless_of_status(self, mock_db, make_organizer):
        """Unlike cancel/recheck's _own_pending_claim_or_404, #415's pending
        screen needs to read a resolved claim too (approved/cancelled/expired)
        so it can render that outcome instead of erroring."""
        from app.claims.lifecycle import get_own_claim

        claim = _fake_claim(status=CLAIM_STATUS_APPROVED)
        mock_db.scalar.return_value = claim
        organizer = make_organizer(organizer_id=5)

        result = await get_own_claim(mock_db, organizer, claim_id=1)

        assert result is claim

    @pytest.mark.asyncio
    async def test_not_found_404(self, mock_db, make_organizer):
        from app.claims.lifecycle import get_own_claim

        mock_db.scalar.return_value = None
        organizer = make_organizer(organizer_id=5)

        with pytest.raises(ClaimError) as exc:
            await get_own_claim(mock_db, organizer, claim_id=1)
        assert exc.value.status_code == 404


class TestCancelClaim:
    @pytest.mark.asyncio
    async def test_cancels_own_pending_claim(self, mock_db, make_organizer):
        claim = _fake_claim(status=CLAIM_STATUS_PENDING)
        mock_db.scalar.return_value = claim
        organizer = make_organizer(organizer_id=5)

        result = await cancel_claim(mock_db, organizer, claim_id=1)

        assert result.status == CLAIM_STATUS_CANCELLED
        assert result.resolved_at is not None
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_not_found_404(self, mock_db, make_organizer):
        mock_db.scalar.return_value = None
        organizer = make_organizer(organizer_id=5)

        with pytest.raises(ClaimError) as exc:
            await cancel_claim(mock_db, organizer, claim_id=1)
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_already_approved_conflict(self, mock_db, make_organizer):
        claim = _fake_claim(status=CLAIM_STATUS_APPROVED)
        mock_db.scalar.return_value = claim
        organizer = make_organizer(organizer_id=5)

        with pytest.raises(ClaimError) as exc:
            await cancel_claim(mock_db, organizer, claim_id=1)
        assert exc.value.status_code == 409


class TestRecheckClaim:
    @pytest.mark.asyncio
    async def test_admin_review_mechanism_rejected(self, mock_db, make_organizer):
        claim = _fake_claim(
            status=CLAIM_STATUS_PENDING,
            verification_mechanism=CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW,
        )
        mock_db.scalar.return_value = claim
        organizer = make_organizer(organizer_id=5)

        with pytest.raises(ClaimError) as exc:
            await recheck_claim(mock_db, AsyncMock(), organizer, claim_id=1)
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_automated_mechanism_rechecks_and_bumps_last_checked_at(
        self, mock_db, make_organizer, make_event
    ):
        claim = _fake_claim(
            status=CLAIM_STATUS_PENDING,
            verification_mechanism=CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN,
        )
        es = _fake_event_source(publisher_id=99)
        stale_checked_at = claim.last_checked_at
        mock_db.scalar = AsyncMock(side_effect=[claim, es])
        mock_db.get.return_value = make_event()
        organizer = make_organizer(organizer_id=5)

        with patch(
            "app.claims.lifecycle.verify_fienta_publisher_claim",
            new_callable=AsyncMock,
            return_value=VerificationResult(
                CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN, CLAIM_VERIFICATION_OUTCOME_ADMIN_REVIEW
            ),
        ):
            result = await recheck_claim(mock_db, AsyncMock(), organizer, claim_id=1)

        assert result.status == CLAIM_STATUS_PENDING
        assert result.last_checked_at > stale_checked_at
        mock_db.commit.assert_awaited_once()


class TestExpireStaleClaims:
    @pytest.mark.asyncio
    async def test_returns_expired_count(self, mock_db):
        execute_result = MagicMock()
        execute_result.scalars.return_value = MagicMock(all=MagicMock(return_value=[1, 2, 3]))
        mock_db.execute.return_value = execute_result

        summary = await expire_stale_claims(mock_db)

        assert summary == {"expired": 3}
        mock_db.execute.assert_awaited_once()
