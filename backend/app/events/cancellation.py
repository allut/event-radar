"""Event cancellation + open-report resolution, shared by every path that
cancels an event: admin retract and takedown, organizer retract and
self-delete, and the detail-refetch sync's source-gone sweep."""

import asyncio
import logging
from datetime import datetime

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    EVENT_STATUS_CANCELLED,
    LOG_EVENT_EMAIL_SEND_FAILED,
    REPORT_EMAIL_SEND_CONCURRENCY,
    REPORT_STATUS_OPEN,
    REPORT_STATUS_RESOLVED,
    TALLINN_TZ,
)
from app.email.report_reporter import send_report_outcome_email
from app.email.resend import resend_http_client
from app.models.models import Event, EventReport, User

log = logging.getLogger(__name__)


async def resolve_open_reports(
    db: AsyncSession, event: Event, resolution_note: str
) -> list[EventReport]:
    """Close every REPORT_STATUS_OPEN row on ``event`` with
    ``resolution_note``, stamping ``resolved_at``. Shared by
    POST /admin/reports/{event_id}/resolve, .../takedown, and every path that
    cancels an event (admin retract, organizer retract, organizer
    self-delete) — see issue #125. Caller commits, then calls
    ``send_report_resolution_emails`` (issue #127) — deliberately NOT done
    here, since sending before the caller's commit could notify a reporter
    of a "resolved" status that a subsequent commit failure then rolls back.

    A single UPDATE...RETURNING (not a SELECT followed by in-Python mutation)
    so a report reopened concurrently (e.g. a fresh POST /reports upsert
    landing between this call and the caller's commit) can't be missed —
    the WHERE clause is evaluated atomically at execution time.
    """
    resolved_at = datetime.now(TALLINN_TZ)
    stmt = (
        update(EventReport)
        .where(
            EventReport.event_id == event.id,
            EventReport.status == REPORT_STATUS_OPEN,
        )
        .values(
            status=REPORT_STATUS_RESOLVED,
            resolution_note=resolution_note,
            resolved_at=resolved_at,
        )
        .returning(EventReport)
    )
    result = await db.execute(stmt)
    reports = list(result.scalars().all())
    # Belt-and-suspenders: reflect the update on the in-memory objects too,
    # in case the driver's RETURNING rows aren't merged into already
    # identity-mapped instances still referenced elsewhere in this request.
    for report in reports:
        report.status = REPORT_STATUS_RESOLVED
        report.resolution_note = resolution_note
        report.resolved_at = resolved_at
    return reports


async def send_report_resolution_emails(
    db: AsyncSession, event: Event, reports: list[EventReport], resolution_note: str
) -> None:
    """Send one reporter-outcome email per row in ``reports`` (the list
    ``resolve_open_reports``/``cancel_event_and_resolve_reports`` returned).
    Call this AFTER the caller's ``db.commit()`` — see issue #127 and
    ``resolve_open_reports``'s docstring for why the ordering matters. A
    per-report send failure is swallowed and logged; the ``resolved`` status
    transition (already committed) is the durable record."""
    if not reports:
        return
    user_ids = {report.user_id for report in reports}
    users = (await db.scalars(select(User).where(User.id.in_(user_ids)))).all()
    users_by_id = {u.id: u for u in users}

    semaphore = asyncio.Semaphore(REPORT_EMAIL_SEND_CONCURRENCY)

    async def _send_one(report: EventReport, http_client: httpx.AsyncClient) -> None:
        reporter = users_by_id.get(report.user_id)
        if reporter is None:
            return
        async with semaphore:
            try:
                await send_report_outcome_email(
                    reporter.email,
                    event,
                    resolution_note,
                    reporter.locale,
                    http_client=http_client,
                )
            except Exception:
                log.error(
                    "Failed to send report outcome email (report_id=%s, event_id=%s)",
                    report.id,
                    event.id,
                    exc_info=True,
                    extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
                )

    # return_exceptions=True is defence-in-depth, mirroring app/email/digest.py's
    # fan-out: _send_one already catches every send error and logs it, but
    # anything raised outside that try/except (e.g. a BaseException such as
    # CancelledError) would otherwise cancel every other in-flight reporter
    # email and propagate into the caller, after resolution has already
    # been committed.
    # One shared client for the whole fan-out (Big-O audit #5, item 2.7),
    # mirroring digest.py's Big-O audit M7 fix.
    async with resend_http_client() as http_client:
        await asyncio.gather(
            *(_send_one(report, http_client) for report in reports),
            return_exceptions=True,
        )


async def cancel_event_and_resolve_reports(
    db: AsyncSession, event: Event, cancellation_reason: str, resolution_note: str
) -> list[EventReport]:
    """Cancel ``event`` and resolve its open reports in one call — every
    cancellation path (admin retract, organizer retract, organizer
    self-delete, report takedown) must keep this pairing atomic so a
    cancelled event never leaves an open report behind. See issue #125.
    Caller commits.
    """
    event.status = EVENT_STATUS_CANCELLED
    event.cancellation_reason = cancellation_reason
    return await resolve_open_reports(db, event, resolution_note)
