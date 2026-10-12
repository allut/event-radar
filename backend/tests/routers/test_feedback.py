"""Tests for POST /feedback, DELETE /feedback/{event_id}, GET /feedback/events."""
import http
from datetime import datetime, timezone

import pytest

from app._generated.shared_constants import VALID_SIGNALS
from tests.routers.conftest import execute_rows


class TestRecordFeedback:
    @pytest.mark.asyncio
    async def test_like_succeeds(self, mock_db, make_user, make_event, make_request):
        from app.routers.feedback import record_feedback, FeedbackBody

        mock_db.scalar.return_value = make_event(10)
        user = make_user()

        result = await record_feedback(
            body=FeedbackBody(event_id=10, signal="like"),
            request=make_request(method="POST", path="/feedback"),
            current_user=user,
            db=mock_db,
        )
        assert result == {"ok": True}
        # Exactly one execute(): the upsert — no score-cache invalidation.
        assert mock_db.execute.call_count == 1
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_uses_on_conflict(self, mock_db, make_user, make_event, make_request):
        from app.routers.feedback import record_feedback, FeedbackBody

        mock_db.scalar.return_value = make_event(10)

        await record_feedback(
            body=FeedbackBody(event_id=10, signal="like"),
            request=make_request(method="POST", path="/feedback"),
            current_user=make_user(),
            db=mock_db,
        )
        from sqlalchemy.dialects import postgresql

        upsert_stmt = mock_db.execute.call_args_list[0].args[0]
        compiled = str(upsert_stmt.compile(dialect=postgresql.dialect()))
        assert "ON CONFLICT" in compiled.upper()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("signal", ["click_external", "view"])
    async def test_passive_signal_is_insert_do_nothing_not_upsert(
        self, signal, mock_db, make_user, make_event, make_request
    ):
        """Regression: click_external/view must never share the upsert path with
        like/dislike/bookmark — otherwise a ticket-link click would silently
        overwrite (destroy) an existing bookmark on the same event. They are
        inserted ON CONFLICT DO NOTHING so the one-row-per-day unique index
        (migration 0055, OWASP audit #9) turns a repeat into a no-op."""
        from sqlalchemy.dialects import postgresql

        from app.routers.feedback import record_feedback, FeedbackBody

        mock_db.scalar.return_value = make_event(10)

        await record_feedback(
            body=FeedbackBody(event_id=10, signal=signal),
            request=make_request(method="POST", path="/feedback"),
            current_user=make_user(),
            db=mock_db,
        )
        mock_db.add.assert_not_called()
        assert mock_db.execute.call_count == 1
        compiled = str(
            mock_db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
        ).upper()
        assert "ON CONFLICT DO NOTHING" in compiled
        assert "DO UPDATE" not in compiled
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("signal", sorted(VALID_SIGNALS))
    async def test_all_valid_signals_accepted(
        self, signal, mock_db, make_user, make_event, make_request
    ):
        from app.routers.feedback import record_feedback, FeedbackBody

        mock_db.scalar.return_value = make_event(1)

        result = await record_feedback(
            body=FeedbackBody(event_id=1, signal=signal),
            request=make_request(method="POST", path="/feedback"),
            current_user=make_user(),
            db=mock_db,
        )
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_invalid_signal_raises_422(self, mock_db, make_user, make_event, make_request):
        from fastapi import HTTPException
        from app.routers.feedback import record_feedback, FeedbackBody

        mock_db.scalar.return_value = make_event(1)
        user = make_user()

        with pytest.raises(HTTPException) as exc_info:
            await record_feedback(
                body=FeedbackBody(event_id=1, signal="thumbs_sideways"),
                request=make_request(method="POST", path="/feedback"),
                current_user=user,
                db=mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_unknown_event_raises_404(self, mock_db, make_user, make_request):
        from fastapi import HTTPException
        from app.routers.feedback import record_feedback, FeedbackBody

        mock_db.scalar.return_value = None  # event not found

        with pytest.raises(HTTPException) as exc_info:
            await record_feedback(
                body=FeedbackBody(event_id=999, signal="like"),
                request=make_request(method="POST", path="/feedback"),
                current_user=make_user(),
                db=mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.NOT_FOUND


class TestDeleteFeedback:
    @pytest.mark.asyncio
    async def test_delete_removes_signal(self, mock_db, make_user, make_request):
        from app.routers.feedback import delete_feedback

        result = await delete_feedback(
            event_id=10,
            request=make_request(method="DELETE", path="/feedback/10"),
            current_user=make_user(user_id=3),
            db=mock_db,
        )
        assert result == {"ok": True}
        # One execute() for the DELETE — nothing else to invalidate.
        assert mock_db.execute.call_count == 1
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_is_idempotent_no_404(self, mock_db, make_user, make_request):
        """No matching row is not an error — uncheck is idempotent."""
        from app.routers.feedback import delete_feedback

        result = await delete_feedback(
            event_id=999,
            request=make_request(method="DELETE", path="/feedback/999"),
            current_user=make_user(),
            db=mock_db,
        )
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_delete_scoped_to_preference_signals(self, mock_db, make_user, make_request):
        """DELETE must never remove view/click_external analytics history — only
        clear the preference (like/dislike/bookmark) row."""
        from app.routers.feedback import delete_feedback

        await delete_feedback(
            event_id=10,
            request=make_request(method="DELETE", path="/feedback/10"),
            current_user=make_user(),
            db=mock_db,
        )
        delete_stmt = mock_db.execute.call_args_list[0].args[0]
        compiled = str(delete_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "signal IN" in compiled


TS = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)


class TestListFeedbackEventsKeyset:
    @pytest.mark.asyncio
    async def test_has_more_emits_cursor_of_last_returned_row(
        self, mock_db, make_user, make_event, make_request
    ):
        from app.routers.feedback import list_feedback_events
        from app.routers.utils import decode_page_cursor

        mock_db.scalar.return_value = 3
        mock_db.execute.side_effect = [execute_rows([(make_event(1), TS, 30), (make_event(2), TS, 20), (make_event(3), TS, 10)]), execute_rows([])]

        result = await list_feedback_events(
            request=make_request(method="GET", path="/feedback/events"),
            signal="bookmark",
            limit=2,
            offset=0,
            cursor=None,
            current_user=make_user(),
            db=mock_db,
        )

        assert result["has_more"] is True
        assert [e["id"] for e in result["events"]] == [1, 2]
        assert decode_page_cursor(result["next_cursor"]) == (TS, 20)

    @pytest.mark.asyncio
    async def test_cursor_page_filters_keyset_skips_total(
        self, mock_db, make_user, make_event, make_request
    ):
        from app.routers.feedback import list_feedback_events
        from app.routers.utils import encode_page_cursor

        mock_db.execute.side_effect = [execute_rows([(make_event(1), TS, 5)]), execute_rows([])]

        result = await list_feedback_events(
            request=make_request(method="GET", path="/feedback/events"),
            signal="bookmark",
            limit=2,
            offset=40,
            cursor=encode_page_cursor(TS, 20),
            current_user=make_user(),
            db=mock_db,
        )

        sql = str(
            mock_db.execute.call_args_list[0].args[0].compile(
                compile_kwargs={"literal_binds": True}
            )
        )
        assert "(user_event_feedback.created_at, user_event_feedback.id) <" in sql
        assert "user_event_feedback.created_at DESC, user_event_feedback.id DESC" in sql
        mock_db.scalar.assert_not_called()
        assert result["total"] is None
        assert result["offset"] == 0
        assert result["next_cursor"] is None

    @pytest.mark.asyncio
    async def test_malformed_cursor_422(self, mock_db, make_user, make_request):
        from fastapi import HTTPException
        from app.routers.feedback import list_feedback_events

        with pytest.raises(HTTPException) as exc_info:
            await list_feedback_events(
                request=make_request(method="GET", path="/feedback/events"),
                signal="bookmark",
                limit=2,
                offset=0,
                cursor="garbage!!",
                current_user=make_user(),
                db=mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.UNPROCESSABLE_ENTITY


class TestListFeedbackEvents:
    @pytest.mark.asyncio
    async def test_returns_events_with_signal(self, mock_db, make_user, make_event, make_request):
        from app.routers.feedback import list_feedback_events

        mock_db.scalar.return_value = 2
        mock_db.execute.side_effect = [execute_rows([(make_event(1), TS, 11), (make_event(2), TS, 10)]), execute_rows([])]

        result = await list_feedback_events(
            request=make_request(method="GET", path="/feedback/events"),
            signal="bookmark",
            limit=24,
            offset=0,
            cursor=None,
            current_user=make_user(),
            db=mock_db,
        )
        assert result["total"] == 2
        assert len(result["events"]) == 2
        assert all(e["my_signal"] == "bookmark" for e in result["events"])

    @pytest.mark.asyncio
    @pytest.mark.parametrize("signal", ["view", "click_external"])
    async def test_analytics_signals_rejected(self, signal, mock_db, make_user, make_request):
        """view/click_external are valid POST signals but not listable — they can
        have multiple rows per event, so listing by them would return dupes."""
        from fastapi import HTTPException
        from app.routers.feedback import list_feedback_events

        with pytest.raises(HTTPException) as exc_info:
            await list_feedback_events(
                request=make_request(method="GET", path="/feedback/events"),
                signal=signal,
                current_user=make_user(),
                db=mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_invalid_signal_raises_422(self, mock_db, make_user, make_request):
        from fastapi import HTTPException
        from app.routers.feedback import list_feedback_events

        with pytest.raises(HTTPException) as exc_info:
            await list_feedback_events(
                request=make_request(method="GET", path="/feedback/events"),
                signal="nope",
                current_user=make_user(),
                db=mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_pagination_fields(self, mock_db, make_user, make_event, make_request):
        from app.routers.feedback import list_feedback_events

        mock_db.scalar.return_value = 1
        mock_db.execute.side_effect = [execute_rows([(make_event(1), TS, 11)]), execute_rows([])]

        result = await list_feedback_events(
            request=make_request(method="GET", path="/feedback/events"),
            signal="like",
            limit=10,
            offset=0,
            cursor=None,
            current_user=make_user(),
            db=mock_db,
        )
        assert result["limit"] == 10
        assert result["offset"] == 0
        assert result["has_more"] is False
