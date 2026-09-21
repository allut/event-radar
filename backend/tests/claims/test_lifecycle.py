"""Tests for app/claims/lifecycle.py (#413) — create/cancel/recheck/expire,
wired to #412's verification engine via mocked db + httpx client."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.claims.lifecycle import (
    ClaimError,
    cancel_claim,
    claim_status_from_claim,
    claiming_organizer_name,
    create_claim,
    expire_stale_claims,
    recheck_claim,
    resolve_claim_for_event,
)
from app.claims.verification import VerificationResult
from app.constants import (
    CLAIM_DISCOVERY_STATUS_CLAIMED,
    CLAIM_DISCOVERY_STATUS_PENDING,
    CLAIM_DISCOVERY_STATUS_UNCLAIMED,
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

    @pytest.mark.asyncio
    async def test_auto_grant_sends_claim_granted_email(self, mock_db, make_organizer, make_event):
        """#421: create_claim's inline auto-grant path notifies the claimant
        immediately — no admin note, so the email falls back to its default
        copy (empty string in, fallback_note used)."""
        es = _fake_event_source(publisher_id=99)
        mock_db.scalar = AsyncMock(side_effect=[0, es])
        event = make_event()
        event.title_orig = "Jazz Night"
        mock_db.get.return_value = event
        organizer = make_organizer(organizer_id=5)

        with (
            patch(
                "app.claims.lifecycle.verify_fienta_publisher_claim",
                new_callable=AsyncMock,
                return_value=VerificationResult(
                    CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN,
                    CLAIM_VERIFICATION_OUTCOME_AUTO_GRANT,
                ),
            ),
            patch(
                "app.claims.lifecycle.send_claim_granted_email", new_callable=AsyncMock
            ) as send_mock,
        ):
            await create_claim(mock_db, AsyncMock(), organizer, event_id=10)

        send_mock.assert_awaited_once()
        args, kwargs = send_mock.call_args
        assert args == (organizer.email, "Jazz Night", "", organizer.locale)
        assert "http_client" in kwargs

    @pytest.mark.asyncio
    async def test_pending_admin_review_sends_no_email(self, mock_db, make_organizer, make_event):
        """A claim that stays pending (routed to admin review) must not send
        the granted email — only an actual grant does."""
        es = _fake_event_source(publisher_id=None)
        mock_db.scalar = AsyncMock(side_effect=[0, es])
        mock_db.get.return_value = make_event()
        organizer = make_organizer(organizer_id=5)

        with (
            patch(
                "app.claims.lifecycle.is_trusted_claimant",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "app.claims.lifecycle.send_claim_granted_email", new_callable=AsyncMock
            ) as send_mock,
        ):
            await create_claim(mock_db, AsyncMock(), organizer, event_id=10)

        send_mock.assert_not_awaited()


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

    @pytest.mark.asyncio
    async def test_cancel_sends_self_cancelled_email(self, mock_db, make_organizer, make_event):
        """#421: a self-cancel notifies the organizer, using the resolved
        representative event's title when one can be resolved."""
        claim = _fake_claim(status=CLAIM_STATUS_PENDING)
        mock_db.scalar.return_value = claim
        organizer = make_organizer(organizer_id=5)
        event = make_event()
        event.title_orig = "Jazz Night"

        with (
            patch(
                "app.claims.pinning.representative_event_for_claim",
                new_callable=AsyncMock,
                return_value=event,
            ),
            patch(
                "app.claims.lifecycle.send_claim_self_cancelled_email", new_callable=AsyncMock
            ) as send_mock,
        ):
            await cancel_claim(mock_db, organizer, claim_id=1)

        send_mock.assert_awaited_once_with(organizer.email, "Jazz Night", organizer.locale)


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

    @pytest.mark.asyncio
    async def test_recheck_auto_grant_sends_claim_granted_email(
        self, mock_db, make_organizer, make_event
    ):
        """#421: a recheck that auto-grants (e.g. a DNS-TXT record that has
        now propagated) must notify the claimant too, same as the initial
        create_claim auto-grant path."""
        claim = _fake_claim(
            status=CLAIM_STATUS_PENDING,
            verification_mechanism=CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN,
        )
        es = _fake_event_source(publisher_id=99)
        mock_db.scalar = AsyncMock(side_effect=[claim, es])
        event = make_event()
        event.title_orig = "Jazz Night"
        mock_db.get.return_value = event
        organizer = make_organizer(organizer_id=5)

        with (
            patch(
                "app.claims.lifecycle.verify_fienta_publisher_claim",
                new_callable=AsyncMock,
                return_value=VerificationResult(
                    CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN,
                    CLAIM_VERIFICATION_OUTCOME_AUTO_GRANT,
                ),
            ),
            patch(
                "app.claims.lifecycle.send_claim_granted_email", new_callable=AsyncMock
            ) as send_mock,
        ):
            result = await recheck_claim(mock_db, AsyncMock(), organizer, claim_id=1)

        assert result.status == CLAIM_STATUS_APPROVED
        send_mock.assert_awaited_once()
        args, kwargs = send_mock.call_args
        assert args == (organizer.email, "Jazz Night", "", organizer.locale)
        assert "http_client" in kwargs


class TestClaimStatusFromClaim:
    def test_none_is_unclaimed(self):
        assert claim_status_from_claim(None) == CLAIM_DISCOVERY_STATUS_UNCLAIMED

    def test_approved_is_claimed(self):
        assert (
            claim_status_from_claim(_fake_claim(status=CLAIM_STATUS_APPROVED))
            == CLAIM_DISCOVERY_STATUS_CLAIMED
        )

    def test_pending_is_pending(self):
        assert (
            claim_status_from_claim(_fake_claim(status=CLAIM_STATUS_PENDING))
            == CLAIM_DISCOVERY_STATUS_PENDING
        )


class TestResolveClaimForEvent:
    @pytest.mark.asyncio
    async def test_no_event_source_returns_none(self, mock_db, make_event):
        mock_db.scalar = AsyncMock(return_value=None)

        assert await resolve_claim_for_event(mock_db, make_event()) is None

    @pytest.mark.asyncio
    async def test_returns_active_claim_for_resolved_target(self, mock_db, make_event):
        claim = _fake_claim(status=CLAIM_STATUS_APPROVED)
        mock_db.scalar = AsyncMock(side_effect=[_fake_event_source(publisher_id=99), claim])

        assert await resolve_claim_for_event(mock_db, make_event()) is claim


class TestClaimingOrganizerName:
    @pytest.mark.asyncio
    async def test_none_claim_returns_none(self):
        assert await claiming_organizer_name(None) is None

    @pytest.mark.asyncio
    async def test_pending_claim_returns_none(self, make_organizer):
        claim = _fake_claim(status=CLAIM_STATUS_PENDING, organizer=make_organizer(name="Tallinn Jazz Club"))

        assert await claiming_organizer_name(claim) is None

    @pytest.mark.asyncio
    async def test_approved_claim_with_no_organizer_name_returns_none(self, make_organizer):
        claim = _fake_claim(status=CLAIM_STATUS_APPROVED, organizer=make_organizer(organizer_id=5))

        assert await claiming_organizer_name(claim) is None

    @pytest.mark.asyncio
    async def test_approved_claim_with_organizer_name_returns_it(self, make_organizer):
        claim = _fake_claim(
            status=CLAIM_STATUS_APPROVED,
            organizer=make_organizer(organizer_id=5, name="Tallinn Jazz Club"),
        )

        assert await claiming_organizer_name(claim) == "Tallinn Jazz Club"


class TestExpireStaleClaims:
    @pytest.mark.asyncio
    async def test_returns_expired_count(self, mock_db):
        expired_claims = [
            MagicMock(id=i, organizer_id=100 + i, kind=CLAIM_KIND_SERIES, publisher_id=None)
            for i in (1, 2, 3)
        ]
        execute_result = MagicMock()
        execute_result.scalars.return_value = MagicMock(all=MagicMock(return_value=expired_claims))
        mock_db.execute.return_value = execute_result
        # _send_claim_expiry_emails' organizer bulk-load — no matching
        # organizers, so it sends nothing (each row's send is a no-op skip).
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))

        summary = await expire_stale_claims(mock_db)

        assert summary == {"expired": 3}
        mock_db.execute.assert_awaited_once()
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sends_one_expiry_email_per_row(self, mock_db, make_organizer):
        """#421: each expired row notifies its organizer — bulk-loaded, not
        a per-row SELECT. A Series-kind claim (no publisher_id) never
        triggers the EventSource bulk-load, so mock_db.scalars is called
        just once here, for the organizer lookup."""
        claim = MagicMock(
            id=1, organizer_id=5, kind=CLAIM_KIND_SERIES, publisher_id=None
        )
        execute_result = MagicMock()
        execute_result.scalars.return_value = MagicMock(all=MagicMock(return_value=[claim]))
        mock_db.execute.return_value = execute_result

        organizer = make_organizer(organizer_id=5)
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[organizer]))

        with patch(
            "app.claims.lifecycle.send_claim_expired_email", new_callable=AsyncMock
        ) as send_mock:
            summary = await expire_stale_claims(mock_db)

        assert summary == {"expired": 1}
        send_mock.assert_awaited_once()
        args, kwargs = send_mock.call_args
        assert args == (organizer.email, None, organizer.locale)
        assert "http_client" in kwargs

    @pytest.mark.asyncio
    async def test_publisher_kind_expiry_resolves_event_title(self, mock_db, make_organizer, make_event):
        """A Publisher-kind expired claim's email gets a real event title,
        bulk-resolved via EventSource/Event (mirrors admin_list_claims'
        publisher-event bulk-load) rather than a per-row lookup."""
        claim = MagicMock(id=1, organizer_id=5, kind=CLAIM_KIND_PUBLISHER, publisher_id=99)
        execute_result = MagicMock()
        execute_result.scalars.return_value = MagicMock(all=MagicMock(return_value=[claim]))
        mock_db.execute.return_value = execute_result

        organizer = make_organizer(organizer_id=5)
        es = _fake_event_source(publisher_id=99)
        es.event_id = 42
        event = make_event(event_id=42)
        event.title_orig = "Jazz Night"
        mock_db.scalars = AsyncMock(
            side_effect=[
                MagicMock(all=MagicMock(return_value=[organizer])),
                MagicMock(all=MagicMock(return_value=[es])),
                MagicMock(all=MagicMock(return_value=[event])),
            ]
        )

        with patch(
            "app.claims.lifecycle.send_claim_expired_email", new_callable=AsyncMock
        ) as send_mock:
            summary = await expire_stale_claims(mock_db)

        assert summary == {"expired": 1}
        send_mock.assert_awaited_once()
        args, _kwargs = send_mock.call_args
        assert args == (organizer.email, "Jazz Night", organizer.locale)
