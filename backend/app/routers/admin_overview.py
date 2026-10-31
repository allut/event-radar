"""Admin overview — pipeline counts and stats."""


from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select, true

from app.auth.dependencies import get_current_admin
from app._generated.shared_constants import (
    CLAIM_STATUS_PENDING,
)
from app.constants.events import (
    EVENT_STATUS_CANCELLED,
)
from app.constants.rate_limits import (
    RATE_LIMIT_ADMIN,
    RATE_LIMIT_BROWSE,
    RATE_LIMIT_SCOPE_ADMIN_READ,
)
from app.constants.reports import (
    REPORT_STATUS_OPEN,
)
from app.db import AsyncSessionLocal
from app.models.models import (
    Claim,
    Event,
    EventReport,
    Source,
)
from app.rate_limit import limiter
from app.events.queries import canonical_event_filter
router = APIRouter(prefix="/admin")


@router.get("/counts", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_BROWSE, scope=RATE_LIMIT_SCOPE_ADMIN_READ)
async def admin_counts(request: Request) -> dict:
    """Open-reports + pending-submissions + pending-claims counts for the
    admin console landing screen (issue #154, extended #420). Mirrors the
    filters admin_list_reports/admin_list_submissions/admin_list_claims use
    for their own totals, so the landing tiles match what those screens show."""
    async with AsyncSessionLocal() as db:
        open_reports = (
            await db.scalar(
                select(func.count(func.distinct(EventReport.event_id)))
                .select_from(EventReport)
                .join(Event, Event.id == EventReport.event_id)
                .where(
                    EventReport.status == REPORT_STATUS_OPEN,
                    Event.status != EVENT_STATUS_CANCELLED,
                )
            )
        ) or 0
        pending_submissions = (
            await db.scalar(
                select(func.count(Event.id)).where(
                    Event.needs_review == true(),
                    Event.status != EVENT_STATUS_CANCELLED,
                )
            )
        ) or 0
        pending_claims = (
            await db.scalar(
                select(func.count(Claim.id)).where(Claim.status == CLAIM_STATUS_PENDING)
            )
        ) or 0

    return {
        "open_reports": open_reports,
        "pending_submissions": pending_submissions,
        "pending_claims": pending_claims,
    }


@router.get("/stats", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_stats(request: Request) -> dict:
    """Aggregate counts used by checkpoint tests and manual monitoring."""
    async with AsyncSessionLocal() as db:
        total, canonical = (
            await db.execute(
                select(
                    func.count(Event.id),
                    func.count(Event.id).filter(canonical_event_filter()),
                ).where(Event.status != EVENT_STATUS_CANCELLED)
            )
        ).one()

        sources_total = (await db.scalar(select(func.count(Source.id)))) or 0
        sources_enabled = (
            await db.scalar(
                select(func.count(Source.id)).where(Source.enabled == true())
            )
        ) or 0

    return {
        "events": {"total": total, "canonical": canonical},
        "sources": {"total": sources_total, "enabled": sources_enabled},
    }
