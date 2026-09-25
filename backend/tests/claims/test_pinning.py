"""Tests for app/claims/pinning.py (#416): pin/unpin bookkeeping, the
representative-event lookup for both claim kinds, and the price-mismatch
diff."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.claims.pinning import (
    FreshPrice,
    apply_pins,
    fetch_fresh_price,
    pin_key,
    price_mismatch,
    representative_event_for_claim,
)
from app.constants import CLAIM_KIND_PUBLISHER, CLAIM_KIND_SERIES


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
            "app.claims.pinning.http_get",
            new_callable=AsyncMock,
            side_effect=httpx.RequestError("boom"),
        ):
            assert await fetch_fresh_price(client, event) is None

    @pytest.mark.asyncio
    async def test_no_offers_in_page_returns_none(self, make_event):
        event = make_event()
        response = MagicMock()
        response.text = "<html></html>"
        client = AsyncMock()
        with (
            patch("app.claims.pinning.http_get", new_callable=AsyncMock, return_value=response),
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
            patch("app.claims.pinning.http_get", new_callable=AsyncMock, return_value=response),
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
            patch("app.claims.pinning.http_get", new_callable=AsyncMock, return_value=response),
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
    async def test_series_claim_scans_for_matching_key(self, mock_db, make_event):
        from app.routers.utils import event_series_key, serialize_event_series_key

        matching = make_event(event_id=1, title="Balti Jaama Turg", venue_name="Kultuurikatel")
        other = make_event(event_id=2, title="Other Event", venue_name="Elsewhere")
        key = serialize_event_series_key(
            event_series_key("Balti Jaama Turg", "Kultuurikatel")
        )
        claim = MagicMock(kind=CLAIM_KIND_SERIES, event_series_key=key)

        execute_result = MagicMock()
        execute_result.scalars.return_value.all.return_value = [matching, other]
        mock_db.execute.return_value = execute_result

        result = await representative_event_for_claim(mock_db, claim)
        assert result is matching

    @pytest.mark.asyncio
    async def test_series_claim_no_match_returns_none(self, mock_db, make_event):
        other = make_event(event_id=2, title="Other Event", venue_name="Elsewhere")
        claim = MagicMock(kind=CLAIM_KIND_SERIES, event_series_key="nope\x1fnope")

        execute_result = MagicMock()
        execute_result.scalars.return_value.all.return_value = [other]
        mock_db.execute.return_value = execute_result

        result = await representative_event_for_claim(mock_db, claim)
        assert result is None
