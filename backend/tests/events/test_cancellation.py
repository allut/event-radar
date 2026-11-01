"""Unit tests for app.events.cancellation."""

import pytest

from app.events.cancellation import resolve_open_reports, send_report_resolution_emails


class TestResolveOpenReports:
    """resolve_open_reports() only mutates EventReport rows — it must not
    itself send any email (issue #127's send_report_resolution_emails is a
    separate, explicitly post-commit step; see its own tests below)."""

    @pytest.mark.asyncio
    async def test_does_not_send_email(self, mock_db, make_event, make_report):
        from unittest.mock import AsyncMock, patch

        event = make_event(42)
        report = make_report(report_id=1, user_id=1, event_id=42, status="open")
        mock_db.execute.return_value.scalars.return_value.all.return_value = [report]

        with patch(
            "app.events.cancellation.send_report_outcome_email", new=AsyncMock()
        ) as mock_send:
            resolved = await resolve_open_reports(mock_db, event, "Reviewed.")

        assert len(resolved) == 1
        mock_send.assert_not_awaited()


class TestSendReportResolutionEmails:
    """send_report_resolution_emails() fires one reporter-outcome email per
    resolved report (issue #127) — fan-out to multiple reporters, and a
    per-report swallow-and-log on send failure so one bad address can't
    block the rest. Callers invoke this AFTER their own db.commit()."""

    @pytest.mark.asyncio
    async def test_fans_out_one_email_per_reporter(
        self, mock_db, make_event, make_report, make_user
    ):
        from unittest.mock import AsyncMock, MagicMock, patch

        event = make_event(42)
        report_a = make_report(report_id=1, user_id=1, event_id=42, status="open")
        report_b = make_report(report_id=2, user_id=2, event_id=42, status="open")
        report_a.status = report_b.status = "resolved"
        user_a = make_user(user_id=1)
        user_b = make_user(user_id=2)
        user_b.email = "other@example.com"

        mock_db.scalars.return_value = MagicMock(
            all=MagicMock(return_value=[user_a, user_b])
        )

        with patch(
            "app.events.cancellation.send_report_outcome_email", new=AsyncMock()
        ) as mock_send:
            await send_report_resolution_emails(
                mock_db, event, [report_a, report_b], "Reviewed."
            )

        assert mock_send.await_count == 2
        sent_to = {call.args[0] for call in mock_send.await_args_list}
        assert sent_to == {user_a.email, "other@example.com"}

    @pytest.mark.asyncio
    async def test_no_reports_short_circuits(self, mock_db, make_event):
        from unittest.mock import AsyncMock, patch

        with patch(
            "app.events.cancellation.send_report_outcome_email", new=AsyncMock()
        ) as mock_send:
            await send_report_resolution_emails(mock_db, make_event(42), [], "note")

        mock_send.assert_not_awaited()
        mock_db.scalars.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_failure_is_swallowed_and_logged(
        self, mock_db, make_event, make_report, make_user, caplog
    ):
        import logging
        from unittest.mock import AsyncMock, MagicMock, patch

        event = make_event(42)
        report = make_report(report_id=1, user_id=1, event_id=42, status="resolved")
        user = make_user(user_id=1)

        mock_db.scalars.return_value = MagicMock(all=MagicMock(return_value=[user]))

        with (
            patch(
                "app.events.cancellation.send_report_outcome_email",
                new=AsyncMock(side_effect=RuntimeError("boom")),
            ),
            caplog.at_level(logging.ERROR),
        ):
            await send_report_resolution_emails(mock_db, event, [report], "Reviewed.")

        assert any(
            "Failed to send report outcome email" in r.getMessage()
            for r in caplog.records
        )

    @pytest.mark.asyncio
    async def test_one_uncaught_failure_does_not_abort_the_batch(
        self, mock_db, make_event, make_report, make_user
    ):
        """A failure _send_one's own try/except doesn't catch (anything
        broader than Exception, e.g. a BaseException) must not cancel the
        other in-flight sends — asyncio.gather(..., return_exceptions=True)
        is what guarantees that."""
        from unittest.mock import AsyncMock, MagicMock, patch

        class _SimulatedFatalError(BaseException):
            pass

        event = make_event(42)
        report_a = make_report(report_id=1, user_id=1, event_id=42, status="resolved")
        report_b = make_report(report_id=2, user_id=2, event_id=42, status="resolved")
        user_a = make_user(user_id=1)
        user_b = make_user(user_id=2)
        user_b.email = "other@example.com"

        mock_db.scalars.return_value = MagicMock(
            all=MagicMock(return_value=[user_a, user_b])
        )

        async def _raise_for_a(email: str, *args: object, **kwargs: object) -> None:
            if email == user_a.email:
                raise _SimulatedFatalError("boom")

        with patch(
            "app.events.cancellation.send_report_outcome_email",
            new=AsyncMock(side_effect=_raise_for_a),
        ) as mock_send:
            await send_report_resolution_emails(
                mock_db, event, [report_a, report_b], "Reviewed."
            )

        assert mock_send.await_count == 2
