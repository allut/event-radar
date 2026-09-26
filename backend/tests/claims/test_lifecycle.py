"""Tests for app/claims/lifecycle.py (#413) — create/cancel/recheck/expire,
wired to #412's verification engine via mocked db + httpx client."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from sqlalchemy.exc import IntegrityError

from app.claims.lifecycle import (
    ClaimError,
    bulk_dormant_pinned_event_ids,
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
    CLAIM_ADMIN_REVIEW_EXPIRY_DAYS,
    CLAIM_DISCOVERY_STATUS_CLAIMED,
    CLAIM_DISCOVERY_STATUS_PENDING,
    CLAIM_DISCOVERY_STATUS_UNCLAIMED,
    CLAIM_EXPIRY_DAYS,
    CLAIM_KIND_PUBLISHER,
    CLAIM_KIND_SERIES,
    CLAIM_STATUS_APPROVED,
    CLAIM_STATUS_CANCELLED,
    CLAIM_STATUS_PENDING,
    CLAIM_STATUS_REVOKED,
    CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW,
    CLAIM_VERIFICATION_MECHANISM_DNS_TXT,
    CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN,
    CLAIM_VERIFICATION_OUTCOME_ADMIN_REVIEW,
    CLAIM_VERIFICATION_OUTCOME_AUTO_GRANT,
    ERROR_CLAIM_OWN_SUBMISSION,
    ERROR_CLAIM_TARGET_ALREADY_APPROVED,
    ERROR_EVENT_NOT_FOUND,
    KUMU_VERIFICATION_DOMAIN,
    ORGANIZER_DAILY_CLAIM_CAP,
    SOURCE_SLUG_FIENTA,
    SOURCE_SLUG_KUMU,
    SOURCE_SLUG_PILETILEVI,
)
from app.routers.utils import event_series_key, serialize_event_series_key


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
    async def test_draft_event_rejected_404(self, mock_db, make_organizer, make_event):
        mock_db.scalar.return_value = 0
        mock_db.get.return_value = make_event(status="draft")
        organizer = make_organizer(organizer_id=5)

        with pytest.raises(ClaimError) as exc:
            await create_claim(mock_db, AsyncMock(), organizer, event_id=10)

        assert exc.value.status_code == 404
        assert exc.value.detail == ERROR_EVENT_NOT_FOUND

    @pytest.mark.asyncio
    async def test_cancelled_event_rejected_404(self, mock_db, make_organizer, make_event):
        mock_db.scalar.return_value = 0
        mock_db.get.return_value = make_event(status="cancelled")
        organizer = make_organizer(organizer_id=5)

        with pytest.raises(ClaimError) as exc:
            await create_claim(mock_db, AsyncMock(), organizer, event_id=10)

        assert exc.value.status_code == 404
        assert exc.value.detail == ERROR_EVENT_NOT_FOUND

    @pytest.mark.asyncio
    async def test_non_canonical_duplicate_rejected_404(self, mock_db, make_organizer, make_event):
        mock_db.scalar.return_value = 0
        event = make_event(event_id=10)
        event.dedup_group_id = 999  # canonical representative is a different row
        mock_db.get.return_value = event
        organizer = make_organizer(organizer_id=5)

        with pytest.raises(ClaimError) as exc:
            await create_claim(mock_db, AsyncMock(), organizer, event_id=10)

        assert exc.value.status_code == 404
        assert exc.value.detail == ERROR_EVENT_NOT_FOUND

    @pytest.mark.asyncio
    async def test_canonical_representative_not_rejected(
        self, mock_db, make_organizer, make_event
    ):
        mock_db.scalar = AsyncMock(side_effect=[0, None])
        event = make_event(event_id=10)
        event.dedup_group_id = 10  # own group's representative — still canonical
        mock_db.get.return_value = event
        organizer = make_organizer(organizer_id=5)

        with pytest.raises(ClaimError) as exc:
            await create_claim(mock_db, AsyncMock(), organizer, event_id=10)

        # Passes the published/canonical gate and falls through to the
        # (unrelated) no-resolvable-source check, not the 404 gate.
        assert exc.value.status_code == 422

    @pytest.mark.asyncio
    async def test_explicit_event_rejected_404(self, mock_db, make_organizer, make_event):
        mock_db.scalar.return_value = 0
        event = make_event()
        event.is_explicit = True
        mock_db.get.return_value = event
        organizer = make_organizer(organizer_id=5)

        with pytest.raises(ClaimError) as exc:
            await create_claim(mock_db, AsyncMock(), organizer, event_id=10)

        assert exc.value.status_code == 404
        assert exc.value.detail == ERROR_EVENT_NOT_FOUND

    @pytest.mark.asyncio
    async def test_own_submission_rejected_422(self, mock_db, make_organizer, make_event):
        mock_db.scalar.return_value = 0
        mock_db.get.return_value = make_event(submitted_by_organizer_id=5)
        organizer = make_organizer(organizer_id=5)

        with pytest.raises(ClaimError) as exc:
            await create_claim(mock_db, AsyncMock(), organizer, event_id=10)

        assert exc.value.status_code == 422
        assert exc.value.detail == ERROR_CLAIM_OWN_SUBMISSION

    @pytest.mark.asyncio
    async def test_ended_event_still_claimable(self, mock_db, make_organizer, make_event):
        """An already-ended Publisher/Series target stays claimable — the
        claim covers future re-matched occurrences too (#429)."""
        es = _fake_event_source(publisher_id=99)
        mock_db.scalar = AsyncMock(side_effect=[0, es, None])
        event = make_event(starts_at=datetime(2020, 1, 1, 18, 0, 0, tzinfo=timezone.utc))
        mock_db.get.return_value = event
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

    @pytest.mark.asyncio
    async def test_fienta_publisher_claim_auto_grants(self, mock_db, make_organizer, make_event):
        es = _fake_event_source(publisher_id=99)
        mock_db.scalar = AsyncMock(side_effect=[0, es, None])
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
        institutional_publisher = MagicMock(id=99)
        mock_db.scalar = AsyncMock(side_effect=[0, es, institutional_publisher, None])
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
    async def test_series_claim_with_justification_stays_pending_admin_review(
        self, mock_db, make_organizer, make_event
    ):
        """A Piletilevi event whose promoter identity fails to resolve at
        all (event-page fetch error here) is the one case that still yields
        a Series target (#427). #428: a Series claim always stays
        admin-review — there is no auto-grant path for it — but a non-blank
        justification lets it through creation at all."""
        es = _fake_event_source(publisher_id=None, source_slug=SOURCE_SLUG_PILETILEVI)
        mock_db.scalar = AsyncMock(side_effect=[0, es, None])
        mock_db.get.return_value = make_event()
        organizer = make_organizer(organizer_id=5)

        with patch(
            "app.claims.target_resolution.http_get",
            new_callable=AsyncMock,
            side_effect=httpx.HTTPError("boom"),
        ):
            claim = await create_claim(
                mock_db, AsyncMock(), organizer, event_id=10, justification="I run this series."
            )

        assert claim.kind == CLAIM_KIND_SERIES
        assert claim.event_series_key is not None
        assert claim.status == CLAIM_STATUS_PENDING
        assert claim.verification_mechanism == CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW
        assert claim.justification == "I run this series."

    @pytest.mark.asyncio
    async def test_series_claim_without_justification_rejected(
        self, mock_db, make_organizer, make_event
    ):
        es = _fake_event_source(publisher_id=None, source_slug=SOURCE_SLUG_PILETILEVI)
        mock_db.scalar = AsyncMock(side_effect=[0, es, None])
        mock_db.get.return_value = make_event()
        organizer = make_organizer(organizer_id=5)

        with patch(
            "app.claims.target_resolution.http_get",
            new_callable=AsyncMock,
            side_effect=httpx.HTTPError("boom"),
        ):
            with pytest.raises(ClaimError) as exc:
                await create_claim(mock_db, AsyncMock(), organizer, event_id=10, justification="   ")

        assert exc.value.status_code == 422
        mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_series_claim_never_auto_grants_regardless_of_prior_approved_claims(
        self, mock_db, make_organizer, make_event
    ):
        """Regression guard (#428 acceptance criteria): a prior approved claim
        of any kind must never auto-grant an unrelated Series claim — the
        Trusted-claimant fast-track is deleted, not gated off, so there is no
        code path left that could even consult the organizer's other claims."""
        es = _fake_event_source(publisher_id=None, source_slug=SOURCE_SLUG_PILETILEVI)
        mock_db.scalar = AsyncMock(side_effect=[0, es, None])
        mock_db.get.return_value = make_event()
        organizer = make_organizer(organizer_id=5)

        with patch(
            "app.claims.target_resolution.http_get",
            new_callable=AsyncMock,
            side_effect=httpx.HTTPError("boom"),
        ):
            claim = await create_claim(
                mock_db, AsyncMock(), organizer, event_id=10, justification="justification"
            )

        assert claim.status == CLAIM_STATUS_PENDING
        mock_db.scalars.assert_not_called()

    @pytest.mark.asyncio
    async def test_auto_grant_sends_claim_granted_email(self, mock_db, make_organizer, make_event):
        """#421: create_claim's inline auto-grant path notifies the claimant
        immediately — no admin note, so the email falls back to its default
        copy (empty string in, fallback_note used)."""
        es = _fake_event_source(publisher_id=99)
        mock_db.scalar = AsyncMock(side_effect=[0, es, None])
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
    async def test_piletilevi_auto_grant_reuses_target_resolutions_event_fetch(
        self, mock_db, make_organizer, make_event
    ):
        """(#439) resolve_claim_target_live already fetches event.url once to
        resolve the promoter identity; verification must reuse that HTML
        rather than fetching event.url a second time."""
        from app.claims.piletilevi_promoter import PromoterContact, PromoterIdentity

        es = _fake_event_source(publisher_id=None, source_slug=SOURCE_SLUG_PILETILEVI)
        mock_db.scalar = AsyncMock(side_effect=[0, es, None])
        event = make_event()
        event.url = "https://www.piletilevi.ee/en/tickets/x/some-event"
        mock_db.get.return_value = event
        organizer = make_organizer(organizer_id=5)
        publisher = MagicMock(id=33)
        identity = PromoterIdentity(
            external_id="https://www.piletilevi.ee/en/promoters/1/x", name="X OÜ"
        )

        with (
            patch(
                "app.claims.target_resolution.http_get",
                new_callable=AsyncMock,
                return_value=MagicMock(text="<html>event page</html>"),
            ) as target_http_get,
            patch(
                "app.claims.target_resolution.resolve_promoter_identity",
                return_value=identity,
            ),
            patch(
                "app.claims.target_resolution._get_or_create_publisher",
                new_callable=AsyncMock,
                return_value=publisher,
            ),
            patch("app.claims.lifecycle.http_get", new_callable=AsyncMock) as lifecycle_http_get,
            patch(
                "app.claims.verification.resolve_promoter_contact",
                new_callable=AsyncMock,
                return_value=PromoterContact(domain="own-domain.ee", email=None),
            ) as resolve_contact,
            patch(
                "app.claims.verification.verify_dns_txt_token",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            claim = await create_claim(mock_db, AsyncMock(), organizer, event_id=10)

        assert target_http_get.await_count == 1
        lifecycle_http_get.assert_not_awaited()
        resolve_contact.assert_awaited_once()
        # The reused HTML, not a re-fetch, is what verification saw.
        assert resolve_contact.call_args[0][1] == "<html>event page</html>"
        assert claim.status == CLAIM_STATUS_APPROVED

    @pytest.mark.asyncio
    async def test_pending_admin_review_sends_no_email(self, mock_db, make_organizer, make_event):
        """A claim that stays pending (routed to admin review) must not send
        the granted email — only an actual grant does."""
        es = _fake_event_source(publisher_id=None, source_slug=SOURCE_SLUG_PILETILEVI)
        mock_db.scalar = AsyncMock(side_effect=[0, es, None])
        mock_db.get.return_value = make_event()
        organizer = make_organizer(organizer_id=5)

        with (
            patch(
                "app.claims.target_resolution.http_get",
                new_callable=AsyncMock,
                side_effect=httpx.HTTPError("boom"),
            ),
            patch(
                "app.claims.lifecycle.send_claim_granted_email", new_callable=AsyncMock
            ) as send_mock,
        ):
            await create_claim(
                mock_db, AsyncMock(), organizer, event_id=10, justification="justification"
            )

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


class TestContestedClaims:
    """(#431, slice 1 of #425): pending claims coexisting on one target,
    proof-preempts-assertion auto-decline, and the approved-target conflict."""

    @pytest.mark.asyncio
    async def test_second_pending_claim_on_same_target_succeeds(
        self, mock_db, make_organizer, make_event
    ):
        """A target with an existing *pending* claim no longer blocks a
        second claim attempt (only the narrower approved-only unique index
        still applies) — this one falls back to admin review, its own
        independent proof token already set on the Claim constructor."""
        es = _fake_event_source(publisher_id=99, source_slug=SOURCE_SLUG_KUMU)
        mock_db.scalar = AsyncMock(side_effect=[0, es, MagicMock(id=99), None])
        mock_db.get.return_value = make_event()
        organizer = make_organizer(organizer_id=5)

        with patch(
            "app.claims.lifecycle.verify_institutional_publisher_claim",
            new_callable=AsyncMock,
            return_value=VerificationResult(
                CLAIM_VERIFICATION_MECHANISM_DNS_TXT, CLAIM_VERIFICATION_OUTCOME_ADMIN_REVIEW
            ),
        ):
            claim = await create_claim(mock_db, AsyncMock(), organizer, event_id=10)

        assert claim.status == CLAIM_STATUS_PENDING
        assert claim.proof_token
        mock_db.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_target_with_approved_claim_rejected_with_409(
        self, mock_db, make_organizer, make_event
    ):
        es = _fake_event_source(publisher_id=99)
        mock_db.scalar = AsyncMock(side_effect=[0, es, MagicMock(id=1)])
        mock_db.get.return_value = make_event()
        organizer = make_organizer(organizer_id=5)

        with pytest.raises(ClaimError) as exc:
            await create_claim(mock_db, AsyncMock(), organizer, event_id=10)

        assert exc.value.status_code == 409
        assert exc.value.detail == ERROR_CLAIM_TARGET_ALREADY_APPROVED
        mock_db.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_commit_race_against_newly_approved_claim_rejected_with_409(
        self, mock_db, make_organizer, make_event
    ):
        """The pre-insert approved-claim check (previous test) can't close
        every race — another claim on the same target could auto-grant
        between that check and this claim's own commit. The commit itself is
        still guarded by the narrowed unique index, and that IntegrityError
        maps onto the same support-facing conflict."""
        es = _fake_event_source(publisher_id=99)
        mock_db.scalar = AsyncMock(side_effect=[0, es, None])
        mock_db.get.return_value = make_event()
        organizer = make_organizer(organizer_id=5)
        mock_db.commit = AsyncMock(
            side_effect=IntegrityError("stmt", "params", Exception("dup"))
        )

        with patch(
            "app.claims.lifecycle.verify_fienta_publisher_claim",
            new_callable=AsyncMock,
            return_value=VerificationResult(
                CLAIM_VERIFICATION_MECHANISM_FIENTA_TOKEN, CLAIM_VERIFICATION_OUTCOME_AUTO_GRANT
            ),
        ):
            with pytest.raises(ClaimError) as exc:
                await create_claim(mock_db, AsyncMock(), organizer, event_id=10)

        assert exc.value.status_code == 409
        assert exc.value.detail == ERROR_CLAIM_TARGET_ALREADY_APPROVED
        mock_db.rollback.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_auto_grant_declines_other_pending_claims_and_notifies_them(
        self, mock_db, make_organizer, make_event
    ):
        es = _fake_event_source(publisher_id=99)
        mock_db.scalar = AsyncMock(side_effect=[0, es, None])
        event = make_event()
        event.title_orig = "Jazz Night"
        mock_db.get.return_value = event
        organizer = make_organizer(organizer_id=5)

        other_organizer = make_organizer(organizer_id=6)
        other_organizer.email = "other@example.com"
        loser = _fake_claim(
            id=2,
            organizer_id=6,
            status=CLAIM_STATUS_PENDING,
            organizer=other_organizer,
        )
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[loser]))
        loser_event = make_event()
        loser_event.title_orig = "Jazz Night (loser's own listing)"

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
                "app.claims.pinning.representative_event_for_claim",
                new_callable=AsyncMock,
                return_value=loser_event,
            ) as representative_event_mock,
            patch(
                "app.claims.lifecycle.send_claim_declined_email", new_callable=AsyncMock
            ) as decline_mock,
        ):
            claim = await create_claim(mock_db, AsyncMock(), organizer, event_id=10)

        assert claim.status == CLAIM_STATUS_APPROVED
        assert loser.status == CLAIM_STATUS_REVOKED
        assert loser.resolved_at is not None
        # Each declined claim resolves its own representative event, not the
        # winning claim's — asserted by using a distinct title for it above.
        representative_event_mock.assert_awaited_once_with(mock_db, loser)
        decline_mock.assert_awaited_once()
        args, kwargs = decline_mock.call_args
        assert args == (
            other_organizer.email,
            "Jazz Night (loser's own listing)",
            "",
            other_organizer.locale,
        )
        assert "http_client" in kwargs

    @pytest.mark.asyncio
    async def test_auto_grant_with_no_other_pending_claims_sends_no_decline_email(
        self, mock_db, make_organizer, make_event
    ):
        es = _fake_event_source(publisher_id=99)
        mock_db.scalar = AsyncMock(side_effect=[0, es, None])
        mock_db.get.return_value = make_event()
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
                "app.claims.lifecycle.send_claim_declined_email", new_callable=AsyncMock
            ) as decline_mock,
        ):
            claim = await create_claim(mock_db, AsyncMock(), organizer, event_id=10)

        assert claim.status == CLAIM_STATUS_APPROVED
        decline_mock.assert_not_awaited()


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
    async def test_expiry_email_reports_the_window_that_actually_fired(
        self, mock_db, make_organizer
    ):
        """#430: an automated-mechanism claim's expiry email states
        CLAIM_EXPIRY_DAYS; an admin_review (or piletilevi_mailbox) one states
        CLAIM_ADMIN_REVIEW_EXPIRY_DAYS instead — never the shorter automated
        figure, which would misstate how long the claim actually sat."""
        automated_claim = MagicMock(
            id=1,
            organizer_id=5,
            kind=CLAIM_KIND_PUBLISHER,
            publisher_id=None,
            verification_mechanism=CLAIM_VERIFICATION_MECHANISM_DNS_TXT,
        )
        admin_review_claim = MagicMock(
            id=2,
            organizer_id=6,
            kind=CLAIM_KIND_SERIES,
            publisher_id=None,
            verification_mechanism=CLAIM_VERIFICATION_MECHANISM_ADMIN_REVIEW,
        )
        execute_result = MagicMock()
        execute_result.scalars.return_value = MagicMock(
            all=MagicMock(return_value=[automated_claim, admin_review_claim])
        )
        mock_db.execute.return_value = execute_result

        organizer_5 = make_organizer(organizer_id=5)
        organizer_6 = make_organizer(organizer_id=6)
        mock_db.scalars.return_value = MagicMock(
            all=MagicMock(return_value=[organizer_5, organizer_6])
        )

        organizer_5.email = "organizer-5@example.com"
        organizer_6.email = "organizer-6@example.com"

        with patch(
            "app.claims.lifecycle.send_claim_expired_email", new_callable=AsyncMock
        ) as send_mock:
            await expire_stale_claims(mock_db)

        days_by_organizer = {
            call.args[0]: call.kwargs["days"] for call in send_mock.await_args_list
        }
        assert days_by_organizer[organizer_5.email] == CLAIM_EXPIRY_DAYS
        assert days_by_organizer[organizer_6.email] == CLAIM_ADMIN_REVIEW_EXPIRY_DAYS

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

    @pytest.mark.asyncio
    async def test_selects_distinct_cutoff_per_mechanism_group(self, mock_db):
        """#430: an automated-mechanism claim (Fienta token/DNS-TXT/Piletilevi
        promoter) is swept against the CLAIM_EXPIRY_DAYS cutoff; everything
        else (admin_review, piletilevi_mailbox) is swept against the longer
        CLAIM_ADMIN_REVIEW_EXPIRY_DAYS cutoff — one UPDATE, two OR-ed
        mechanism/cutoff branches. Asserted against the compiled statement
        rather than row outcomes, since mock_db never runs real SQL."""
        execute_result = MagicMock()
        execute_result.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
        mock_db.execute.return_value = execute_result
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))

        before = datetime.now(timezone.utc)
        await expire_stale_claims(mock_db)
        after = datetime.now(timezone.utc)

        statement = mock_db.execute.call_args.args[0]
        sql = str(statement.compile())
        params = statement.compile().params

        assert "claims.verification_mechanism IN" in sql
        assert "claims.verification_mechanism NOT IN" in sql

        automated_cutoff = params["last_checked_at_1"]
        admin_review_cutoff = params["last_checked_at_2"]
        assert automated_cutoff > admin_review_cutoff

        expected_automated = before - timedelta(days=CLAIM_EXPIRY_DAYS)
        expected_admin_review = before - timedelta(days=CLAIM_ADMIN_REVIEW_EXPIRY_DAYS)
        tolerance = after - before + timedelta(seconds=1)
        assert abs(automated_cutoff - expected_automated) <= tolerance
        assert abs(admin_review_cutoff - expected_admin_review) <= tolerance


class TestBulkDormantPinnedEventIds:
    """#422: pinned_fields must not keep applying once the covering claim
    is dormant — batched over many events (refetch_event_details), fixed
    query count."""

    @pytest.mark.asyncio
    async def test_no_pinned_events_short_circuits(self, mock_db, make_event):
        event = make_event(event_id=1)
        event.pinned_fields = []

        result = await bulk_dormant_pinned_event_ids(mock_db, [event])

        assert result == set()
        mock_db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_publisher_kind_dormant_claim_flagged(self, mock_db, make_event):
        event = make_event(event_id=42)
        event.pinned_fields = ["title:et"]
        mock_db.execute.side_effect = [
            MagicMock(all=MagicMock(return_value=[(42, 99)])),  # EventSource rows
            MagicMock(all=MagicMock(return_value=[(99,)])),  # dormant publisher_ids
        ]

        result = await bulk_dormant_pinned_event_ids(mock_db, [event])

        assert result == {42}

    @pytest.mark.asyncio
    async def test_publisher_kind_active_claim_not_flagged(self, mock_db, make_event):
        event = make_event(event_id=42)
        event.pinned_fields = ["title:et"]
        mock_db.execute.side_effect = [
            MagicMock(all=MagicMock(return_value=[(42, 99)])),  # EventSource rows
            MagicMock(all=MagicMock(return_value=[])),  # no dormant publishers
        ]

        result = await bulk_dormant_pinned_event_ids(mock_db, [event])

        assert result == set()

    @pytest.mark.asyncio
    async def test_series_kind_dormant_claim_flagged(self, mock_db, make_event):
        event = make_event(event_id=7, venue_name="Kumu")
        event.title_orig = "Jazz Night"
        event.pinned_fields = ["title:et"]
        key = serialize_event_series_key(event_series_key("Jazz Night", "Kumu"))
        mock_db.execute.side_effect = [
            MagicMock(all=MagicMock(return_value=[(7, None)])),  # EventSource rows
            MagicMock(all=MagicMock(return_value=[(key,)])),  # dormant series keys
        ]

        result = await bulk_dormant_pinned_event_ids(mock_db, [event])

        assert result == {7}

    @pytest.mark.asyncio
    async def test_no_event_source_row_never_dormant(self, mock_db, make_event):
        """An organizer's own direct submission (no EventSource row) has no
        claim to go dormant — its pin always keeps applying."""
        event = make_event(event_id=5)
        event.pinned_fields = ["title:et"]
        mock_db.execute.side_effect = [
            MagicMock(all=MagicMock(return_value=[])),  # no EventSource rows
        ]

        result = await bulk_dormant_pinned_event_ids(mock_db, [event])

        assert result == set()
