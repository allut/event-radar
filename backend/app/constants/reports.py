"""Event reports: reasons, statuses, detail limits, resolution notes, and report errors."""

from app._generated.shared_constants import (
    REPORT_DETAIL_MAX_CHARS as REPORT_DETAIL_MAX_CHARS,
)

# Report-an-inappropriate-event feature (event_reports table).
REPORT_REASON_SPAM_OR_SCAM = "spam_or_scam"
REPORT_REASON_SEXUAL_OR_EXPLICIT = "sexual_or_explicit"
REPORT_REASON_NOT_AN_EVENT = "not_an_event"
REPORT_REASON_HATEFUL_OR_VIOLENT = "hateful_or_violent"
REPORT_REASON_MISLEADING_INFO = "misleading_info"
REPORT_REASON_EVENT_ENDED_OR_CANCELLED = "event_ended_or_cancelled"
REPORT_REASON_WRONG_LOCATION = "wrong_location"
REPORT_REASON_OTHER = "other"
VALID_REPORT_REASONS = frozenset(
    {
        REPORT_REASON_SPAM_OR_SCAM,
        REPORT_REASON_SEXUAL_OR_EXPLICIT,
        REPORT_REASON_NOT_AN_EVENT,
        REPORT_REASON_HATEFUL_OR_VIOLENT,
        REPORT_REASON_MISLEADING_INFO,
        REPORT_REASON_EVENT_ENDED_OR_CANCELLED,
        REPORT_REASON_WRONG_LOCATION,
        REPORT_REASON_OTHER,
    }
)
REPORT_STATUS_OPEN = "open"
REPORT_STATUS_RESOLVED = "resolved"
VALID_REPORT_STATUSES = frozenset({REPORT_STATUS_OPEN, REPORT_STATUS_RESOLVED})

# Admin-authenticated but persisted to a Text column and emailed verbatim to
# every reporter (see app/email/report_reporter.py) — bounded so validation
# rejects an oversized note before it's stored/mailed rather than only being
# limited by the 10 MiB request-body ceiling (OWASP audit F16).
ADMIN_RESOLUTION_NOTE_MAX_CHARS = 2000

# System-generated resolution_note for the auto-resolve-on-cancellation cascade
# (utils.py::resolve_open_reports) — every path that cancels an event (admin
# retract, organizer retract, organizer self-delete, report takedown's own
# explicit note) reuses this so the reporter-outcome email (issue #127) has a
# consistent fallback message regardless of which door triggered it.
REPORT_AUTO_RESOLVE_NOTE = "auto-resolved: event cancelled"

# Concurrency cap when fanning out report-resolution outcome emails
# (send_report_resolution_emails) — bounded for the same reason as
# DIGEST_SEND_CONCURRENCY (Resend free-tier rate), and to keep a brigaded
# event's admin-resolution request from serializing 50-100 Resend round trips.
REPORT_EMAIL_SEND_CONCURRENCY: int = 8

# routers/reports.py
ERROR_INVALID_REPORT_REASON = "reason must be one of: {reasons}"
ERROR_REPORT_DETAIL_REQUIRED = (
    "detail is required when reason is 'other' or is_illegal_allegation is true."
)
ERROR_REPORT_DETAIL_TOO_LONG = "detail must be at most {max_chars} characters."
ERROR_RESOLUTION_NOTE_REQUIRED = "resolution_note is required."
