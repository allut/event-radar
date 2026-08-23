"""Tests for POST /reports."""
import http

import pytest
from fastapi import HTTPException

from app.constants import REPORT_DETAIL_MAX_CHARS


class TestSubmitReport:
    @pytest.mark.asyncio
    async def test_success(self, mock_db, make_user, make_event, make_request):
        from app.routers.reports import ReportBody, submit_report

        mock_db.scalar.return_value = make_event(10)

        result = await submit_report(
            body=ReportBody(event_id=10, reason="spam_or_scam"),
            request=make_request(method="POST", path="/reports"),
            current_user=make_user(),
            db=mock_db,
        )
        assert result == {"ok": True}
        mock_db.execute.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_uses_on_conflict(
        self, mock_db, make_user, make_event, make_request
    ):
        from app.routers.reports import ReportBody, submit_report

        mock_db.scalar.return_value = make_event(10)

        await submit_report(
            body=ReportBody(event_id=10, reason="spam_or_scam"),
            request=make_request(method="POST", path="/reports"),
            current_user=make_user(),
            db=mock_db,
        )
        from sqlalchemy.dialects import postgresql

        upsert_stmt = mock_db.execute.call_args.args[0]
        compiled = str(upsert_stmt.compile(dialect=postgresql.dialect()))
        assert "ON CONFLICT" in compiled.upper()

    @pytest.mark.asyncio
    async def test_on_conflict_reopens_resolved_report(
        self, mock_db, make_user, make_event, make_request
    ):
        """Regression: the ON CONFLICT SET clause must reset status/resolved_at/
        resolution_note back to open — otherwise re-reporting a resolved event
        would leave it permanently resolved and never show as `reported` again
        (see load_user_reported_events)."""
        from app.routers.reports import ReportBody, submit_report

        mock_db.scalar.return_value = make_event(10)

        await submit_report(
            body=ReportBody(event_id=10, reason="spam_or_scam"),
            request=make_request(method="POST", path="/reports"),
            current_user=make_user(),
            db=mock_db,
        )
        upsert_stmt = mock_db.execute.call_args.args[0]
        set_clause = dict(upsert_stmt._post_values_clause.update_values_to_set)
        assert set_clause["status"] == "open"
        assert set_clause["resolved_at"] is None
        assert set_clause["resolution_note"] is None

    @pytest.mark.asyncio
    async def test_invalid_reason_rejected(
        self, mock_db, make_user, make_event, make_request
    ):
        from app.routers.reports import ReportBody, submit_report

        with pytest.raises(HTTPException) as exc_info:
            await submit_report(
                body=ReportBody(event_id=10, reason="not_a_real_reason"),
                request=make_request(method="POST", path="/reports"),
                current_user=make_user(),
                db=mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.UNPROCESSABLE_ENTITY
        mock_db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_other_reason_requires_detail(
        self, mock_db, make_user, make_event, make_request
    ):
        from app.routers.reports import ReportBody, submit_report

        with pytest.raises(HTTPException) as exc_info:
            await submit_report(
                body=ReportBody(event_id=10, reason="other"),
                request=make_request(method="POST", path="/reports"),
                current_user=make_user(),
                db=mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_illegal_allegation_requires_detail(
        self, mock_db, make_user, make_event, make_request
    ):
        from app.routers.reports import ReportBody, submit_report

        with pytest.raises(HTTPException):
            await submit_report(
                body=ReportBody(
                    event_id=10,
                    reason="hateful_or_violent",
                    is_illegal_allegation=True,
                ),
                request=make_request(method="POST", path="/reports"),
                current_user=make_user(),
                db=mock_db,
            )

    @pytest.mark.asyncio
    async def test_other_reason_with_detail_succeeds(
        self, mock_db, make_user, make_event, make_request
    ):
        from app.routers.reports import ReportBody, submit_report

        mock_db.scalar.return_value = make_event(10)

        result = await submit_report(
            body=ReportBody(event_id=10, reason="other", detail="It's weird"),
            request=make_request(method="POST", path="/reports"),
            current_user=make_user(),
            db=mock_db,
        )
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_detail_too_long_rejected(
        self, mock_db, make_user, make_event, make_request
    ):
        from app.routers.reports import ReportBody, submit_report

        with pytest.raises(HTTPException) as exc_info:
            await submit_report(
                body=ReportBody(
                    event_id=10,
                    reason="other",
                    detail="x" * (REPORT_DETAIL_MAX_CHARS + 1),
                ),
                request=make_request(method="POST", path="/reports"),
                current_user=make_user(),
                db=mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.UNPROCESSABLE_ENTITY

    @pytest.mark.asyncio
    async def test_whitespace_only_detail_normalized_to_none(
        self, mock_db, make_user, make_event, make_request
    ):
        """Regression: whitespace-only detail on a reason that doesn't require
        it must persist as NULL, not an empty string."""
        from app.routers.reports import ReportBody, submit_report

        mock_db.scalar.return_value = make_event(10)

        await submit_report(
            body=ReportBody(event_id=10, reason="wrong_location", detail="   "),
            request=make_request(method="POST", path="/reports"),
            current_user=make_user(),
            db=mock_db,
        )
        upsert_stmt = mock_db.execute.call_args.args[0]
        insert_values = upsert_stmt.compile().params
        assert insert_values["detail"] is None

    @pytest.mark.asyncio
    async def test_non_public_event_returns_404(
        self, mock_db, make_user, make_request
    ):
        """public_event_filter() enforcement — draft/internal events must 404,
        not leak existence via a distinct error."""
        from app.routers.reports import ReportBody, submit_report

        mock_db.scalar.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            await submit_report(
                body=ReportBody(event_id=999, reason="spam_or_scam"),
                request=make_request(method="POST", path="/reports"),
                current_user=make_user(),
                db=mock_db,
            )
        assert exc_info.value.status_code == http.HTTPStatus.NOT_FOUND
        mock_db.execute.assert_not_called()
