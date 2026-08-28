"""Tests for organizer event submission CRUD (routers/organizer_events.py)."""
import http
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from app.constants import (
    EVENT_STATUS_CANCELLED,
    EVENT_STATUS_CLASSIFIED,
    EVENT_STATUS_PUBLISHED,
    ORGANIZER_CURRENCY_MAX_LEN,
    ORGANIZER_DAILY_SUBMISSION_CAP,
    ORGANIZER_VENUE_NAME_MAX_LEN,
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
    e.venue_id = None
    e.title_localized = None
    e.description_localized = None
    e.important_info_localized = None
    for k, v in overrides.items():
        setattr(e, k, v)
    return e


class TestCheckImageHost:
    """L4: organizer-submission image_url must be the signed Cloudinary
    upload's own delivery domain — otherwise the digest's <img> embed becomes
    an arbitrary-host tracking pixel."""

    def test_none_is_a_noop(self):
        from app.routers.organizer_events import _check_image_host

        _check_image_host(None)  # must not raise

    def test_cloudinary_host_accepted(self):
        from app.routers.organizer_events import _check_image_host

        _check_image_host("https://res.cloudinary.com/demo/image/upload/x.png")

    def test_arbitrary_host_rejected(self):
        from fastapi import HTTPException
        from app.routers.organizer_events import _check_image_host

        with pytest.raises(HTTPException) as exc_info:
            _check_image_host("https://evil.example.com/tracker.png")
        assert exc_info.value.status_code == http.HTTPStatus.BAD_REQUEST

    def test_lookalike_host_rejected(self):
        """A host merely containing the trusted domain as a substring/suffix
        (e.g. a subdomain trick) must not slip through — hostname must match
        exactly, not via substring containment."""
        from fastapi import HTTPException
        from app.routers.organizer_events import _check_image_host

        with pytest.raises(HTTPException):
            _check_image_host("https://res.cloudinary.com.evil.com/x.png")


class TestApplyOrganizerCategory:
    @pytest.mark.asyncio
    async def test_creates_classification_when_none_exists(self, mock_db):
        from app.routers.organizer_events import _apply_organizer_category

        mock_db.scalar.return_value = None
        mock_db.add = MagicMock()

        await _apply_organizer_category(mock_db, 10, "music")

        mock_db.add.assert_called_once()
        added = mock_db.add.call_args[0][0]
        assert added.event_id == 10
        assert added.categories == ["music"]

    @pytest.mark.asyncio
    async def test_prepends_to_existing_categories(self, mock_db):
        from app.routers.organizer_events import _apply_organizer_category

        classification = MagicMock()
        classification.categories = ["theater"]
        mock_db.scalar.return_value = classification

        await _apply_organizer_category(mock_db, 10, "music")

        assert classification.categories == ["music", "theater"]

    @pytest.mark.asyncio
    async def test_no_duplicate_when_already_present(self, mock_db):
        from app.routers.organizer_events import _apply_organizer_category

        classification = MagicMock()
        classification.categories = ["music", "theater"]
        mock_db.scalar.return_value = classification

        await _apply_organizer_category(mock_db, 10, "music")

        assert classification.categories == ["music", "theater"]


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
        mock_publish.assert_awaited_once_with(mock_db, event_ids=[10], diagnostics=False)
        assert fake_event.submitted_by_organizer_id == 5
        assert fake_event.needs_review is True
        mock_db.commit.assert_awaited_once()
        assert result == {
            "id": 10,
            "slug": fake_event.slug,
            "status": EVENT_STATUS_PUBLISHED,
        }

    @pytest.mark.asyncio
    async def test_rejects_image_url_off_cloudinary_host(
        self, mock_db, make_request, make_organizer
    ):
        """L4: submit must reject an image_url that isn't the signed upload's
        own domain, before ever touching the DB."""
        from fastapi import HTTPException
        from app.routers.organizer_events import SubmitEventBody, submit_event

        organizer = make_organizer(organizer_id=5)
        source = MagicMock(id=1, slug="user_submission")
        mock_db.scalar.side_effect = [0, source]  # daily-cap count, source lookup

        body = SubmitEventBody(
            title="Kontsert",
            starts_at="2026-06-01T18:00:00+03:00",
            image_url="https://evil.example.com/tracker.png",
        )
        with pytest.raises(HTTPException) as exc_info:
            await submit_event(
                body,
                make_request(method="POST", path="/organizer/events"),
                organizer,
                mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.BAD_REQUEST

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

    def test_invalid_category_rejected(self):
        from pydantic import ValidationError
        from app.routers.organizer_events import SubmitEventBody

        with pytest.raises(ValidationError):
            SubmitEventBody(
                title="Kontsert",
                starts_at="2026-06-01T18:00:00+03:00",
                category="not-a-real-category",
            )

    @pytest.mark.asyncio
    async def test_organizer_category_applied_after_classify(
        self, mock_db, make_request, make_organizer
    ):
        from app.constants import VALID_CATEGORIES
        from app.routers.organizer_events import SubmitEventBody, submit_event

        picked_category = next(iter(VALID_CATEGORIES))
        organizer = make_organizer(organizer_id=5)
        fake_event = _fake_event()
        source = MagicMock(id=1, slug="user_submission")
        mock_db.scalar.side_effect = [0, source, EVENT_STATUS_PUBLISHED]
        mock_db.commit = AsyncMock()

        with (
            patch(
                "app.routers.organizer_events.insert_normalized_event",
                new_callable=AsyncMock,
                return_value=fake_event,
            ),
            patch(
                "app.routers.organizer_events.classify_event",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.routers.organizer_events.publish_pending", new_callable=AsyncMock
            ),
            patch(
                "app.routers.organizer_events._apply_organizer_category",
                new_callable=AsyncMock,
            ) as mock_apply_category,
        ):
            body = SubmitEventBody(
                title="Kontsert",
                starts_at="2026-06-01T18:00:00+03:00",
                category=picked_category,
            )
            await submit_event(
                body,
                make_request(method="POST", path="/organizer/events"),
                organizer,
                mock_db,
            )
        mock_apply_category.assert_awaited_once_with(
            mock_db, fake_event.id, picked_category
        )

    @pytest.mark.asyncio
    async def test_rejects_url_with_bad_scheme(
        self, mock_db, make_request, make_organizer
    ):
        """insert_normalized_event drops a url with a non-http(s) scheme —
        the organizer must get a clear 400, not a silently-vanished field.
        Host is no longer pinned: organizer urls are render-only (never
        server-fetched, see refetch.py's submitted_by_organizer_id exclusion),
        so only the scheme check (safe_external_url) applies."""
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
                url="javascript:alert(1)",
            )
            with pytest.raises(HTTPException) as exc_info:
                await submit_event(
                    body,
                    make_request(method="POST", path="/organizer/events"),
                    organizer,
                    mock_db,
                )
        assert exc_info.value.status_code == http.HTTPStatus.BAD_REQUEST

    @pytest.mark.asyncio
    async def test_accepts_url_on_arbitrary_host(
        self, mock_db, make_request, make_organizer
    ):
        """An organizer's own ticketing domain — never in ALLOWED_SOURCE_HOSTS —
        is accepted now that submitted urls are scheme-checked only."""
        from app.routers.organizer_events import SubmitEventBody, submit_event

        organizer = make_organizer(organizer_id=5)
        fake_event = _fake_event(url="https://mytheatre.ee/tickets/42")
        source = MagicMock(id=1, slug="user_submission")
        mock_db.scalar.side_effect = [0, source, EVENT_STATUS_PUBLISHED]
        mock_db.commit = AsyncMock()

        with (
            patch(
                "app.routers.organizer_events.insert_normalized_event",
                new_callable=AsyncMock,
                return_value=fake_event,
            ),
            patch(
                "app.routers.organizer_events.classify_event",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "app.routers.organizer_events.publish_pending",
                new_callable=AsyncMock,
                return_value={"published": 1},
            ),
        ):
            body = SubmitEventBody(
                title="Kontsert",
                starts_at="2026-06-01T18:00:00+03:00",
                url="https://mytheatre.ee/tickets/42",
            )
            result = await submit_event(
                body,
                make_request(method="POST", path="/organizer/events"),
                organizer,
                mock_db,
            )
        assert result["id"] == fake_event.id

    @pytest.mark.asyncio
    async def test_venue_id_linked_submission_nulls_free_typed_fields(
        self, mock_db, make_request, make_organizer
    ):
        """#176: venue_id set -> venue_name/venue_address left NULL at write
        time even if the organizer also sent free-typed values, and the FK
        is persisted onto the event."""
        from app.routers.organizer_events import SubmitEventBody, submit_event

        organizer = make_organizer(organizer_id=5)
        fake_event = _fake_event()
        source = MagicMock(id=1, slug="user_submission")
        owned_venue = MagicMock(id=7, organizer_id=5, deleted_at=None)
        # MagicMock's `name` kwarg sets the mock's own repr, not a `.name`
        # attribute — set it explicitly so the content-moderation recheck
        # (is_explicit_text/is_non_event_text) scans a real string.
        owned_venue.name = "Real Venue Hall"
        # scalar order: daily-cap count, source lookup, venue ownership check,
        # final-status re-fetch.
        mock_db.scalar.side_effect = [0, source, owned_venue, EVENT_STATUS_PUBLISHED]
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
            ),
            patch(
                "app.routers.organizer_events.publish_pending", new_callable=AsyncMock
            ),
        ):
            body = SubmitEventBody(
                title="Kontsert",
                starts_at="2026-06-01T18:00:00+03:00",
                venue_id=7,
                venue_name="Ignored Free-Typed Name",
                venue_address="Ignored Free-Typed Address",
            )
            result = await submit_event(
                body,
                make_request(method="POST", path="/organizer/events"),
                organizer,
                mock_db,
            )

        normalized_arg = mock_insert.await_args.args[2]
        assert normalized_arg.venue_name is None
        assert normalized_arg.venue_address is None
        assert fake_event.venue_id == 7
        assert result["id"] == fake_event.id

    @pytest.mark.asyncio
    async def test_venue_id_ownership_violation_rejected(
        self, mock_db, make_request, make_organizer
    ):
        """#176: a venue_id owned by another organizer (or nonexistent) 404s
        before any event is created."""
        from fastapi import HTTPException
        from app.routers.organizer_events import SubmitEventBody, submit_event

        organizer = make_organizer(organizer_id=5)
        source = MagicMock(id=1, slug="user_submission")
        # daily-cap count, source lookup, venue ownership check (not found).
        mock_db.scalar.side_effect = [0, source, None]

        with patch(
            "app.routers.organizer_events.insert_normalized_event",
            new_callable=AsyncMock,
        ) as mock_insert:
            body = SubmitEventBody(
                title="Kontsert",
                starts_at="2026-06-01T18:00:00+03:00",
                venue_id=999,
            )
            with pytest.raises(HTTPException) as exc_info:
                await submit_event(
                    body,
                    make_request(method="POST", path="/organizer/events"),
                    organizer,
                    mock_db,
                )
        assert exc_info.value.status_code == http.HTTPStatus.NOT_FOUND
        mock_insert.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_free_typed_submission_unaffected_by_venue_id_support(
        self, mock_db, make_request, make_organizer
    ):
        """#176: the no-venue_id path is unchanged — free-typed venue_name/
        venue_address still flow straight through."""
        from app.routers.organizer_events import SubmitEventBody, submit_event

        organizer = make_organizer(organizer_id=5)
        fake_event = _fake_event()
        source = MagicMock(id=1, slug="user_submission")
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
            ),
            patch(
                "app.routers.organizer_events.publish_pending", new_callable=AsyncMock
            ),
        ):
            body = SubmitEventBody(
                title="Kontsert",
                starts_at="2026-06-01T18:00:00+03:00",
                venue_name="Freely Typed Hall",
                venue_address="Freely Typed St 1",
            )
            await submit_event(
                body,
                make_request(method="POST", path="/organizer/events"),
                organizer,
                mock_db,
            )

        normalized_arg = mock_insert.await_args.args[2]
        assert normalized_arg.venue_name == "Freely Typed Hall"
        assert normalized_arg.venue_address == "Freely Typed St 1"
        assert fake_event.venue_id is None


class TestUpdateOwnEvent:
    @pytest.mark.asyncio
    async def test_rejects_edit_of_cancelled_event(
        self, mock_db, make_request, make_organizer
    ):
        """L-3 in the OWASP audit: an admin takedown is the decisive action
        for content that had to come down — the organizer must not be able
        to change the stored content behind that decision after the fact."""
        from fastapi import HTTPException
        from app.routers.organizer_events import PatchEventBody, update_own_event

        organizer = make_organizer(organizer_id=5)
        event = _fake_event(submitted_by_organizer_id=5, status=EVENT_STATUS_CANCELLED)
        mock_db.scalar.return_value = event

        body = PatchEventBody(venue_name="New Venue Hall")
        with pytest.raises(HTTPException) as exc_info:
            await update_own_event(
                10,
                body,
                make_request(method="PATCH", path="/organizer/events/10"),
                organizer,
                mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.CONFLICT
        # The event must not have been mutated on the way to the rejection.
        assert event.venue_name != "New Venue Hall"

    @pytest.mark.asyncio
    async def test_category_edit_applies_via_helper(
        self, mock_db, make_request, make_organizer
    ):
        from app.constants import VALID_CATEGORIES
        from app.routers.organizer_events import PatchEventBody, update_own_event

        picked_category = next(iter(VALID_CATEGORIES))
        organizer = make_organizer(organizer_id=5)
        event = _fake_event(submitted_by_organizer_id=5, status=EVENT_STATUS_PUBLISHED)
        mock_db.scalar.return_value = event
        mock_db.commit = AsyncMock()

        with patch(
            "app.routers.organizer_events._apply_organizer_category",
            new_callable=AsyncMock,
        ) as mock_apply_category:
            body = PatchEventBody(category=picked_category)
            await update_own_event(
                10,
                body,
                make_request(method="PATCH", path="/organizer/events/10"),
                organizer,
                mock_db,
            )
        mock_apply_category.assert_awaited_once_with(mock_db, event.id, picked_category)

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
        """A PATCH-supplied url must still be scheme-checked via
        safe_external_url() — not assigned straight from the request body."""
        from fastapi import HTTPException
        from app.routers.organizer_events import PatchEventBody, update_own_event

        organizer = make_organizer(organizer_id=5)
        event = _fake_event(submitted_by_organizer_id=5, status=EVENT_STATUS_PUBLISHED)
        mock_db.scalar.return_value = event
        mock_db.commit = AsyncMock()

        with patch(
            "app.routers.organizer_events.safe_external_url",
            return_value=None,
        ) as mock_guard:
            body = PatchEventBody(url="javascript:alert(1)")
            with pytest.raises(HTTPException) as exc_info:
                await update_own_event(
                    10,
                    body,
                    make_request(method="PATCH", path="/organizer/events/10"),
                    organizer,
                    mock_db,
                )
        mock_guard.assert_called_once()
        assert exc_info.value.status_code == http.HTTPStatus.BAD_REQUEST

    @pytest.mark.asyncio
    async def test_url_edit_accepted_when_guard_passes(
        self, mock_db, make_request, make_organizer
    ):
        """A non-allowlisted host is accepted — organizer urls are no longer
        host-pinned, only scheme-checked."""
        from app.routers.organizer_events import PatchEventBody, update_own_event

        organizer = make_organizer(organizer_id=5)
        event = _fake_event(submitted_by_organizer_id=5, status=EVENT_STATUS_PUBLISHED)
        mock_db.scalar.return_value = event
        mock_db.commit = AsyncMock()

        with patch(
            "app.routers.organizer_events.safe_external_url",
            return_value="https://mytheatre.ee/tickets/42",
        ):
            body = PatchEventBody(url="https://mytheatre.ee/tickets/42")
            result = await update_own_event(
                10,
                body,
                make_request(method="PATCH", path="/organizer/events/10"),
                organizer,
                mock_db,
            )
        assert event.url == "https://mytheatre.ee/tickets/42"
        assert result["status"] == EVENT_STATUS_PUBLISHED

    @pytest.mark.asyncio
    async def test_venue_id_edit_links_venue_and_nulls_free_typed_fields(
        self, mock_db, make_request, make_organizer
    ):
        """#176: patching in a venue_id validates ownership, links the FK,
        and clears any stale free-typed venue_name/venue_address."""
        from app.routers.organizer_events import PatchEventBody, update_own_event

        organizer = make_organizer(organizer_id=5)
        event = _fake_event(
            submitted_by_organizer_id=5,
            status=EVENT_STATUS_PUBLISHED,
            venue_name="Old Free-Typed Hall",
            venue_address="Old Address",
            venue_id=None,
        )
        owned_venue = MagicMock(id=7, organizer_id=5, deleted_at=None)
        # MagicMock's `name` kwarg sets the mock's own repr, not a `.name`
        # attribute — set it explicitly so the content-moderation recheck
        # (is_explicit_text/is_non_event_text) scans a real string.
        owned_venue.name = "Real Venue Hall"
        mock_db.scalar.side_effect = [event, owned_venue]
        mock_db.commit = AsyncMock()

        body = PatchEventBody(venue_id=7)
        result = await update_own_event(
            10,
            body,
            make_request(method="PATCH", path="/organizer/events/10"),
            organizer,
            mock_db,
        )

        assert event.venue_id == 7
        assert event.venue_name is None
        assert event.venue_address is None
        assert result["status"] == EVENT_STATUS_PUBLISHED

    @pytest.mark.asyncio
    async def test_venue_id_edit_ownership_violation_raises_404(
        self, mock_db, make_request, make_organizer
    ):
        from fastapi import HTTPException
        from app.routers.organizer_events import PatchEventBody, update_own_event

        organizer = make_organizer(organizer_id=5)
        event = _fake_event(
            submitted_by_organizer_id=5, status=EVENT_STATUS_PUBLISHED, venue_id=None
        )
        mock_db.scalar.side_effect = [event, None]

        body = PatchEventBody(venue_id=999)
        with pytest.raises(HTTPException) as exc_info:
            await update_own_event(
                10,
                body,
                make_request(method="PATCH", path="/organizer/events/10"),
                organizer,
                mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.NOT_FOUND
        assert event.venue_id is None

    @pytest.mark.asyncio
    async def test_venue_name_edit_ignored_when_already_linked(
        self, mock_db, make_request, make_organizer
    ):
        """A PATCH that sends only venue_name (not venue_id) on an event
        already linked to a venue must not resurrect venue_name — the FK
        stays the sole venue source until explicitly unlinked."""
        from app.models.models import Venue
        from app.routers.organizer_events import PatchEventBody, update_own_event

        organizer = make_organizer(organizer_id=5)
        event = _fake_event(
            submitted_by_organizer_id=5,
            status=EVENT_STATUS_PUBLISHED,
            venue_id=7,
            venue_name=None,
            venue_address=None,
        )
        linked_venue = MagicMock(id=7)
        linked_venue.name = "Real Venue Hall"
        # scalar order: _own_event_or_404 lookup, then the moderation
        # recheck's db.get(Venue, ...) fallback — not exercised via scalar,
        # so only one scalar call here; db.get is mocked separately below.
        mock_db.scalar.side_effect = [event]
        mock_db.get = AsyncMock(return_value=linked_venue)
        mock_db.commit = AsyncMock()

        body = PatchEventBody(venue_name="Sneaky Rename Attempt")
        result = await update_own_event(
            10,
            body,
            make_request(method="PATCH", path="/organizer/events/10"),
            organizer,
            mock_db,
        )

        assert event.venue_id == 7
        assert event.venue_name is None
        mock_db.get.assert_awaited_once_with(Venue, 7)
        assert result["status"] == EVENT_STATUS_PUBLISHED


class TestUploadEventImage:
    """POST /organizer/events/image — signed Cloudinary upload (Phase 2 §2.1)."""

    # Real PNG magic bytes — upload_event_image sniffs the leading bytes
    # rather than trusting content_type (M-3 in the OWASP audit), so a fake
    # body would now be rejected as unsupported before reaching whatever the
    # test is actually exercising.
    _PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

    def _fake_upload(self, content_type="image/png", body=None):
        if body is None:
            body = self._PNG_MAGIC + b"fake-bytes"
        f = MagicMock()
        f.content_type = content_type
        f.filename = "photo.png"
        f.read = AsyncMock(return_value=body)
        return f

    @pytest.mark.asyncio
    async def test_rejects_declared_type_not_matching_actual_bytes(
        self, mock_db, make_request, make_organizer
    ):
        """M-3 in the OWASP audit: file.content_type is client-asserted and
        was previously never checked against the actual bytes before they
        left this system for Cloudinary."""
        from fastapi import HTTPException
        from app.routers.organizer_events import upload_event_image

        mock_db.scalar.return_value = 0
        organizer = make_organizer(organizer_id=5)
        # Declares PNG but the bytes are neither PNG, JPEG, nor WebP.
        file = self._fake_upload(content_type="image/png", body=b"not-a-real-image")

        with pytest.raises(HTTPException) as exc_info:
            await upload_event_image(
                make_request(method="POST", path="/organizer/events/image"),
                file,
                organizer,
                mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.UNSUPPORTED_MEDIA_TYPE

    @pytest.mark.asyncio
    async def test_rejects_unsupported_mime(
        self, mock_db, make_request, make_organizer
    ):
        from fastapi import HTTPException
        from app.routers.organizer_events import upload_event_image

        organizer = make_organizer(organizer_id=5)
        file = self._fake_upload(content_type="application/pdf")

        with pytest.raises(HTTPException) as exc_info:
            await upload_event_image(
                make_request(method="POST", path="/organizer/events/image"),
                file,
                organizer,
                mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.UNSUPPORTED_MEDIA_TYPE

    @pytest.mark.asyncio
    async def test_rejects_oversized_file(self, mock_db, make_request, make_organizer):
        from fastapi import HTTPException
        from app.constants import IMAGE_UPLOAD_MAX_BYTES
        from app.routers.organizer_events import upload_event_image

        mock_db.scalar.return_value = 0
        organizer = make_organizer(organizer_id=5)
        file = self._fake_upload(body=b"x" * (IMAGE_UPLOAD_MAX_BYTES + 1))

        with pytest.raises(HTTPException) as exc_info:
            await upload_event_image(
                make_request(method="POST", path="/organizer/events/image"),
                file,
                organizer,
                mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.REQUEST_ENTITY_TOO_LARGE

    @pytest.mark.asyncio
    async def test_daily_upload_cap_returns_429(
        self, mock_db, make_request, make_organizer
    ):
        """L5: a per-account daily image-upload cap, independent of the
        per-IP rate limiter (which an account can sidestep across IPs)."""
        from fastapi import HTTPException
        from app.constants import ORGANIZER_DAILY_IMAGE_UPLOAD_CAP
        from app.routers.organizer_events import upload_event_image

        mock_db.scalar.return_value = ORGANIZER_DAILY_IMAGE_UPLOAD_CAP
        organizer = make_organizer(organizer_id=5)
        file = self._fake_upload()

        with pytest.raises(HTTPException) as exc_info:
            await upload_event_image(
                make_request(method="POST", path="/organizer/events/image"),
                file,
                organizer,
                mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.TOO_MANY_REQUESTS

    @pytest.mark.asyncio
    async def test_returns_501_when_cloudinary_unconfigured(
        self, mock_db, make_request, make_organizer
    ):
        from fastapi import HTTPException
        from app.routers.organizer_events import upload_event_image

        mock_db.scalar.return_value = 0
        organizer = make_organizer(organizer_id=5)
        file = self._fake_upload()

        with patch("app.routers.organizer_events.settings") as mock_settings:
            mock_settings.CLOUDINARY_CLOUD_NAME = ""
            with pytest.raises(HTTPException) as exc_info:
                await upload_event_image(
                    make_request(method="POST", path="/organizer/events/image"),
                    file,
                    organizer,
                    mock_db,
                )
        assert exc_info.value.status_code == http.HTTPStatus.NOT_IMPLEMENTED

    @pytest.mark.asyncio
    async def test_successful_upload_returns_secure_url(
        self, mock_db, make_request, make_organizer
    ):
        from app.models.models import OrganizerImageUpload
        from app.routers.organizer_events import upload_event_image

        mock_db.scalar.return_value = 0
        organizer = make_organizer(organizer_id=5)
        file = self._fake_upload()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "secure_url": "https://res.cloudinary.com/demo/image/upload/photo.png"
        }

        with (
            patch("app.routers.organizer_events.settings") as mock_settings,
            patch(
                "app.routers.organizer_events.http_post",
                new_callable=AsyncMock,
                return_value=mock_response,
            ) as mock_post,
        ):
            mock_settings.CLOUDINARY_CLOUD_NAME = "demo"
            mock_settings.CLOUDINARY_API_KEY = "key123"
            mock_settings.CLOUDINARY_API_SECRET = "secret456"

            result = await upload_event_image(
                make_request(method="POST", path="/organizer/events/image"),
                file,
                organizer,
                mock_db,
            )

        assert result == {
            "url": "https://res.cloudinary.com/demo/image/upload/photo.png"
        }
        mock_post.assert_awaited_once()
        _, kwargs = mock_post.call_args
        assert kwargs["data"]["api_key"] == "key123"
        assert "signature" in kwargs["data"]
        assert kwargs["data"]["signature_algorithm"] == "sha256"
        # Generated, not file.filename — M-3 in the OWASP audit: the upload
        # filename is attacker-controlled text otherwise crossing a service
        # boundary unchanged, and nothing downstream reads it.
        uploaded_filename = kwargs["files"]["file"][0]
        assert uploaded_filename != "photo.png"
        assert uploaded_filename.endswith(".png")
        # L5: a successful upload is recorded so the daily cap can count it.
        added = mock_db.add.call_args[0][0]
        assert isinstance(added, OrganizerImageUpload)
        assert added.organizer_id == 5
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_upload_failure_returns_502(self, mock_db, make_request, make_organizer):
        import httpx
        from fastapi import HTTPException
        from app.routers.organizer_events import upload_event_image

        mock_db.scalar.return_value = 0
        organizer = make_organizer(organizer_id=5)
        file = self._fake_upload()

        with (
            patch("app.routers.organizer_events.settings") as mock_settings,
            patch(
                "app.routers.organizer_events.http_post",
                new_callable=AsyncMock,
                side_effect=httpx.HTTPError("boom"),
            ),
        ):
            mock_settings.CLOUDINARY_CLOUD_NAME = "demo"
            mock_settings.CLOUDINARY_API_KEY = "key123"
            mock_settings.CLOUDINARY_API_SECRET = "secret456"

            with pytest.raises(HTTPException) as exc_info:
                await upload_event_image(
                    make_request(method="POST", path="/organizer/events/image"),
                    file,
                    organizer,
                    mock_db,
                )
        assert exc_info.value.status_code == http.HTTPStatus.BAD_GATEWAY

    @pytest.mark.asyncio
    async def test_malformed_json_response_returns_502_not_500(
        self, mock_db, make_request, make_organizer
    ):
        """A 200 response whose body isn't valid JSON (e.g. Cloudinary returning
        an HTML error page) must translate to the same clean 502, not an
        uncaught exception."""
        from fastapi import HTTPException
        from app.routers.organizer_events import upload_event_image

        mock_db.scalar.return_value = 0
        organizer = make_organizer(organizer_id=5)
        file = self._fake_upload()

        mock_response = MagicMock()
        mock_response.json.side_effect = ValueError("not JSON")

        with (
            patch("app.routers.organizer_events.settings") as mock_settings,
            patch(
                "app.routers.organizer_events.http_post",
                new_callable=AsyncMock,
                return_value=mock_response,
            ),
        ):
            mock_settings.CLOUDINARY_CLOUD_NAME = "demo"
            mock_settings.CLOUDINARY_API_KEY = "key123"
            mock_settings.CLOUDINARY_API_SECRET = "secret456"

            with pytest.raises(HTTPException) as exc_info:
                await upload_event_image(
                    make_request(method="POST", path="/organizer/events/image"),
                    file,
                    organizer,
                    mock_db,
                )
        assert exc_info.value.status_code == http.HTTPStatus.BAD_GATEWAY


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
            title_localized={"et": "Pealkiri", "en": "Title"},
            description_localized={"et": "Kirjeldus"},
            important_info_localized=None,
        )
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[event]))

        result = await list_own_events(
            make_request(path="/organizer/events"), 20, 0, organizer, mock_db
        )

        assert result["events"][0]["status"] == EVENT_STATUS_CLASSIFIED
        assert result["events"][0]["needs_review"] is True
        assert result["events"][0]["title_localized"] == {"et": "Pealkiri", "en": "Title"}
        assert result["events"][0]["description_localized"] == {"et": "Kirjeldus"}
        assert result["events"][0]["important_info_localized"] is None


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
    async def test_deletes_auto_resolves_open_reports(
        self, mock_db, make_request, make_organizer, make_report, make_user
    ):
        """Self-delete must auto-resolve the event's open reports through
        the shared resolve_open_reports() helper (issue #125), firing one
        reporter-outcome email per resolved report (issue #127)."""
        from app.routers.organizer_events import delete_own_event

        organizer = make_organizer(organizer_id=5)
        event = _fake_event(submitted_by_organizer_id=5)
        report = make_report(report_id=1, event_id=10, status="open")
        reporter = make_user(user_id=report.user_id)
        mock_db.scalar.return_value = event
        mock_db.execute.return_value.scalars.return_value.all.return_value = [report]
        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[reporter]))
        mock_db.commit = AsyncMock()

        with patch(
            "app.routers.utils.send_report_outcome_email", new=AsyncMock()
        ) as mock_send:
            await delete_own_event(
                10,
                make_request(method="DELETE", path="/organizer/events/10"),
                organizer,
                mock_db,
            )

        assert report.status == "resolved"
        assert report.resolution_note == "auto-resolved: event cancelled"
        mock_send.assert_awaited_once_with(
            reporter.email, event, "auto-resolved: event cancelled", reporter.locale
        )

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


class TestSubmitEventBodyValidation:
    """P1-3: over-length venue_name/currency used to reach the DB and raise
    asyncpg.StringDataRightTruncation (an unhandled 500) instead of failing
    Pydantic validation with a 422. Also covers the new price/date ordering
    and non-negative-price checks."""

    def _base_kwargs(self, **overrides):
        kwargs = dict(
            title="Test Event",
            starts_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        kwargs.update(overrides)
        return kwargs

    def test_valid_body_accepted(self):
        from app.routers.organizer_events import SubmitEventBody

        body = SubmitEventBody(**self._base_kwargs())
        assert body.title == "Test Event"

    def test_venue_name_over_column_width_rejected(self):
        from app.routers.organizer_events import SubmitEventBody

        with pytest.raises(ValidationError):
            SubmitEventBody(
                **self._base_kwargs(venue_name="x" * (ORGANIZER_VENUE_NAME_MAX_LEN + 1))
            )

    def test_currency_over_column_width_rejected(self):
        from app.routers.organizer_events import SubmitEventBody

        with pytest.raises(ValidationError):
            SubmitEventBody(
                **self._base_kwargs(currency="x" * (ORGANIZER_CURRENCY_MAX_LEN + 1))
            )

    def test_negative_price_min_rejected(self):
        from app.routers.organizer_events import SubmitEventBody

        with pytest.raises(ValidationError):
            SubmitEventBody(**self._base_kwargs(price_min=-1.0))

    def test_price_min_greater_than_price_max_rejected(self):
        from app.routers.organizer_events import SubmitEventBody

        with pytest.raises(ValidationError):
            SubmitEventBody(**self._base_kwargs(price_min=20.0, price_max=10.0))

    def test_ends_at_before_starts_at_rejected(self):
        from app.routers.organizer_events import SubmitEventBody

        starts_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
        with pytest.raises(ValidationError):
            SubmitEventBody(
                **self._base_kwargs(
                    starts_at=starts_at, ends_at=starts_at - timedelta(hours=1)
                )
            )

    def test_ends_at_after_starts_at_accepted(self):
        from app.routers.organizer_events import SubmitEventBody

        starts_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
        body = SubmitEventBody(
            **self._base_kwargs(
                starts_at=starts_at, ends_at=starts_at + timedelta(hours=1)
            )
        )
        assert body.ends_at is not None


class TestPatchEventBodyValidation:
    def test_price_min_greater_than_price_max_rejected(self):
        from app.routers.organizer_events import PatchEventBody

        with pytest.raises(ValidationError):
            PatchEventBody(price_min=20.0, price_max=10.0)

    def test_ends_at_before_starts_at_rejected_when_both_present(self):
        from app.routers.organizer_events import PatchEventBody

        starts_at = datetime(2026, 6, 1, tzinfo=timezone.utc)
        with pytest.raises(ValidationError):
            PatchEventBody(
                starts_at=starts_at, ends_at=starts_at - timedelta(hours=1)
            )

    def test_only_ends_at_present_is_not_cross_checked(self):
        """A patch touching only ends_at can't be validated against the
        existing row's starts_at without a DB round-trip — accepted here,
        left to the create-time invariant."""
        from app.routers.organizer_events import PatchEventBody

        body = PatchEventBody(ends_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
        assert body.ends_at is not None

    def test_venue_name_over_column_width_rejected(self):
        from app.routers.organizer_events import PatchEventBody

        with pytest.raises(ValidationError):
            PatchEventBody(venue_name="x" * (ORGANIZER_VENUE_NAME_MAX_LEN + 1))
