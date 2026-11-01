"""Report-reason validation shared by the public and admin report routers."""

import logging

from fastapi import HTTPException, status

from app.constants.reports import (
    ERROR_INVALID_REPORT_REASON,
    VALID_REPORT_REASONS,
)

log = logging.getLogger(__name__)


def validate_report_reason(reason: str) -> None:
    """Shared by POST /reports and GET /admin/reports's ``reason`` filter —
    a single source of truth for the taxonomy check and its error message."""
    if reason not in VALID_REPORT_REASONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_INVALID_REPORT_REASON.format(reasons=sorted(VALID_REPORT_REASONS)),
        )
