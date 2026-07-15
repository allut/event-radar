"""Tests for POST /feedback, DELETE /feedback/{event_id}, GET /feedback/events."""
import http

import pytest

from app.constants import VALID_SIGNALS


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
        # One execute() for the upsert, one for score invalidation.
        assert mock_db.execute.call_count == 2
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
    async def test_click_external_appends_not_upserts(
        self, mock_db, make_user, make_event, make_request
    ):
        """Regression: click_external/view must never share the upsert path with
        like/dislike/bookmark — otherwise a ticket-link click would silently
        overwrite (destroy) an existing bookmark on the same event."""
        from app.routers.feedback import record_feedback, FeedbackBody

        mock_db.scalar.return_value = make_event(10)

        await record_feedback(
            body=FeedbackBody(event_id=10, signal="click_external"),
            request=make_request(method="POST", path="/feedback"),
            current_user=make_user(),
            db=mock_db,
        )
        # Analytics signal: appended via db.add(), never upserted via db.execute()
        # against the preference-signal index.
        mock_db.add.assert_called_once()
        added_row = mock_db.add.call_args.args[0]
        assert added_row.signal == "click_external"
        # Only the score-invalidation DELETE goes through execute() — no upsert.
        assert mock_db.execute.call_count == 1

    @pytest.mark.asyncio
    async def test_view_appends_not_upserts(
        self, mock_db, make_user, make_event, make_request
    ):
        from app.routers.feedback import record_feedback, FeedbackBody

        mock_db.scalar.return_value = make_event(10)

        await record_feedback(
            body=FeedbackBody(event_id=10, signal="view"),
            request=make_request(method="POST", path="/feedback"),
            current_user=make_user(),
            db=mock_db,
        )
        mock_db.add.assert_called_once()
        assert mock_db.execute.call_count == 1

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

    @pytest.mark.asyncio
    async def test_score_cache_invalidated(self, mock_db, make_user, make_event, make_request):
        """Ensure a second execute() call issues the DELETE against user_event_scores."""
        from app.routers.feedback import record_feedback, FeedbackBody

        mock_db.scalar.return_value = make_event(5)
        user = make_user(user_id=3)

        await record_feedback(
            body=FeedbackBody(event_id=5, signal="dislike"),
            request=make_request(method="POST", path="/feedback"),
            current_user=user,
            db=mock_db,
        )
        invalidate_stmt = mock_db.execute.call_args_list[1].args[0]
        compiled = str(invalidate_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "DELETE FROM user_event_scores" in compiled


class TestDeleteFeedback:
    @pytest.mark.asyncio
    async def test_delete_removes_signal(self, mock_db, make_user, make_request):
        from app.routers.feedback import delete_feedback

        user = make_user(user_id=3)

        result = await delete_feedback(
            event_id=10,
            request=make_request(method="DELETE", path="/feedback/10"),
            current_user=user,
            db=mock_db,
        )
        assert result == {"ok": True}
        # One execute() for the DELETE, one for score invalidation.
        assert mock_db.execute.call_count == 2
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


class TestListFeedbackEvents:
    @pytest.mark.asyncio
    async def test_returns_events_with_signal(self, mock_db, make_user, make_event, make_request):
        from app.routers.feedback import list_feedback_events

        mock_db.scalar.return_value = 2
        scalars_result = type("R", (), {"all": lambda self: [make_event(1), make_event(2)]})()
        mock_db.scalars.return_value = scalars_result

        result = await list_feedback_events(
            request=make_request(method="GET", path="/feedback/events"),
            signal="bookmark",
            limit=24,
            offset=0,
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
        scalars_result = type("R", (), {"all": lambda self: [make_event(1)]})()
        mock_db.scalars.return_value = scalars_result

        result = await list_feedback_events(
            request=make_request(method="GET", path="/feedback/events"),
            signal="like",
            limit=10,
            offset=0,
            current_user=make_user(),
            db=mock_db,
        )
        assert result["limit"] == 10
        assert result["offset"] == 0
        assert result["has_more"] is False
