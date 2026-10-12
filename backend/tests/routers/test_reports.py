"""Tests for POST /reports."""
import http
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.constants.reports import REPORT_DETAIL_MAX_CHARS


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
    async def test_detail_too_long_rejected(self):
        """OWASP audit F16: ReportBody.detail now carries Field(max_length=...),
        so an oversized value is rejected during Pydantic validation — before
        it's fully materialized/parsed into the handler — rather than only by
        submit_report's own len() check after construction."""
        from app.routers.reports import ReportBody

        with pytest.raises(ValidationError):
            ReportBody(
                event_id=10,
                reason="other",
                detail="x" * (REPORT_DETAIL_MAX_CHARS + 1),
            )

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

    @pytest.mark.asyncio
    async def test_claimed_event_reports_through_ordinary_path(
        self, mock_db, make_user, make_event, make_request
    ):
        """Regression (#419): reporting a claimed event must be indistinguishable
        from reporting any other event — no claim-aware branch, no second/
        weaker moderation path."""
        from app.routers.reports import ReportBody, submit_report

        claimed_event = make_event(10)
        claimed_event.claim_status = "claimed"
        claimed_event.listed_by = "Tallinn Jazz Club"
        mock_db.scalar.return_value = claimed_event

        result = await submit_report(
            body=ReportBody(event_id=10, reason="spam_or_scam"),
            request=make_request(method="POST", path="/reports"),
            current_user=make_user(),
            db=mock_db,
        )

        assert result == {"ok": True}
        mock_db.execute.assert_called_once()
        mock_db.commit.assert_called_once()


class TestFirstReportNotification:
    @pytest.mark.asyncio
    async def test_first_open_report_sends_notification(
        self, mock_db, make_user, make_event, make_request
    ):
        from app.routers.reports import ReportBody, submit_report

        event = make_event(10)
        mock_db.scalar.side_effect = [event, 0]
        user = make_user()

        with patch(
            "app.routers.reports.send_report_notification", new=AsyncMock()
        ) as mock_send:
            await submit_report(
                body=ReportBody(event_id=10, reason="spam_or_scam"),
                request=make_request(method="POST", path="/reports"),
                current_user=user,
                db=mock_db,
            )

        mock_send.assert_awaited_once_with(
            event, "spam_or_scam", None, False, 1, user.email
        )

    @pytest.mark.asyncio
    async def test_subsequent_open_report_stays_silent(
        self, mock_db, make_user, make_event, make_request
    ):
        """A second report on an event that already has an open report must
        not re-notify — only the zero-to-one transition fires."""
        from app.routers.reports import ReportBody, submit_report

        mock_db.scalar.side_effect = [make_event(10), 1]

        with patch(
            "app.routers.reports.send_report_notification", new=AsyncMock()
        ) as mock_send:
            await submit_report(
                body=ReportBody(event_id=10, reason="spam_or_scam"),
                request=make_request(method="POST", path="/reports"),
                current_user=make_user(),
                db=mock_db,
            )

        mock_send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_editing_own_already_open_report_stays_silent(
        self, mock_db, make_user, make_event, make_request
    ):
        """Regression: a user editing their own already-open report (e.g. to
        fix a typo in `detail`) must not re-fire the notification — the
        upsert unconditionally sets status=open, so the gate must be read
        *before* the upsert, not derived from the post-commit open count."""
        from app.routers.reports import ReportBody, submit_report

        # pre_upsert_open_count == 1: this user's own row was already open.
        mock_db.scalar.side_effect = [make_event(10), 1]

        with patch(
            "app.routers.reports.send_report_notification", new=AsyncMock()
        ) as mock_send:
            await submit_report(
                body=ReportBody(
                    event_id=10, reason="spam_or_scam", detail="typo fix"
                ),
                request=make_request(method="POST", path="/reports"),
                current_user=make_user(),
                db=mock_db,
            )

        mock_send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_notification_failure_is_swallowed(
        self, mock_db, make_user, make_event, make_request
    ):
        """Send failures must not break the request — event_reports remains
        the durable record regardless of delivery."""
        from app.routers.reports import ReportBody, submit_report

        mock_db.scalar.side_effect = [make_event(10), 0]

        with patch(
            "app.routers.reports.send_report_notification",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            result = await submit_report(
                body=ReportBody(event_id=10, reason="spam_or_scam"),
                request=make_request(method="POST", path="/reports"),
                current_user=make_user(),
                db=mock_db,
            )

        assert result == {"ok": True}
