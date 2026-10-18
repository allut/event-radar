"""The report-notify subject for a report on a promoted event (#612)."""

from unittest.mock import MagicMock

import httpx
import pytest

from app.email import report_notify, resend


@pytest.mark.asyncio
async def test_promoted_event_marks_the_subject(patch_client, monkeypatch, make_event):
    monkeypatch.setattr(report_notify.settings, "RESEND_API_KEY", "re_key")
    post = patch_client(resend, MagicMock(status_code=httpx.codes.OK, text="ok"))

    await report_notify.send_report_notification(
        make_event(7, title="Gig"), "spam_or_scam", None, False, 1, "r@example.com", is_promoted=True
    )

    assert post.call_args.kwargs["json"]["subject"] == "New report on a promoted event — Gig"


@pytest.mark.asyncio
async def test_unpromoted_subject_is_unchanged(patch_client, monkeypatch, make_event):
    monkeypatch.setattr(report_notify.settings, "RESEND_API_KEY", "re_key")
    post = patch_client(resend, MagicMock(status_code=httpx.codes.OK, text="ok"))

    await report_notify.send_report_notification(
        make_event(7, title="Gig"), "spam_or_scam", None, False, 1, "r@example.com"
    )

    assert post.call_args.kwargs["json"]["subject"] == "New report — Gig"
