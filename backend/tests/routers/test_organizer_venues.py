"""Tests for organizer venue CRUD (routers/organizer_venues.py)."""
import http
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from app.constants.organizer import ORGANIZER_DAILY_VENUE_CREATION_CAP
from tests.conftest import build_venue


def _fake_venue(**overrides):
    defaults = {
        "name": "Test Venue",
        "address": "Test Street 1",
        "lat": 59.437,
        "lng": 24.7536,
        "organizer_id": 5,
        "price_min": None,
        "price_max": None,
        "currency": None,
        "geocode_attempted_at": "2026-05-13T06:00:00+00:00",
        "deleted_at": None,
        "created_at": "2026-05-13T06:00:00+00:00",
    }
    return build_venue(**(defaults | overrides))


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
            make_request(method="GET", path="/organizer/venues"),
            limit=50,
            offset=0,
            current_organizer=organizer,
            db=mock_db,
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
            make_request(method="GET", path="/organizer/venues"),
            limit=50,
            offset=0,
            current_organizer=organizer,
            db=mock_db,
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
    async def test_rename_rescans_linked_events_and_queues_review(
        self, mock_db, make_request, make_organizer, make_event
    ):
        """OWASP audit #5: a renamed venue is resolved onto every linked
        event at read time, so the rename must pass the same explicit-content
        scan as the submit path and queue the events for admin review."""
        from app.constants.events import EVENT_STATUS_CLASSIFIED, EVENT_STATUS_PUBLISHED
        from app.routers.organizer_venues import VenuePatchBody, update_own_venue

        organizer = make_organizer(organizer_id=5)
        venue = _fake_venue()
        mock_db.scalar.return_value = venue
        clean = make_event(event_id=1, status=EVENT_STATUS_PUBLISHED)
        flagged = make_event(event_id=2, status=EVENT_STATUS_PUBLISHED)
        for ev in (clean, flagged):
            ev.is_explicit = False
            ev.is_non_event = False
            ev.needs_review = False
            ev.important_info = None
            ev.title_orig = "Jazz night"
            ev.description_orig = None
        flagged.important_info = "striptease after party"
        scalars_result = MagicMock()
        scalars_result.all.return_value = [clean, flagged]
        mock_db.scalars.return_value = scalars_result

        await update_own_venue(
            1,
            VenuePatchBody(name="Renamed Venue"),
            make_request(method="PATCH", path="/organizer/venues/1"),
            organizer,
            mock_db,
        )

        assert clean.needs_review is True
        assert clean.status == EVENT_STATUS_PUBLISHED
        assert flagged.needs_review is True
        assert flagged.is_explicit is True
        assert flagged.status == EVENT_STATUS_CLASSIFIED

    @pytest.mark.asyncio
    async def test_rename_to_explicit_name_pulls_published_event_back(
        self, mock_db, make_request, make_organizer, make_event
    ):
        from app.constants.events import EVENT_STATUS_CLASSIFIED, EVENT_STATUS_PUBLISHED
        from app.routers.organizer_venues import VenuePatchBody, update_own_venue

        organizer = make_organizer(organizer_id=5)
        venue = _fake_venue()
        mock_db.scalar.return_value = venue
        event = make_event(event_id=1, status=EVENT_STATUS_PUBLISHED)
        event.is_explicit = False
        event.is_non_event = False
        event.important_info = None
        event.title_orig = "Jazz night"
        event.description_orig = None
        scalars_result = MagicMock()
        scalars_result.all.return_value = [event]
        mock_db.scalars.return_value = scalars_result

        await update_own_venue(
            1,
            VenuePatchBody(name="Striptease Club"),
            make_request(method="PATCH", path="/organizer/venues/1"),
            organizer,
            mock_db,
        )

        assert event.is_explicit is True
        assert event.status == EVENT_STATUS_CLASSIFIED

    @pytest.mark.asyncio
    async def test_non_name_edit_does_not_rescan_events(
        self, mock_db, make_request, make_organizer
    ):
        from app.routers.organizer_venues import VenuePatchBody, update_own_venue

        organizer = make_organizer(organizer_id=5)
        venue = _fake_venue()
        mock_db.scalar.return_value = venue

        await update_own_venue(
            1,
            VenuePatchBody(name=venue.name, price_min=10),
            make_request(method="PATCH", path="/organizer/venues/1"),
            organizer,
            mock_db,
        )

        mock_db.scalars.assert_not_called()

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
