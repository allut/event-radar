"""Tests for POST /feedback endpoint."""
import http

import pytest


class TestRecordFeedback:
    @pytest.mark.asyncio
    async def test_like_succeeds(self, mock_db, make_user, make_event):
        from app.routers.feedback import record_feedback, FeedbackBody

        mock_db.get.return_value = make_event(10)
        user = make_user()

        result = await record_feedback(
            body=FeedbackBody(event_id=10, signal="like"),
            current_user=user,
            db=mock_db,
        )
        assert result == {"ok": True}
        mock_db.add.assert_called_once()
        mock_db.execute.assert_called_once()  # score invalidation
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_valid_signals_accepted(self, make_user, make_event):
        from app.constants import VALID_SIGNALS
        from app.routers.feedback import record_feedback, FeedbackBody
        from unittest.mock import AsyncMock, MagicMock

        for signal in VALID_SIGNALS:
            db = AsyncMock()
            db.get = AsyncMock(return_value=make_event(1))
            db.scalar = AsyncMock()
            db.scalars = AsyncMock()
            db.execute = AsyncMock()
            db.add = MagicMock()
            db.commit = AsyncMock()
            db.refresh = AsyncMock()
            result = await record_feedback(
                body=FeedbackBody(event_id=1, signal=signal),
                current_user=make_user(),
                db=db,
            )
            assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_invalid_signal_raises_422(self, mock_db, make_user, make_event):
        from fastapi import HTTPException
        from app.routers.feedback import record_feedback, FeedbackBody

        mock_db.get.return_value = make_event(1)
        user = make_user()

        with pytest.raises(HTTPException) as exc_info:
            await record_feedback(
                body=FeedbackBody(event_id=1, signal="thumbs_sideways"),
                current_user=user,
                db=mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_unknown_event_raises_404(self, mock_db, make_user):
        from fastapi import HTTPException
        from app.routers.feedback import record_feedback, FeedbackBody

        mock_db.get.return_value = None  # event not found

        with pytest.raises(HTTPException) as exc_info:
            await record_feedback(
                body=FeedbackBody(event_id=999, signal="like"),
                current_user=make_user(),
                db=mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_score_cache_invalidated(self, mock_db, make_user, make_event):
        """Ensure a DELETE is issued to user_event_scores."""
        from app.routers.feedback import record_feedback, FeedbackBody

        mock_db.get.return_value = make_event(5)
        user = make_user(user_id=3)

        await record_feedback(
            body=FeedbackBody(event_id=5, signal="dislike"),
            current_user=user,
            db=mock_db,
        )
        # execute() is used for the DELETE statement
        mock_db.execute.assert_called_once()
