"""Tests for organizer event submission CRUD (routers/organizer_events.py)."""
import http
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.constants import (
    EVENT_STATUS_CLASSIFIED,
    EVENT_STATUS_PUBLISHED,
    ORGANIZER_DAILY_SUBMISSION_CAP,
)


def _fake_event(**overrides):
    e = MagicMock()
    e.id = 10
    e.slug = "test-event-20260601-abcd"
    e.status = "draft"
    e.submitted_by_organizer_id = None
    e.needs_review = False
    e.is_explicit = False
    e.is_non_event = False
    e.title_orig = "Test Event"
    e.description_orig = "A test event"
    e.important_info = None
    e.venue_name = "Test Venue"
    e.title_localized = None
    e.description_localized = None
    e.important_info_localized = None
    for k, v in overrides.items():
        setattr(e, k, v)
    return e


class TestSubmitEvent:
    @pytest.mark.asyncio
    async def test_creates_classifies_publishes_and_flags_review(
        self, mock_db, make_request, make_organizer
    ):
        from app.routers.organizer_events import SubmitEventBody, submit_event

        organizer = make_organizer(organizer_id=5)
        fake_event = _fake_event()
        source = MagicMock(id=1, slug="user_submission")
        # scalar call order: daily-cap count, user_submission source lookup,
        # then the post-publish_pending re-fetch of the final status (avoids
        # touching the possibly-expired `event` object — see submit_event).
        mock_db.scalar.side_effect = [0, source, EVENT_STATUS_PUBLISHED]
        mock_db.commit = AsyncMock()

        with (
            patch(
                "app.routers.organizer_events.insert_normalized_event",
                new_callable=AsyncMock,
                return_value=fake_event,
            ) as mock_insert,
            patch(
                "app.routers.organizer_events.classify_event",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_classify,
            patch(
                "app.routers.organizer_events.publish_pending",
                new_callable=AsyncMock,
                return_value={"published": 1},
            ) as mock_publish,
        ):
            body = SubmitEventBody(
                title="Kontsert",
                starts_at="2026-06-01T18:00:00+03:00",
            )
            result = await submit_event(
                body,
                make_request(method="POST", path="/organizer/events"),
                organizer,
                mock_db,
            )

        mock_insert.assert_awaited_once()
        mock_classify.assert_awaited_once_with(fake_event, mock_db)
        mock_publish.assert_awaited_once_with(mock_db)
        assert fake_event.submitted_by_organizer_id == 5
        assert fake_event.needs_review is True
        mock_db.commit.assert_awaited_once()
        assert result == {
            "id": 10,
            "slug": fake_event.slug,
            "status": EVENT_STATUS_PUBLISHED,
        }

    @pytest.mark.asyncio
    async def test_daily_cap_returns_429(self, mock_db, make_request, make_organizer):
        from fastapi import HTTPException
        from app.routers.organizer_events import SubmitEventBody, submit_event

        organizer = make_organizer(organizer_id=5)
        mock_db.scalar.side_effect = [ORGANIZER_DAILY_SUBMISSION_CAP]

        body = SubmitEventBody(title="Kontsert", starts_at="2026-06-01T18:00:00+03:00")
        with pytest.raises(HTTPException) as exc_info:
            await submit_event(
                body,
                make_request(method="POST", path="/organizer/events"),
                organizer,
                mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.TOO_MANY_REQUESTS

    @pytest.mark.asyncio
    async def test_naive_starts_at_rejected(self):
        from pydantic import ValidationError
        from app.routers.organizer_events import SubmitEventBody

        with pytest.raises(ValidationError):
            SubmitEventBody(title="Kontsert", starts_at="2026-06-01T18:00:00")

    @pytest.mark.asyncio
    async def test_rejects_url_silently_dropped_by_ssrf_guard(
        self, mock_db, make_request, make_organizer
    ):
        """insert_normalized_event drops a url whose host isn't in
        ALLOWED_SOURCE_HOSTS — the organizer must get a clear 400, not a
        silently-vanished field."""
        from fastapi import HTTPException
        from app.routers.organizer_events import SubmitEventBody, submit_event

        organizer = make_organizer(organizer_id=5)
        # event.url ends up None even though the organizer supplied one.
        fake_event = _fake_event(url=None)
        source = MagicMock(id=1, slug="user_submission")
        mock_db.scalar.side_effect = [0, source]

        with (
            patch(
                "app.routers.organizer_events.insert_normalized_event",
                new_callable=AsyncMock,
                return_value=fake_event,
            ),
            patch(
                "app.routers.organizer_events.classify_event", new_callable=AsyncMock
            ),
            patch(
                "app.routers.organizer_events.publish_pending", new_callable=AsyncMock
            ),
        ):
            body = SubmitEventBody(
                title="Kontsert",
                starts_at="2026-06-01T18:00:00+03:00",
                url="https://not-an-allowed-host.example.com/tickets",
            )
            with pytest.raises(HTTPException) as exc_info:
                await submit_event(
                    body,
                    make_request(method="POST", path="/organizer/events"),
                    organizer,
                    mock_db,
                )
        assert exc_info.value.status_code == http.HTTPStatus.BAD_REQUEST


class TestUpdateOwnEvent:
    @pytest.mark.asyncio
    async def test_sets_needs_review_on_clean_edit_keeps_published(
        self, mock_db, make_request, make_organizer
    ):
        from app.routers.organizer_events import PatchEventBody, update_own_event

        organizer = make_organizer(organizer_id=5)
        event = _fake_event(
            submitted_by_organizer_id=5, status=EVENT_STATUS_PUBLISHED, needs_review=False
        )
        mock_db.scalar.return_value = event
        mock_db.commit = AsyncMock()

        body = PatchEventBody(venue_name="New Venue Hall")
        result = await update_own_event(
            10,
            body,
            make_request(method="PATCH", path="/organizer/events/10"),
            organizer,
            mock_db,
        )

        assert event.venue_name == "New Venue Hall"
        assert event.needs_review is True
        assert event.status == EVENT_STATUS_PUBLISHED  # clean edit never demotes
        assert result["status"] == EVENT_STATUS_PUBLISHED

    @pytest.mark.asyncio
    async def test_newly_flagged_explicit_demotes_published_event(
        self, mock_db, make_request, make_organizer
    ):
        from app.routers.organizer_events import PatchEventBody, update_own_event

        organizer = make_organizer(organizer_id=5)
        event = _fake_event(
            submitted_by_organizer_id=5, status=EVENT_STATUS_PUBLISHED, is_explicit=False
        )
        mock_db.scalar.return_value = event
        mock_db.commit = AsyncMock()

        body = PatchEventBody(title="Striptease Night")
        result = await update_own_event(
            10,
            body,
            make_request(method="PATCH", path="/organizer/events/10"),
            organizer,
            mock_db,
        )

        assert event.is_explicit is True
        assert event.status == EVENT_STATUS_CLASSIFIED
        assert result["status"] == EVENT_STATUS_CLASSIFIED

    @pytest.mark.asyncio
    async def test_cross_organizer_edit_raises_404(
        self, mock_db, make_request, make_organizer
    ):
        from fastapi import HTTPException
        from app.routers.organizer_events import PatchEventBody, update_own_event

        organizer = make_organizer(organizer_id=5)
        mock_db.scalar.return_value = None  # no event matches (id, organizer_id)

        body = PatchEventBody(venue_name="Hijack Attempt")
        with pytest.raises(HTTPException) as exc_info:
            await update_own_event(
                10,
                body,
                make_request(method="PATCH", path="/organizer/events/10"),
                organizer,
                mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_url_edit_goes_through_ssrf_guard_and_is_rejected(
        self, mock_db, make_request, make_organizer
    ):
        """A PATCH-supplied url must be pinned through the same
        safe_fetchable_url() host-allowlist as the insert path — not
        assigned straight from the request body."""
        from fastapi import HTTPException
        from app.routers.organizer_events import PatchEventBody, update_own_event

        organizer = make_organizer(organizer_id=5)
        event = _fake_event(submitted_by_organizer_id=5, status=EVENT_STATUS_PUBLISHED)
        mock_db.scalar.return_value = event
        mock_db.commit = AsyncMock()

        with patch(
            "app.routers.organizer_events.safe_fetchable_url",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_guard:
            body = PatchEventBody(url="https://attacker.internal/rebind")
            with pytest.raises(HTTPException) as exc_info:
                await update_own_event(
                    10,
                    body,
                    make_request(method="PATCH", path="/organizer/events/10"),
                    organizer,
                    mock_db,
                )
        mock_guard.assert_awaited_once()
        assert exc_info.value.status_code == http.HTTPStatus.BAD_REQUEST

    @pytest.mark.asyncio
    async def test_url_edit_accepted_when_guard_passes(
        self, mock_db, make_request, make_organizer
    ):
        from app.routers.organizer_events import PatchEventBody, update_own_event

        organizer = make_organizer(organizer_id=5)
        event = _fake_event(submitted_by_organizer_id=5, status=EVENT_STATUS_PUBLISHED)
        mock_db.scalar.return_value = event
        mock_db.commit = AsyncMock()

        with patch(
            "app.routers.organizer_events.safe_fetchable_url",
            new_callable=AsyncMock,
            return_value="https://fienta.com/e/some-event",
        ):
            body = PatchEventBody(url="https://fienta.com/e/some-event")
            result = await update_own_event(
                10,
                body,
                make_request(method="PATCH", path="/organizer/events/10"),
                organizer,
                mock_db,
            )
        assert event.url == "https://fienta.com/e/some-event"
        assert result["status"] == EVENT_STATUS_PUBLISHED


class TestListOwnEvents:
    @pytest.mark.asyncio
    async def test_includes_status_and_needs_review(
        self, mock_db, make_request, make_organizer
    ):
        """serialize_event() is public-read-path-oriented and omits status —
        the organizer's own dashboard must be able to tell lifecycle states
        apart, so list_own_events layers status/needs_review on top."""
        from app.routers.organizer_events import list_own_events

        organizer = make_organizer(organizer_id=5)
        event = _fake_event(
            submitted_by_organizer_id=5,
            status=EVENT_STATUS_CLASSIFIED,
            needs_review=True,
        )
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[event]))

        result = await list_own_events(
            make_request(path="/organizer/events"), 20, 0, organizer, mock_db
        )

        assert result["events"][0]["status"] == EVENT_STATUS_CLASSIFIED
        assert result["events"][0]["needs_review"] is True


class TestDeleteOwnEvent:
    @pytest.mark.asyncio
    async def test_deletes_sets_cancelled(self, mock_db, make_request, make_organizer):
        from app.constants import EVENT_STATUS_CANCELLED
        from app.routers.organizer_events import delete_own_event

        organizer = make_organizer(organizer_id=5)
        event = _fake_event(submitted_by_organizer_id=5)
        mock_db.scalar.return_value = event
        mock_db.commit = AsyncMock()

        result = await delete_own_event(
            10,
            make_request(method="DELETE", path="/organizer/events/10"),
            organizer,
            mock_db,
        )

        assert event.status == EVENT_STATUS_CANCELLED
        assert result["status"] == EVENT_STATUS_CANCELLED

    @pytest.mark.asyncio
    async def test_cross_organizer_delete_raises_404(
        self, mock_db, make_request, make_organizer
    ):
        from fastapi import HTTPException
        from app.routers.organizer_events import delete_own_event

        organizer = make_organizer(organizer_id=5)
        mock_db.scalar.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await delete_own_event(
                10,
                make_request(method="DELETE", path="/organizer/events/10"),
                organizer,
                mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.NOT_FOUND
