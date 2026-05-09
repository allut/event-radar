"""Tests for POST /feedback endpoint."""
import http
from unittest.mock import AsyncMock, MagicMock

from app.constants import DEFAULT_USER_LOCALE

import pytest


def _mock_db():
    db = AsyncMock()
    db.get = AsyncMock()
    db.scalar = AsyncMock()
    db.execute = AsyncMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


def _make_user(user_id: int = 1):
    u = MagicMock()
    u.id = user_id
    u.email = "test@example.com"
    u.locale = DEFAULT_USER_LOCALE
    return u


def _make_event(event_id: int = 10):
    e = MagicMock()
    e.id = event_id
    return e


class TestRecordFeedback:
    @pytest.mark.asyncio
    async def test_like_succeeds(self):
        from app.routers.feedback import record_feedback, FeedbackBody

        db = _mock_db()
        db.get.return_value = _make_event(10)
        user = _make_user()

        result = await record_feedback(
            body=FeedbackBody(event_id=10, signal="like"),
            current_user=user,
            db=db,
        )
        assert result == {"ok": True}
        db.add.assert_called_once()
        db.execute.assert_called_once()  # score invalidation
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_valid_signals_accepted(self):
        from app.constants import VALID_SIGNALS
        from app.routers.feedback import record_feedback, FeedbackBody

        for signal in VALID_SIGNALS:
            db = _mock_db()
            db.get.return_value = _make_event(1)
            user = _make_user()
            result = await record_feedback(
                body=FeedbackBody(event_id=1, signal=signal),
                current_user=user,
                db=db,
            )
            assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_invalid_signal_raises_422(self):
        from fastapi import HTTPException
        from app.routers.feedback import record_feedback, FeedbackBody

        db = _mock_db()
        db.get.return_value = _make_event(1)
        user = _make_user()

        with pytest.raises(HTTPException) as exc_info:
            await record_feedback(
                body=FeedbackBody(event_id=1, signal="thumbs_sideways"),
                current_user=user,
                db=db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_unknown_event_raises_404(self):
        from fastapi import HTTPException
        from app.routers.feedback import record_feedback, FeedbackBody

        db = _mock_db()
        db.get.return_value = None  # event not found

        with pytest.raises(HTTPException) as exc_info:
            await record_feedback(
                body=FeedbackBody(event_id=999, signal="like"),
                current_user=_make_user(),
                db=db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.NOT_FOUND

    @pytest.mark.asyncio
    async def test_score_cache_invalidated(self):
        """Ensure a DELETE is issued to user_event_scores."""
        from app.routers.feedback import record_feedback, FeedbackBody

        db = _mock_db()
        db.get.return_value = _make_event(5)
        user = _make_user(user_id=3)

        await record_feedback(
            body=FeedbackBody(event_id=5, signal="dislike"),
            current_user=user,
            db=db,
        )
        # execute() is used for the DELETE statement
        db.execute.assert_called_once()
