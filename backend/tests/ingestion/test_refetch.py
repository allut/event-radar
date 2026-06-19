"""Tests for the daily detail-refetch sync (refetch_event_details + reconciliation)."""

from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants import (
    REFETCH_MIN_INTERVAL_DAYS,
    TALLINN_CENTER_LAT,
    TALLINN_CENTER_LNG,
    TALLINN_TZ,
)
from app.ingestion.refetch import (
    _is_empty_venue_name,
    refetch_event_details,
)

# --- HTML builders -----------------------------------------------------------


def _ld_script(json_body: str) -> str:
    return f'<html><head><script type="application/ld+json">{json_body}</script></head></html>'


def _event_html(
    *,
    name: str | None = None,
    street: str | None = None,
    locality: str | None = "Tallinn",
    lat: float | None = None,
    lng: float | None = None,
    price: float | None = None,
    currency: str = "EUR",
) -> str:
    """Build a fienta-style detail page with a schema.org Event JSON-LD block."""
    parts: list[str] = ['"@type":"Event"']
    if name is not None or street is not None or lat is not None:
        loc: list[str] = ['"@type":"Place"']
        if name is not None:
            loc.append(f'"name":{_q(name)}')
        if lat is not None and lng is not None:
            loc.append(f'"geo":{{"@type":"GeoCoordinates","latitude":{lat},"longitude":{lng}}}')
        addr: list[str] = []
        if street is not None:
            addr.append(f'"streetAddress":{_q(street)}')
        if locality is not None and street is not None:
            addr.append(f'"addressLocality":{_q(locality)}')
        if addr:
            loc.append('"address":{' + ",".join(addr) + "}")
        parts.append('"location":{' + ",".join(loc) + "}")
    if price is not None:
        parts.append(
            f'"offers":{{"@type":"Offer","price":"{price}","priceCurrency":"{currency}"}}'
        )
    return _ld_script("{" + ",".join(parts) + "}")


def _q(s: str) -> str:
    return '"' + s.replace('"', '\\"') + '"'


def _resp(html: str) -> MagicMock:
    r = MagicMock()
    r.text = html
    return r


def _future_event(**overrides) -> MagicMock:
    e = MagicMock()
    e.id = 1
    e.url = "https://fienta.com/some-event-1"
    e.starts_at = datetime.now(TALLINN_TZ) + timedelta(days=7)
    e.title_orig = "Test Event"
    e.description_orig = "A test event description"
    e.venue_name = "Test Venue"
    e.venue_address = "Old Street 1, Tallinn"
    e.lat = TALLINN_CENTER_LAT
    e.lng = TALLINN_CENTER_LNG
    e.price_min = None
    e.price_max = None
    e.currency = "EUR"
    e.status = "published"
    e.is_explicit = False
    e.detail_refetched_at = None
    e.detail_refetch_count = 0
    for k, v in overrides.items():
        setattr(e, k, v)
    return e


async def _run(mock_db, event, html) -> dict:
    """Drive refetch_event_details with one candidate event and a stubbed detail page."""
    mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[event]))
    with (
        patch("app.ingestion.refetch.http_get", new=AsyncMock(return_value=_resp(html))),
        patch("app.ingestion.refetch.asyncio.sleep", new=AsyncMock()),
    ):
        return await refetch_event_details(mock_db)


# --- _is_empty_venue_name (placeholder set, online exclusion) ----------------


class TestIsEmptyVenueName:
    @pytest.mark.parametrize("name", [None, "", "   ", "TBD", "tba", "---", "N/A", "unknown"])
    def test_empty_or_placeholder(self, name):
        assert _is_empty_venue_name(name) is True

    @pytest.mark.parametrize("name", ["KUMU", "Online", "MamaOnline", "Heldeke!"])
    def test_real_names_not_empty(self, name):
        # online/MamaOnline are real venue names, never placeholders.
        assert _is_empty_venue_name(name) is False


# --- price reconciliation ----------------------------------------------------


class TestPriceReconcile:
    @pytest.mark.asyncio
    async def test_fills_empty_price(self, mock_db):
        event = _future_event(price_min=None, price_max=None)
        summary = await _run(mock_db, event, _event_html(price=12.0))
        assert event.price_min == 12.0
        assert summary["price_changed"] == 1

    @pytest.mark.asyncio
    async def test_overwrites_changed_price(self, mock_db):
        event = _future_event(price_min=Decimal("10.00"), price_max=Decimal("10.00"))
        summary = await _run(mock_db, event, _event_html(price=15.0))
        assert event.price_min == 15.0
        assert summary["price_changed"] == 1

    @pytest.mark.asyncio
    async def test_same_price_unchanged(self, mock_db):
        event = _future_event(price_min=Decimal("12.00"), price_max=Decimal("12.00"))
        summary = await _run(mock_db, event, _event_html(price=12.0))
        assert summary["price_changed"] == 0
        assert summary["unchanged"] == 1

    @pytest.mark.asyncio
    async def test_no_offers_leaves_stored_price(self, mock_db):
        event = _future_event(price_min=Decimal("9.00"), price_max=Decimal("9.00"))
        # Detail has a location but no offers — must not clobber the stored price.
        summary = await _run(mock_db, event, _event_html(name="Test Venue", street="Old Street 1"))
        assert event.price_min == Decimal("9.00")
        assert summary["price_changed"] == 0


# --- address <-> coords coupling --------------------------------------------


class TestAddressCoordsCoupling:
    @pytest.mark.asyncio
    async def test_address_change_with_coords_updates_triple(self, mock_db):
        event = _future_event(venue_address="Old Street 1, Tallinn")
        summary = await _run(
            mock_db, event,
            _event_html(name="Heldeke!", street="Tööstuse tänav 13", lat=59.44, lng=24.75),
        )
        assert event.venue_address == "Tööstuse tänav 13, Tallinn"
        assert event.lat == 59.44
        assert event.lng == 24.75
        assert summary["address_changed"] == 1
        assert summary["coords_changed"] == 1

    @pytest.mark.asyncio
    async def test_address_change_without_coords_nulls_coords(self, mock_db):
        event = _future_event(
            venue_address="Old Street 1, Tallinn", lat=59.0, lng=24.0
        )
        summary = await _run(
            mock_db, event, _event_html(name="New Place", street="New Street 5")
        )
        assert event.venue_address == "New Street 5, Tallinn"
        assert event.lat is None
        assert event.lng is None
        assert summary["address_changed"] == 1
        assert summary["coords_changed"] == 1

    @pytest.mark.asyncio
    async def test_neither_reported_preserves_sibling_triple(self, mock_db):
        # A sibling-copied (address, lat, lng) triple; detail page reports only a name.
        event = _future_event(
            venue_address="Sibling Addr 9, Tallinn", lat=59.1, lng=24.2,
            venue_name="Test Venue",
        )
        summary = await _run(mock_db, event, _event_html(name="Test Venue"))
        assert event.venue_address == "Sibling Addr 9, Tallinn"
        assert event.lat == 59.1
        assert event.lng == 24.2
        assert summary["address_changed"] == 0
        assert summary["coords_changed"] == 0

    @pytest.mark.asyncio
    async def test_coord_within_tolerance_is_unchanged(self, mock_db):
        # Same address; coords differ only in sub-meter float noise → no change.
        event = _future_event(
            venue_address="Same Street 1, Tallinn",
            lat=59.43793509999999, lng=24.7379351,
        )
        summary = await _run(
            mock_db, event,
            _event_html(street="Same Street 1", lat=59.4379351, lng=24.73793509999999),
        )
        assert summary["coords_changed"] == 0
        assert event.lat == 59.43793509999999  # untouched

    @pytest.mark.asyncio
    async def test_same_address_coords_moved_updates_coords_only(self, mock_db):
        event = _future_event(
            venue_address="Same Street 1, Tallinn", lat=59.1, lng=24.1
        )
        summary = await _run(
            mock_db, event,
            _event_html(street="Same Street 1", lat=59.5, lng=24.5),
        )
        assert event.venue_address == "Same Street 1, Tallinn"
        assert event.lat == 59.5
        assert event.lng == 24.5
        assert summary["coords_changed"] == 1
        assert summary["address_changed"] == 0

    @pytest.mark.asyncio
    async def test_address_change_already_null_coords_not_counted(self, mock_db):
        # Address changes, stored coords were already NULL, detail has no coords →
        # nothing about the coords actually changed, so coords_changed must not count.
        event = _future_event(venue_address="Old Street 1, Tallinn", lat=None, lng=None)
        summary = await _run(
            mock_db, event, _event_html(name="New Place", street="New Street 5")
        )
        assert event.venue_address == "New Street 5, Tallinn"
        assert event.lat is None
        assert summary["address_changed"] == 1
        assert summary["coords_changed"] == 0

    @pytest.mark.asyncio
    async def test_fills_empty_address_and_coords(self, mock_db):
        event = _future_event(venue_address=None, lat=None, lng=None)
        summary = await _run(
            mock_db, event,
            _event_html(street="Filled Street 2", lat=59.4, lng=24.7),
        )
        assert event.venue_address == "Filled Street 2, Tallinn"
        assert event.lat == 59.4
        assert summary["address_changed"] == 1


# --- venue_name guard --------------------------------------------------------


class TestVenueNameGuard:
    @pytest.mark.asyncio
    async def test_clean_name_overwrites(self, mock_db):
        event = _future_event(venue_name="KUMU")
        summary = await _run(mock_db, event, _event_html(name="Vaba Lava"))
        assert event.venue_name == "Vaba Lava"
        assert summary["venue_changed"] == 1

    @pytest.mark.asyncio
    async def test_suspect_detail_name_does_not_overwrite_clean(self, mock_db):
        event = _future_event(venue_name="KUMU")
        # Suspect: contains a comma + digits (a glued address).
        summary = await _run(
            mock_db, event, _event_html(name="Some Hall, Telliskivi 60a")
        )
        assert event.venue_name == "KUMU"
        assert summary["venue_changed"] == 0

    @pytest.mark.asyncio
    async def test_placeholder_name_replaced(self, mock_db):
        event = _future_event(venue_name="TBD")
        summary = await _run(mock_db, event, _event_html(name="Heldeke!"))
        assert event.venue_name == "Heldeke!"
        assert summary["venue_changed"] == 1

    @pytest.mark.asyncio
    async def test_online_name_left_intact(self, mock_db):
        # Online event: real "MamaOnline" name, no physical address. Same name on
        # the detail page → untouched; address stays empty.
        event = _future_event(venue_name="MamaOnline", venue_address=None, lat=None, lng=None)
        summary = await _run(mock_db, event, _event_html(name="MamaOnline", price=0.0))
        assert event.venue_name == "MamaOnline"
        assert event.venue_address is None
        assert summary["venue_changed"] == 0


# --- content-safety re-check on venue_name change ---------------------------


class TestExplicitVenueNameGuard:
    @pytest.mark.asyncio
    async def test_explicit_detail_name_flags_and_demotes_published(self, mock_db):
        event = _future_event(
            venue_name="Old Venue", is_explicit=False, status="published"
        )
        summary = await _run(mock_db, event, _event_html(name="Strip Club Tallinn"))
        assert event.venue_name == "Strip Club Tallinn"
        assert event.is_explicit is True
        assert event.status == "classified"  # demoted so the publish gate re-excludes
        assert summary["flagged_explicit"] == 1

    @pytest.mark.asyncio
    async def test_clean_name_change_does_not_flag(self, mock_db):
        event = _future_event(venue_name="KUMU", is_explicit=False, status="published")
        summary = await _run(mock_db, event, _event_html(name="Vaba Lava"))
        assert event.is_explicit is False
        assert event.status == "published"
        assert summary["flagged_explicit"] == 0


# --- throttle bump + no-data -------------------------------------------------


class TestThrottleBump:
    @pytest.mark.asyncio
    async def test_no_data_still_bumps_counters(self, mock_db):
        event = _future_event()
        summary = await _run(mock_db, event, "<html><body>no jsonld here</body></html>")
        assert summary["no_data"] == 1
        assert event.detail_refetch_count == 1
        assert event.detail_refetched_at is not None

    @pytest.mark.asyncio
    async def test_unchanged_still_bumps_counters(self, mock_db):
        event = _future_event(
            venue_name="Test Venue", venue_address="Old Street 1, Tallinn",
            lat=59.1, lng=24.1, price_min=Decimal("12.00"), price_max=Decimal("12.00"),
        )
        summary = await _run(
            mock_db, event,
            _event_html(name="Test Venue", street="Old Street 1", lat=59.1, lng=24.1, price=12.0),
        )
        assert summary["unchanged"] == 1
        assert event.detail_refetch_count == 1
        assert event.detail_refetched_at is not None

    @pytest.mark.asyncio
    async def test_fetch_failure_does_not_bump(self, mock_db):
        import httpx

        event = _future_event()
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[event]))
        with (
            patch(
                "app.ingestion.refetch.http_get",
                new=AsyncMock(side_effect=httpx.RequestError("boom")),
            ),
            patch("app.ingestion.refetch.asyncio.sleep", new=AsyncMock()),
        ):
            summary = await refetch_event_details(mock_db)
        assert summary["failed"] == 1
        assert event.detail_refetch_count == 0  # not throttled — retries next run
        assert event.detail_refetched_at is None


# --- candidate query ---------------------------------------------------------


class TestCandidateQuery:
    @pytest.mark.asyncio
    async def test_query_predicates(self, mock_db):
        captured: dict = {}

        def _capture(stmt):
            captured["stmt"] = stmt
            return MagicMock(all=MagicMock(return_value=[]))

        mock_db.scalars.side_effect = _capture
        summary = await refetch_event_details(mock_db)
        assert summary["candidates"] == 0

        sql = str(captured["stmt"])
        # Future events with a url, throttle window, oldest-first ordering.
        assert "events.url IS NOT NULL" in sql
        assert "events.starts_at >" in sql
        assert "events.detail_refetched_at IS NULL" in sql
        assert "events.detail_refetched_at <" in sql
        assert "ORDER BY events.detail_refetched_at ASC NULLS FIRST" in sql
        # Inspect only the predicate (the SELECT column list naturally names every
        # column). No missing-field filter (all future events are candidates) and
        # no attempt-cap clause on the diagnostic counter.
        where_sql = sql.split("WHERE", 1)[1].split("ORDER BY", 1)[0]
        assert "venue_address" not in where_sql
        assert "price_min" not in where_sql
        assert "detail_refetch_count" not in where_sql


def test_min_interval_is_one_day():
    assert REFETCH_MIN_INTERVAL_DAYS == 1
