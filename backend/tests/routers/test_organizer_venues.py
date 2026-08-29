"""Tests for organizer venue CRUD (routers/organizer_venues.py)."""
import http
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.constants import ORGANIZER_DAILY_VENUE_CREATION_CAP


def _fake_venue(**overrides):
    v = MagicMock()
    v.id = 1
    v.organizer_id = 5
    v.name = "Test Venue"
    v.name_en = None
    v.name_ru = None
    v.address = "Test Street 1"
    v.lat = 59.437
    v.lng = 24.7536
    v.price_min = None
    v.price_max = None
    v.currency = None
    v.geocode_attempted_at = "2026-05-13T06:00:00+00:00"
    v.deleted_at = None
    v.created_at = "2026-05-13T06:00:00+00:00"
    for k, val in overrides.items():
        setattr(v, k, val)
    return v


class TestListOwnVenues:
    @pytest.mark.asyncio
    async def test_returns_serialized_venues(
        self, mock_db, make_request, make_organizer
    ):
        from app.routers.organizer_venues import list_own_venues

        organizer = make_organizer(organizer_id=5)
        venue = _fake_venue()
        scalars_result = MagicMock()
        scalars_result.all.return_value = [venue]
        mock_db.scalars.return_value = scalars_result

        result = await list_own_venues(
            make_request(method="GET", path="/organizer/venues"), organizer, mock_db
        )

        assert result == [
            {
                "id": venue.id,
                "name": venue.name,
                "name_en": venue.name_en,
                "name_ru": venue.name_ru,
                "address": venue.address,
                "lat": venue.lat,
                "lng": venue.lng,
                "price_min": venue.price_min,
                "price_max": venue.price_max,
                "currency": venue.currency,
                "created_at": venue.created_at,
            }
        ]

    @pytest.mark.asyncio
    async def test_scopes_query_to_own_organizer(
        self, mock_db, make_request, make_organizer
    ):
        """Proves list_own_venues actually filters by organizer_id, not just
        that it returns whatever db.scalars() hands back."""
        from app.routers.organizer_venues import list_own_venues

        organizer = make_organizer(organizer_id=5)
        scalars_result = MagicMock()
        scalars_result.all.return_value = []
        mock_db.scalars.return_value = scalars_result

        await list_own_venues(
            make_request(method="GET", path="/organizer/venues"), organizer, mock_db
        )

        stmt = mock_db.scalars.call_args[0][0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "organizer_id = 5" in compiled
        assert "deleted_at IS NULL" in compiled


class TestCreateVenue:
    @pytest.mark.asyncio
    async def test_creates_venue_with_defaults(
        self, mock_db, make_request, make_organizer
    ):
        from app.routers.organizer_venues import VenueBody, create_venue

        organizer = make_organizer(organizer_id=5)
        mock_db.scalar.side_effect = [0]  # daily-cap count

        created = _fake_venue(organizer_id=5)

        def _refresh(obj):
            for attr in (
                "id",
                "name",
                "name_en",
                "name_ru",
                "address",
                "lat",
                "lng",
                "price_min",
                "price_max",
                "currency",
                "created_at",
            ):
                setattr(obj, attr, getattr(created, attr))

        mock_db.refresh.side_effect = _refresh

        body = VenueBody(name="Test Venue", address="Test Street 1")
        result = await create_venue(
            body, make_request(method="POST", path="/organizer/venues"), organizer, mock_db
        )

        mock_db.add.assert_called_once()
        added = mock_db.add.call_args[0][0]
        assert added.organizer_id == 5
        assert added.name == "Test Venue"
        assert result["name"] == "Test Venue"

    @pytest.mark.asyncio
    async def test_daily_cap_returns_429_and_does_not_persist(
        self, mock_db, make_request, make_organizer
    ):
        from fastapi import HTTPException
        from app.routers.organizer_venues import VenueBody, create_venue

        organizer = make_organizer(organizer_id=5)
        mock_db.scalar.side_effect = [ORGANIZER_DAILY_VENUE_CREATION_CAP]

        body = VenueBody(name="Test Venue")
        with pytest.raises(HTTPException) as exc_info:
            await create_venue(
                body,
                make_request(method="POST", path="/organizer/venues"),
                organizer,
                mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.TOO_MANY_REQUESTS
        mock_db.add.assert_not_called()
        mock_db.commit.assert_not_called()

    def test_inverted_price_range_rejected(self):
        from app.routers.organizer_venues import VenueBody

        with pytest.raises(ValidationError):
            VenueBody(name="Test Venue", price_min=50, price_max=10)


class TestUpdateOwnVenue:
    @pytest.mark.asyncio
    async def test_name_only_edit_preserves_geocode_state(
        self, mock_db, make_request, make_organizer
    ):
        from app.routers.organizer_venues import VenuePatchBody, update_own_venue

        organizer = make_organizer(organizer_id=5)
        venue = _fake_venue()
        mock_db.scalar.return_value = venue

        body = VenuePatchBody(name="Renamed Venue")
        await update_own_venue(
            1,
            body,
            make_request(method="PATCH", path="/organizer/venues/1"),
            organizer,
            mock_db,
        )

        assert venue.name == "Renamed Venue"
        assert venue.lat == 59.437  # untouched
        assert venue.geocode_attempted_at == "2026-05-13T06:00:00+00:00"

    @pytest.mark.asyncio
    async def test_address_edit_clears_geocode_state(
        self, mock_db, make_request, make_organizer
    ):
        from app.routers.organizer_venues import VenuePatchBody, update_own_venue

        organizer = make_organizer(organizer_id=5)
        venue = _fake_venue()
        mock_db.scalar.return_value = venue

        body = VenuePatchBody(address="New Street 5")
        await update_own_venue(
            1,
            body,
            make_request(method="PATCH", path="/organizer/venues/1"),
            organizer,
            mock_db,
        )

        assert venue.address == "New Street 5"
        assert venue.lat is None
        assert venue.lng is None
        assert venue.geocode_attempted_at is None

    @pytest.mark.asyncio
    async def test_address_edit_with_unchanged_value_preserves_geocode_state(
        self, mock_db, make_request, make_organizer
    ):
        """A PATCH that round-trips the same address value (e.g. a form
        re-submitting the full block after only price changed) must not
        force an unnecessary re-geocode."""
        from app.routers.organizer_venues import VenuePatchBody, update_own_venue

        organizer = make_organizer(organizer_id=5)
        venue = _fake_venue()
        mock_db.scalar.return_value = venue

        body = VenuePatchBody(address=venue.address, price_min=10)
        await update_own_venue(
            1,
            body,
            make_request(method="PATCH", path="/organizer/venues/1"),
            organizer,
            mock_db,
        )

        assert venue.lat == 59.437
        assert venue.lng == 24.7536
        assert venue.geocode_attempted_at == "2026-05-13T06:00:00+00:00"

    @pytest.mark.asyncio
    async def test_cross_organizer_edit_raises_404(
        self, mock_db, make_request, make_organizer
    ):
        from fastapi import HTTPException
        from app.routers.organizer_venues import VenuePatchBody, update_own_venue

        organizer = make_organizer(organizer_id=5)
        mock_db.scalar.return_value = None  # no venue matches (id, organizer_id)

        body = VenuePatchBody(name="Hijack Attempt")
        with pytest.raises(HTTPException) as exc_info:
            await update_own_venue(
                1,
                body,
                make_request(method="PATCH", path="/organizer/venues/1"),
                organizer,
                mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.NOT_FOUND

    def test_inverted_price_range_rejected(self):
        from app.routers.organizer_venues import VenuePatchBody

        with pytest.raises(ValidationError):
            VenuePatchBody(price_min=50, price_max=10)


class TestDeleteOwnVenue:
    @pytest.mark.asyncio
    async def test_soft_deletes(self, mock_db, make_request, make_organizer):
        from app.routers.organizer_venues import delete_own_venue

        organizer = make_organizer(organizer_id=5)
        venue = _fake_venue()
        mock_db.scalar.return_value = venue

        await delete_own_venue(
            1,
            make_request(method="DELETE", path="/organizer/venues/1"),
            organizer,
            mock_db,
        )

        assert venue.deleted_at is not None
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_cross_organizer_delete_raises_404(
        self, mock_db, make_request, make_organizer
    ):
        from fastapi import HTTPException
        from app.routers.organizer_venues import delete_own_venue

        organizer = make_organizer(organizer_id=5)
        mock_db.scalar.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await delete_own_venue(
                1,
                make_request(method="DELETE", path="/organizer/venues/1"),
                organizer,
                mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.NOT_FOUND
