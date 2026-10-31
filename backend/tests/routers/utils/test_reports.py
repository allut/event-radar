"""Unit tests for app.routers.utils.reports."""
import pytest
from fastapi import HTTPException


class TestReportReasonTaxonomy:
    @pytest.mark.parametrize(
        "reason",
        [
            "spam_or_scam",
            "sexual_or_explicit",
            "not_an_event",
            "hateful_or_violent",
            "misleading_info",
            "event_ended_or_cancelled",
            "wrong_location",
            "other",
        ],
    )
    def test_every_offered_reason_is_accepted(self, reason):
        from app.routers.utils.reports import validate_report_reason

        validate_report_reason(reason)

    def test_error_lists_exactly_the_offered_reasons(self):
        from app.routers.utils.reports import validate_report_reason

        with pytest.raises(HTTPException) as exc_info:
            validate_report_reason("not_a_real_reason")
        for reason in ["spam_or_scam", "wrong_location", "other"]:
            assert f"'{reason}'" in exc_info.value.detail
        assert exc_info.value.detail.count("'") == 2 * 8
