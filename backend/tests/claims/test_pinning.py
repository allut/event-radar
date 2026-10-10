"""Tests for app/claims/pinning.py (#416): pin/unpin bookkeeping, the
representative-event lookup for both claim kinds, the price-mismatch diff,
and (#438) the daily claim-edit cap's covered-event-count scaling."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.claims.pinning import (
    FreshPrice,
    apply_pins,
    claim_event_for_id,
    clear_claim_pins,
    fetch_fresh_price,
    organizer_covered_event_count,
    pin_key,
    price_mismatch,
    representative_event_for_claim,
    scaled_claim_edit_cap,
)
from app.constants import (
    CLAIM_KIND_PUBLISHER,
    CLAIM_KIND_SERIES,
    ORGANIZER_CLAIM_EDIT_CAP_CEILING,
    ORGANIZER_CLAIM_EDIT_CAP_PER_EVENT,
    ORGANIZER_DAILY_CLAIM_EDIT_CAP,
)


class TestPinKey:
    def test_plain_field(self):
        assert pin_key("image_url") == "image_url"

    def test_locale_field(self):
        assert pin_key("title", "et") == "title:et"


class TestApplyPins:
    def test_pin_adds_to_existing(self):
        result = apply_pins(["url"], pin={"title:et"}, unpin=set())
        assert set(result) == {"url", "title:et"}

    def test_unpin_removes(self):
        result = apply_pins(["url", "title:et"], pin=set(), unpin={"url"})
        assert result == ["title:et"]

    def test_locale_pins_independent(self):
        # Editing the Estonian title pins only "title:et" — Russian/English
        # stay whatever they were.
        result = apply_pins(["title:ru"], pin={"title:et"}, unpin=set())
        assert set(result) == {"title:ru", "title:et"}

    def test_edit_wins_over_unpin_of_same_key(self):
        result = apply_pins(["title:et"], pin={"title:et"}, unpin={"title:et"})
        assert result == ["title:et"]

    def test_unpin_of_absent_key_is_a_noop(self):
        result = apply_pins([], pin=set(), unpin={"url"})
        assert result == []


class TestPriceMismatch:
    def test_no_fresh_read_is_no_mismatch(self, make_event):
        event = make_event()
        assert price_mismatch(event, None) is None

    def test_matching_fresh_price_is_no_mismatch(self, make_event):
        event = make_event(price_min=10.0)
        event.currency = "EUR"
        event.has_free_tier = False
        fresh = FreshPrice(price_min=10.0, price_max=None, currency="EUR", has_free_tier=False)
        assert price_mismatch(event, fresh) is None

    def test_differing_price_min_is_a_mismatch(self, make_event):
        event = make_event(price_min=10.0)
        fresh = FreshPrice(price_min=15.0, price_max=None, currency=None, has_free_tier=False)
        result = price_mismatch(event, fresh)
        assert result == {
            "price_min": 15.0,
            "price_max": None,
            "currency": None,
            "has_free_tier": False,
        }

    def test_within_tolerance_is_no_mismatch(self, make_event):
        event = make_event(price_min=10.0)
        fresh = FreshPrice(price_min=10.001, price_max=None, currency=None, has_free_tier=False)
        assert price_mismatch(event, fresh) is None

    def test_newly_free_is_a_mismatch(self, make_event):
        event = make_event()
        event.has_free_tier = False
        fresh = FreshPrice(price_min=None, price_max=None, currency=None, has_free_tier=True)
        assert price_mismatch(event, fresh) is not None


class TestFetchFreshPrice:
    @pytest.mark.asyncio
    async def test_no_url_returns_none(self, make_event):
        event = make_event()
        event.url = None
        client = AsyncMock()
        assert await fetch_fresh_price(client, event) is None

    @pytest.mark.asyncio
    async def test_fetch_failure_returns_none(self, make_event):
        event = make_event()
        client = AsyncMock()
        with patch(
            "app.claims.pinning.http_get_stored_url",
            new_callable=AsyncMock,
            side_effect=httpx.RequestError("boom"),
        ):
            assert await fetch_fresh_price(client, event) is None

    @pytest.mark.asyncio
    async def test_ssrf_guard_refusal_returns_none(self, make_event):
        event = make_event()
        event.url = "https://127.0.0.1.attacker.example/e/1"
        client = AsyncMock()
        # Real guard, no http_get_stored_url patch: a non-allowlisted host is
        # refused before any request is made.
        assert await fetch_fresh_price(client, event) is None
        client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_offers_in_page_returns_none(self, make_event):
        event = make_event()
        response = MagicMock()
        response.text = "<html></html>"
        client = AsyncMock()
        with (
            patch("app.claims.pinning.http_get_stored_url", new_callable=AsyncMock, return_value=response),
            patch("app.claims.pinning.parse_jsonld_event_items", return_value=[]),
            patch(
                "app.claims.pinning.offers_from_jsonld_items",
                return_value=(None, None, None, False),
            ),
        ):
            assert await fetch_fresh_price(client, event) is None

    @pytest.mark.asyncio
    async def test_parses_offers_into_fresh_price(self, make_event):
        event = make_event()
        response = MagicMock()
        response.text = "<html></html>"
        client = AsyncMock()
        with (
            patch("app.claims.pinning.http_get_stored_url", new_callable=AsyncMock, return_value=response),
            patch("app.claims.pinning.parse_jsonld_event_items", return_value=[{}]),
            patch(
                "app.claims.pinning.offers_from_jsonld_items",
                return_value=(12.0, 18.0, "EUR", False),
            ),
        ):
            fresh = await fetch_fresh_price(client, event)
        assert fresh == FreshPrice(12.0, 18.0, "EUR", False)

    @pytest.mark.asyncio
    async def test_kumu_falls_back_to_selector_price_when_no_jsonld_offers(self, make_event):
        """KUMU pages (#424) carry no Event/offers JSON-LD — falls back to
        the same selector-based price hint refetch.py uses."""
        event = make_event()
        event.url = "https://kumu.ekm.ee/en/syndmus/some-event/"
        response = MagicMock()
        response.text = (
            "<html><body>"
            '<div class="event-header__ticket-price">&euro;16</div>'
            "</body></html>"
        )
        client = AsyncMock()
        with (
            patch("app.claims.pinning.http_get_stored_url", new_callable=AsyncMock, return_value=response),
            patch("app.claims.pinning.parse_jsonld_event_items", return_value=[]),
            patch(
                "app.claims.pinning.offers_from_jsonld_items",
                return_value=(None, None, None, False),
            ),
        ):
            fresh = await fetch_fresh_price(client, event)
        assert fresh == FreshPrice(16.0, 16.0, "EUR", False)


class TestRepresentativeEventForClaim:
    @pytest.mark.asyncio
    async def test_publisher_claim_uses_representative_event_source(self, mock_db, make_event):
        claim = MagicMock(kind=CLAIM_KIND_PUBLISHER, publisher_id=7)
        es = MagicMock(event_id=42)
        event = make_event(event_id=42)
        mock_db.scalar.return_value = event
        with patch(
            "app.claims.pinning.representative_event_source",
            new_callable=AsyncMock,
            return_value=es,
        ):
            result = await representative_event_for_claim(mock_db, claim)
        assert result is event

    @pytest.mark.asyncio
    async def test_publisher_claim_with_no_event_source_returns_none(self, mock_db):
        claim = MagicMock(kind=CLAIM_KIND_PUBLISHER, publisher_id=7)
        with patch(
            "app.claims.pinning.representative_event_source",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await representative_event_for_claim(mock_db, claim)
        assert result is None

    @pytest.mark.asyncio
    async def test_series_claim_looks_up_by_indexed_key(self, mock_db, make_event):
        matching = make_event(event_id=1, title="Balti Jaama Turg", venue_name="Kultuurikatel")
        matching.series_key = "balti jaama turg\x1fkultuurikatel"
        claim = MagicMock(kind=CLAIM_KIND_SERIES, event_series_key=matching.series_key)

        execute_result = MagicMock()
        execute_result.scalars.return_value.all.return_value = [matching]
        mock_db.execute.return_value = execute_result

        result = await representative_event_for_claim(mock_db, claim)
        assert result is matching

    @pytest.mark.asyncio
    async def test_series_claim_no_match_returns_none(self, mock_db):
        claim = MagicMock(kind=CLAIM_KIND_SERIES, event_series_key="nope\x1fnope")

        execute_result = MagicMock()
        execute_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = execute_result

        result = await representative_event_for_claim(mock_db, claim)
        assert result is None


class TestClearClaimPins:
    """#442: revoking a claim must clear pinned_fields on every event the
    claim covers, not just representative_event_for_claim()'s pick."""

    @pytest.mark.asyncio
    async def test_publisher_claim_clears_every_covered_event(self, mock_db):
        claim = MagicMock(kind=CLAIM_KIND_PUBLISHER, publisher_id=7)
        scalars_result = MagicMock()
        scalars_result.all.return_value = [42, 43, 44]
        mock_db.scalars.return_value = scalars_result

        event_ids = await clear_claim_pins(mock_db, claim)

        assert event_ids == [42, 43, 44]
        mock_db.execute.assert_awaited_once()
        stmt = mock_db.execute.await_args.args[0]
        assert stmt.is_dml
        assert "events" in str(stmt).lower()

    @pytest.mark.asyncio
    async def test_publisher_claim_with_nothing_pinned_skips_update(self, mock_db):
        claim = MagicMock(kind=CLAIM_KIND_PUBLISHER, publisher_id=7)
        scalars_result = MagicMock()
        scalars_result.all.return_value = []
        mock_db.scalars.return_value = scalars_result

        event_ids = await clear_claim_pins(mock_db, claim)

        assert event_ids == []
        mock_db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_series_claim_clears_events_matching_indexed_key(self, mock_db):
        claim = MagicMock(kind=CLAIM_KIND_SERIES, event_series_key="a\x1fb")
        scalars_result = MagicMock()
        scalars_result.all.return_value = [1, 5]
        mock_db.scalars.return_value = scalars_result

        event_ids = await clear_claim_pins(mock_db, claim)

        assert event_ids == [1, 5]
        query = str(mock_db.scalars.await_args.args[0])
        assert "events.series_key =" in query
        # M-3: never clears another organizer's own submission.
        assert "submitted_by_organizer_id IS NULL" in query
        mock_db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_series_claim_no_match_skips_update(self, mock_db):
        claim = MagicMock(kind=CLAIM_KIND_SERIES, event_series_key="nope\x1fnope")
        scalars_result = MagicMock()
        scalars_result.all.return_value = []
        mock_db.scalars.return_value = scalars_result

        event_ids = await clear_claim_pins(mock_db, claim)

        assert event_ids == []
        mock_db.execute.assert_not_awaited()


class TestClaimEventForId:
    """#437: a Publisher claim given an explicit event_id re-derives claim
    coverage server-side instead of trusting the client-supplied pairing."""

    @pytest.mark.asyncio
    async def test_no_event_id_falls_back_to_representative_event(self, mock_db, make_event):
        claim = MagicMock(kind=CLAIM_KIND_PUBLISHER, publisher_id=7)
        event = make_event(event_id=1)
        with patch(
            "app.claims.pinning.representative_event_for_claim",
            new_callable=AsyncMock,
            return_value=event,
        ) as mocked:
            result = await claim_event_for_id(mock_db, claim, None)
        mocked.assert_awaited_once_with(mock_db, claim)
        assert result is event

    @pytest.mark.asyncio
    async def test_series_claim_event_id_must_match_representative(self, mock_db, make_event):
        """OWASP audit M-3: a Series claim has one resolvable event; a path/body
        id naming any other row resolves to None (404), never a silent swap."""
        claim = MagicMock(kind=CLAIM_KIND_SERIES, event_series_key="k")
        event = make_event(event_id=1)
        with patch(
            "app.claims.pinning.representative_event_for_claim",
            new_callable=AsyncMock,
            return_value=event,
        ) as mocked:
            assert await claim_event_for_id(mock_db, claim, 999) is None
            assert await claim_event_for_id(mock_db, claim, 1) is event
            assert await claim_event_for_id(mock_db, claim, None) is event
        assert mocked.await_count == 3

    @pytest.mark.asyncio
    async def test_publisher_claim_with_event_id_queries_membership(self, mock_db, make_event):
        claim = MagicMock(kind=CLAIM_KIND_PUBLISHER, publisher_id=7)
        event = make_event(event_id=42)
        mock_db.scalar = AsyncMock(return_value=event)
        result = await claim_event_for_id(mock_db, claim, 42)
        assert result is event
        mock_db.scalar.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_publisher_claim_with_uncovered_event_id_returns_none(self, mock_db):
        claim = MagicMock(kind=CLAIM_KIND_PUBLISHER, publisher_id=7)
        mock_db.scalar = AsyncMock(return_value=None)
        result = await claim_event_for_id(mock_db, claim, 999)
        assert result is None


def _execute_rows(rows):
    """A sync MagicMock whose `.all()` returns `rows` — stands in for the
    object `(await db.execute(...))` resolves to. Mirrors
    tests/routers/conftest.py's execute_rows(), kept local rather than
    imported cross-package since that helper's existing precedent is
    routers-test-module-only (grep the repo for `from tests.routers.conftest
    import` — every prior use lives inside tests/routers/ itself)."""
    r = MagicMock()
    r.all.return_value = rows
    return r


def _execute_scalar(value):
    """A sync MagicMock whose `.scalar()` returns `value` — stands in for
    the object `(await db.execute(...))` resolves to when the query is a
    scalar aggregate rather than a row set (see _execute_rows() for the
    row-set counterpart)."""
    r = MagicMock()
    r.scalar.return_value = value
    return r


def _claim_row(kind: str, publisher_id: int | None = None):
    return MagicMock(kind=kind, publisher_id=publisher_id)


class TestOrganizerCoveredEventCount:
    """#438: how many events the organizer's approved, non-dormant claim(s)
    cover — feeds the scaled daily claim-edit cap."""

    @pytest.mark.asyncio
    async def test_no_claims_is_zero(self, mock_db):
        mock_db.execute.side_effect = [_execute_rows([])]
        result = await organizer_covered_event_count(mock_db, 5)
        assert result == 0

    @pytest.mark.asyncio
    async def test_single_publisher_claim_uses_bulk_distinct_count(self, mock_db):
        mock_db.execute.side_effect = [
            _execute_rows([_claim_row(CLAIM_KIND_PUBLISHER, publisher_id=99)]),
            _execute_scalar(61),
        ]
        result = await organizer_covered_event_count(mock_db, 5)
        assert result == 61
        assert mock_db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_series_claim_counts_as_one(self, mock_db):
        """A Series claim has no FK to bulk-count against, so it counts as
        the single representative event the claim-editing surface actually
        exposes for it — no second query is issued."""
        mock_db.execute.side_effect = [
            _execute_rows([_claim_row(CLAIM_KIND_SERIES)]),
        ]
        result = await organizer_covered_event_count(mock_db, 5)
        assert result == 1
        assert mock_db.execute.await_count == 1

    @pytest.mark.asyncio
    async def test_multiple_publisher_claims_share_one_bulk_query(self, mock_db):
        mock_db.execute.side_effect = [
            _execute_rows(
                [
                    _claim_row(CLAIM_KIND_PUBLISHER, publisher_id=1),
                    _claim_row(CLAIM_KIND_PUBLISHER, publisher_id=2),
                ]
            ),
            _execute_scalar(75),
        ]
        result = await organizer_covered_event_count(mock_db, 5)
        assert result == 75
        assert mock_db.execute.await_count == 2

    @pytest.mark.asyncio
    async def test_publisher_and_series_claims_combine(self, mock_db):
        mock_db.execute.side_effect = [
            _execute_rows(
                [
                    _claim_row(CLAIM_KIND_PUBLISHER, publisher_id=1),
                    _claim_row(CLAIM_KIND_SERIES),
                ]
            ),
            _execute_scalar(10),
        ]
        result = await organizer_covered_event_count(mock_db, 5)
        assert result == 11


class TestScaledClaimEditCap:
    """#438: the daily claim-edit cap scales with covered-event count, with
    a single covered event landing exactly on the pre-existing flat
    baseline and a large claim bounded by the ceiling."""

    def test_single_event_matches_flat_baseline(self):
        assert scaled_claim_edit_cap(1) == ORGANIZER_DAILY_CLAIM_EDIT_CAP

    def test_zero_covered_events_matches_flat_baseline(self):
        # Shouldn't happen in practice (the request always resolves through
        # an approved claim covering at least one event), but treating it
        # the same as one keeps the function total.
        assert scaled_claim_edit_cap(0) == ORGANIZER_DAILY_CLAIM_EDIT_CAP

    def test_scales_past_flat_baseline_below_ceiling(self):
        covered = 10
        expected = ORGANIZER_DAILY_CLAIM_EDIT_CAP + (covered - 1) * ORGANIZER_CLAIM_EDIT_CAP_PER_EVENT
        assert ORGANIZER_DAILY_CLAIM_EDIT_CAP < expected < ORGANIZER_CLAIM_EDIT_CAP_CEILING
        assert scaled_claim_edit_cap(covered) == expected

    def test_large_claim_hits_ceiling(self):
        # Estonia Concert Hall's 61-event Publisher claim (#426) — well past
        # where the linear scale would exceed the ceiling.
        assert scaled_claim_edit_cap(61) == ORGANIZER_CLAIM_EDIT_CAP_CEILING

    def test_cap_never_exceeds_ceiling_for_very_large_claims(self):
        assert scaled_claim_edit_cap(10_000) == ORGANIZER_CLAIM_EDIT_CAP_CEILING


class TestBulkResolveSeriesEvents:
    @pytest.mark.asyncio
    async def test_empty_keys_issue_no_query(self, mock_db):
        from app.claims.pinning import bulk_resolve_series_events

        assert await bulk_resolve_series_events(mock_db, set()) == {}
        mock_db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_one_indexed_query_resolves_every_key_earliest_match_wins(
        self, mock_db, make_event
    ):
        from app.claims.pinning import bulk_resolve_series_events

        first_a = make_event(1, title="Market A", venue_name="Hall")
        later_a = make_event(2, title="Market A", venue_name="Hall")
        only_b = make_event(3, title="Market B", venue_name="Hall")
        first_a.series_key = later_a.series_key = "a\x1fhall"
        only_b.series_key = "b\x1fhall"

        scalars = MagicMock()
        scalars.all.return_value = [first_a, later_a, only_b]
        mock_db.execute.return_value.scalars.return_value = scalars

        result = await bulk_resolve_series_events(
            mock_db, {"a\x1fhall", "b\x1fhall", "ghost\x1fhall"}
        )

        assert result == {"a\x1fhall": first_a, "b\x1fhall": only_b}
        mock_db.execute.assert_awaited_once()
        query = str(mock_db.execute.await_args.args[0])
        assert "events.series_key IN" in query
        # M-3: cross-tenant guard.
        assert "submitted_by_organizer_id IS NULL" in query
        assert "events.status !=" in query


class TestTransitionPendingClaim:
    """OWASP audit L-11: the pending->X transition is a guarded UPDATE."""

    @pytest.mark.asyncio
    async def test_winner_gets_true_and_object_synced(self, mock_db):
        from datetime import datetime, timezone

        from app.claims.lifecycle import transition_pending_claim

        claim = MagicMock(id=4, status="pending")
        mock_db.execute.return_value = MagicMock(
            scalar_one_or_none=MagicMock(return_value=4)
        )
        now = datetime.now(timezone.utc)
        assert await transition_pending_claim(mock_db, claim, "approved", now) is True
        assert claim.status == "approved" and claim.resolved_at == now
        compiled = str(mock_db.execute.await_args.args[0])
        assert "claims.status =" in compiled and "RETURNING" in compiled

    @pytest.mark.asyncio
    async def test_loser_gets_false_and_object_untouched(self, mock_db):
        from datetime import datetime, timezone

        from app.claims.lifecycle import transition_pending_claim

        claim = MagicMock(id=4, status="pending")
        mock_db.execute.return_value = MagicMock(
            scalar_one_or_none=MagicMock(return_value=None)
        )
        assert (
            await transition_pending_claim(
                mock_db, claim, "revoked", datetime.now(timezone.utc)
            )
            is False
        )
        assert claim.status == "pending"
