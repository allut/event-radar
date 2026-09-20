"""Tests for GET /feed and GET /events/{id} endpoints."""
import http
from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.constants import TALLINN_TZ


# ---------------------------------------------------------------------------
# GET /feed
# ---------------------------------------------------------------------------


class TestGetFeed:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_feed_built(self, mock_db, make_user, make_request):
        from app.routers.feed import get_feed

        mock_db.scalar.return_value = None  # no DailyFeed row
        user = make_user()

        result = await get_feed(request=make_request(), current_user=user, db=mock_db)

        assert result["events"] == []
        assert result["built_at"] is None
        assert "feed_date" in result

    @pytest.mark.asyncio
    async def test_returns_events_in_feed_order(self, mock_db, make_user, make_event, make_request):
        from app.routers.feed import get_feed

        feed = MagicMock()
        feed.event_ids = [10, 20]
        feed.built_at = datetime(2026, 5, 10, 6, 0, 0, tzinfo=timezone.utc)
        mock_db.scalar.return_value = feed

        event10 = make_event(10)
        event20 = make_event(20)
        scalars_result = MagicMock()
        scalars_result.all.return_value = [event10, event20]
        mock_db.scalars.return_value = scalars_result

        user = make_user()
        result = await get_feed(request=make_request(), current_user=user, db=mock_db)

        assert len(result["events"]) == 2
        assert result["events"][0]["id"] == 10
        assert result["events"][1]["id"] == 20
        assert result["built_at"] is not None

    @pytest.mark.asyncio
    async def test_falls_back_to_prior_feed_when_none_today(
        self, mock_db, make_user, make_event, make_request
    ):
        from app.routers.feed import get_feed

        prior_feed = MagicMock()
        prior_feed.event_ids = [10]
        prior_feed.feed_date = date(2026, 5, 9)
        prior_feed.built_at = datetime(2026, 5, 9, 6, 0, 0, tzinfo=timezone.utc)
        # First db.scalar() call (today's lookup) -> None; second (fallback) -> prior_feed.
        mock_db.scalar.side_effect = [None, prior_feed]

        event10 = make_event(10)
        scalars_result = MagicMock()
        scalars_result.all.return_value = [event10]
        mock_db.scalars.return_value = scalars_result

        user = make_user()
        result = await get_feed(request=make_request(), current_user=user, db=mock_db)

        assert result["is_stale"] is True
        assert result["feed_date"] == "2026-05-09"
        assert len(result["events"]) == 1
        assert result["events"][0]["id"] == 10

    @pytest.mark.asyncio
    async def test_stale_feed_hydrating_to_nothing_returns_empty_not_stale(
        self, mock_db, make_user, make_request
    ):
        """The fallback feed's events all ended/were unpublished since it was
        built — public_event_filter() strips them all, hydrated events is
        empty. Must not report is_stale: true with no events."""
        from app.routers.feed import get_feed

        prior_feed = MagicMock()
        prior_feed.event_ids = [10]
        prior_feed.feed_date = date(2026, 5, 9)
        prior_feed.built_at = datetime(2026, 5, 9, 6, 0, 0, tzinfo=timezone.utc)
        mock_db.scalar.side_effect = [None, prior_feed]

        empty = MagicMock()
        empty.all.return_value = []
        mock_db.scalars.return_value = empty

        user = make_user()
        result = await get_feed(request=make_request(), current_user=user, db=mock_db)

        assert result["events"] == []
        assert result["is_stale"] is False
        assert result["built_at"] is None

    @pytest.mark.asyncio
    async def test_no_fallback_available_returns_empty_not_stale(
        self, mock_db, make_user, make_request
    ):
        from app.routers.feed import get_feed

        # Today's lookup -> None; fallback lookup -> also None.
        mock_db.scalar.side_effect = [None, None]

        user = make_user()
        result = await get_feed(request=make_request(), current_user=user, db=mock_db)

        assert result["events"] == []
        assert result["is_stale"] is False

    @pytest.mark.asyncio
    async def test_todays_feed_present_is_not_stale(
        self, mock_db, make_user, make_event, make_request
    ):
        from app.routers.feed import get_feed

        today = datetime.now(TALLINN_TZ).date()
        feed = MagicMock()
        feed.event_ids = [10]
        feed.feed_date = today
        feed.built_at = datetime(2026, 5, 10, 6, 0, 0, tzinfo=timezone.utc)
        mock_db.scalar.return_value = feed

        event10 = make_event(10)
        scalars_result = MagicMock()
        scalars_result.all.return_value = [event10]
        mock_db.scalars.return_value = scalars_result

        user = make_user()
        result = await get_feed(request=make_request(), current_user=user, db=mock_db)

        assert result["is_stale"] is False
        assert result["feed_date"] == today.isoformat()

    @pytest.mark.asyncio
    async def test_empty_event_ids_returns_empty(self, mock_db, make_user, make_request):
        from app.routers.feed import get_feed

        feed = MagicMock()
        feed.event_ids = []
        mock_db.scalar.return_value = feed

        user = make_user()
        result = await get_feed(request=make_request(), current_user=user, db=mock_db)

        assert result["events"] == []

    @pytest.mark.asyncio
    async def test_event_without_classification(self, mock_db, make_user, make_event, make_request):
        from app.routers.feed import get_feed

        feed = MagicMock()
        feed.event_ids = [10]
        feed.built_at = datetime(2026, 5, 10, 6, 0, 0, tzinfo=timezone.utc)
        mock_db.scalar.return_value = feed

        event = make_event(10)
        event.classification = None
        scalars_result = MagicMock()
        scalars_result.all.return_value = [event]
        mock_db.scalars.return_value = scalars_result

        user = make_user()
        result = await get_feed(request=make_request(), current_user=user, db=mock_db)

        assert result["events"][0]["categories"] == []
        assert result["events"][0]["why_go"] == []

    @pytest.mark.asyncio
    async def test_locale_query_param_overrides_persisted_locale(
        self, mock_db, make_user, make_event, make_request
    ):
        """?locale=et must win over the user's persisted EN locale — this is
        the fix for the cross-page stale-language bug (see the-language-
        switch-on-tender-snowflake plan)."""
        from app.routers.feed import get_feed

        feed = MagicMock()
        feed.event_ids = [10]
        feed.built_at = datetime(2026, 5, 10, 6, 0, 0, tzinfo=timezone.utc)
        mock_db.scalar.return_value = feed

        event = make_event(10, why_go_localized={"et": ["ET bullet"], "en": ["EN bullet"]})
        scalars_result = MagicMock()
        scalars_result.all.return_value = [event]
        mock_db.scalars.return_value = scalars_result

        user = make_user(locale="en")
        result = await get_feed(
            request=make_request(), locale="et", current_user=user, db=mock_db
        )

        assert result["events"][0]["why_go"] == ["ET bullet"]

    @pytest.mark.asyncio
    async def test_absent_locale_query_param_falls_back_to_persisted(
        self, mock_db, make_user, make_event, make_request
    ):
        from app.routers.feed import get_feed

        feed = MagicMock()
        feed.event_ids = [10]
        feed.built_at = datetime(2026, 5, 10, 6, 0, 0, tzinfo=timezone.utc)
        mock_db.scalar.return_value = feed

        event = make_event(10, why_go_localized={"et": ["ET bullet"], "en": ["EN bullet"]})
        scalars_result = MagicMock()
        scalars_result.all.return_value = [event]
        mock_db.scalars.return_value = scalars_result

        user = make_user(locale="en")
        result = await get_feed(
            request=make_request(), locale=None, current_user=user, db=mock_db
        )

        assert result["events"][0]["why_go"] == ["EN bullet"]

    @pytest.mark.asyncio
    async def test_event_query_excludes_explicit_events(self, mock_db, make_user, make_request):
        from app.routers.feed import get_feed

        feed = MagicMock()
        feed.event_ids = [10]
        feed.built_at = datetime(2026, 5, 10, 6, 0, 0, tzinfo=timezone.utc)
        mock_db.scalar.return_value = feed

        empty = MagicMock()
        empty.all.return_value = []
        mock_db.scalars.return_value = empty

        user = make_user()
        await get_feed(request=make_request(), current_user=user, db=mock_db)

        stmt = mock_db.scalars.call_args.args[0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "is_explicit" in compiled
        assert "is_non_event" in compiled
        assert "false" in compiled.lower()


# ---------------------------------------------------------------------------
# GET /events/{event_id}
# ---------------------------------------------------------------------------


class TestGetEvent:
    @pytest.mark.asyncio
    async def test_returns_event_detail(self, mock_db, make_event, make_request):
        from app.routers.events import get_event

        event = make_event(42)
        mock_db.scalar.return_value = event

        result = await get_event(event_id=42, request=make_request(), db=mock_db)

        assert result["id"] == 42
        assert result["title"] == "Test Event"
        assert result["categories"] == ["music"]
        assert result["why_go"] == ["Great DJs", "Intimate venue", "All night long"]

    @pytest.mark.asyncio
    async def test_returns_404_when_not_found(self, mock_db, make_request):
        from fastapi import HTTPException
        from app.routers.events import get_event

        mock_db.scalar.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await get_event(event_id=999, request=make_request(), db=mock_db)
        assert exc_info.value.status_code == http.HTTPStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_event_no_classification(self, mock_db, make_event, make_request):
        from app.routers.events import get_event

        event = make_event(1)
        event.classification = None
        mock_db.scalar.return_value = event

        result = await get_event(event_id=1, request=make_request(), db=mock_db)

        assert result["categories"] == []
        assert result["quality_score"] is None

    @pytest.mark.asyncio
    async def test_revoked_token_treated_as_anonymous(self, mock_db, make_event, make_request, make_user):
        """A token whose version no longer matches user.session_token_version
        (post logout-all) must not resolve the user — no locale/signal leak."""
        from app.routers.events import get_event
        from app.auth.tokens import generate_session_token

        event = make_event(42)
        mock_db.scalar.return_value = event

        user = make_user(user_id=7, locale="ru")
        user.session_token_version = 2
        mock_db.get.return_value = user

        stale_token = generate_session_token(7, 1)  # minted at version 1, user now at 2

        result = await get_event(
            event_id=42,
            request=make_request(),
            db=mock_db,
            session=stale_token,
        )

        # Revoked token must not resolve signals for this user — no leak of
        # my_signal (like/dislike/bookmark) after logout-all.
        assert result["my_signal"] is None
        mock_db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_query_excludes_explicit_events(self, mock_db, make_request):
        from app.routers.events import get_event
        from fastapi import HTTPException

        mock_db.scalar.return_value = None

        with pytest.raises(HTTPException):
            await get_event(event_id=42, request=make_request(), db=mock_db)

        stmt = mock_db.scalar.call_args.args[0]
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "is_explicit" in compiled
        assert "is_non_event" in compiled
        assert "false" in compiled.lower()

    @pytest.mark.asyncio
    async def test_locale_query_param_overrides_token_locale(
        self, mock_db, make_event, make_request, make_user
    ):
        """?locale=et must win even for an authenticated caller whose
        persisted locale is EN — same fix as GET /feed."""
        from app.routers.events import get_event
        from app.auth.tokens import generate_session_token

        event = make_event(42, why_go_localized={"et": ["ET bullet"], "en": ["EN bullet"]})
        mock_db.scalar.return_value = event

        user = make_user(user_id=7, locale="en")
        user.session_token_version = 1
        mock_db.get.return_value = user
        token = generate_session_token(7, 1)

        result = await get_event(
            event_id=42,
            request=make_request(),
            locale_query="et",
            db=mock_db,
            session=token,
        )

        assert result["why_go"] == ["ET bullet"]

    @pytest.mark.asyncio
    async def test_absent_locale_query_param_falls_back_to_token_locale(
        self, mock_db, make_event, make_request, make_user
    ):
        from app.routers.events import get_event
        from app.auth.tokens import generate_session_token

        event = make_event(42, why_go_localized={"et": ["ET bullet"], "en": ["EN bullet"]})
        mock_db.scalar.return_value = event

        user = make_user(user_id=7, locale="en")
        user.session_token_version = 1
        mock_db.get.return_value = user
        token = generate_session_token(7, 1)

        result = await get_event(
            event_id=42,
            request=make_request(),
            locale_query=None,
            db=mock_db,
            session=token,
        )

        assert result["why_go"] == ["EN bullet"]

    @pytest.mark.asyncio
    async def test_claim_status_unclaimed_when_never_ingested(self, mock_db, make_event, make_request):
        """No resolvable EventSource (an organizer's own direct submission,
        never scraped) -> always unclaimed, per claim_status_for_event's
        docstring (#414)."""
        from app.routers.events import get_event

        event = make_event(42)
        mock_db.scalar.side_effect = [event, None]

        result = await get_event(event_id=42, request=make_request(), db=mock_db)

        assert result["claim_status"] == "unclaimed"

    @pytest.mark.asyncio
    async def test_claim_status_pending(self, mock_db, make_event, make_request):
        from app.routers.events import get_event

        event = make_event(42)
        es = MagicMock(publisher_id=7, source=MagicMock())
        claim = MagicMock(status="pending")
        mock_db.scalar.side_effect = [event, es, claim]

        result = await get_event(event_id=42, request=make_request(), db=mock_db)

        assert result["claim_status"] == "pending"

    @pytest.mark.asyncio
    async def test_claim_status_claimed(self, mock_db, make_event, make_request):
        from app.routers.events import get_event

        event = make_event(42)
        es = MagicMock(publisher_id=7, source=MagicMock())
        claim = MagicMock(status="approved")
        mock_db.scalar.side_effect = [event, es, claim]

        result = await get_event(event_id=42, request=make_request(), db=mock_db)

        assert result["claim_status"] == "claimed"
