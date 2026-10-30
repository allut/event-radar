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


class TestListFeedbackEventsPaging:
    """Spec #551: Saved events pages by offset with the full envelope on
    every request; there is no keyset cursor."""

    @staticmethod
    async def _list_page(mock_db, make_request, user, offset, rows, total, limit=2):
        """One saved-events page: `rows` from the page query, `total` from the COUNT."""
        from app.routers.feedback import list_feedback_events

        mock_db.scalar.return_value = total
        mock_db.execute.reset_mock()
        mock_db.execute.side_effect = [execute_rows(rows), execute_rows([])]
        return await list_feedback_events(
            request=make_request(method="GET", path="/feedback/events"),
            signal="bookmark",
            limit=limit,
            offset=offset,
            current_user=user,
            db=mock_db,
        )

    @pytest.mark.asyncio
    async def test_returns_paging_envelope_on_every_page(
        self, mock_db, make_user, make_event, make_request
    ):
        user = make_user()
        envelope = ("total", "limit", "offset", "has_more")
        first = await self._list_page(
            mock_db, make_request, user, 0,
            [(make_event(1), TS, 5), (make_event(2), TS, 4), (make_event(3), TS, 3)], 5,
        )
        middle = await self._list_page(
            mock_db, make_request, user, 2,
            [(make_event(3), TS, 3), (make_event(4), TS, 2), (make_event(5), TS, 1)], 5,
        )
        last = await self._list_page(
            mock_db, make_request, user, 4, [(make_event(5), TS, 1)], 5
        )

        assert {k: first[k] for k in envelope} == {
            "total": 5, "limit": 2, "offset": 0, "has_more": True,
        }
        assert {k: middle[k] for k in envelope} == {
            "total": 5, "limit": 2, "offset": 2, "has_more": True,
        }
        assert {k: last[k] for k in envelope} == {
            "total": 5, "limit": 2, "offset": 4, "has_more": False,
        }
        assert [e["id"] for e in middle["events"]] == [3, 4]
        for page in (first, middle, last):
            assert "next_cursor" not in page

    @pytest.mark.asyncio
    async def test_empty_list_has_zero_total(self, mock_db, make_user, make_request):
        result = await self._list_page(mock_db, make_request, make_user(), 0, [], None)
        assert (result["total"], result["has_more"], result["events"]) == (0, False, [])

    def test_endpoint_takes_no_cursor(self):
        import inspect
        from app.routers.feedback import list_feedback_events

        assert "cursor" not in inspect.signature(list_feedback_events).parameters

    @pytest.mark.asyncio
    async def test_pages_share_a_created_at_then_id_order(
        self, mock_db, make_user, make_request
    ):
        """Tie-breaker stability across pages: two signals given in the same
        instant must never swap between pages, so every page query orders by
        created_at desc then feedback id desc, and only OFFSET differs."""
        user = make_user()
        sqls = []
        for offset in (0, 2):
            await self._list_page(mock_db, make_request, user, offset, [], 3)
            stmt = mock_db.execute.call_args_list[0].args[0]
            sqls.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))

        for sql in sqls:
            assert "ORDER BY user_event_feedback.created_at DESC, user_event_feedback.id DESC" in sql
        assert "LIMIT 3 OFFSET 0" in sqls[0]
        assert "LIMIT 3 OFFSET 2" in sqls[1]
        assert sqls[0].replace("OFFSET 0", "OFFSET 2") == sqls[1]

    @pytest.mark.asyncio
    async def test_count_matches_the_page_filter(self, mock_db, make_user, make_request):
        await self._list_page(mock_db, make_request, make_user(), 4, [], 0)
        count_stmt = mock_db.scalar.call_args.args[0]
        sql = str(count_stmt.compile(compile_kwargs={"literal_binds": True}))
        assert "count(" in sql.lower()
        assert "user_event_feedback.signal = 'bookmark'" in sql


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
            current_user=make_user(),
            db=mock_db,
        )
        assert result["limit"] == 10
        assert result["offset"] == 0
        assert result["has_more"] is False
