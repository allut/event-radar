"""Admin endpoints — protected by the admin console session cookie."""


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


# ---------------------------------------------------------------------------
# Claims queue (#420): grant/decline an admin-review-routed claim, revoke an
# already-granted one. Distinct from /admin/submissions (organizer-trust
# review) and /admin/reports (content moderation) — a claim's grant/decline/
# revoke is its own decision shape. See CONTEXT.md's Event Claiming glossary
# and app/claims/lifecycle.py for the organizer-facing create/cancel/recheck
# endpoints this complements.
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Promotions (#600): JSON API for the cap strip, the list and the grant form.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Promotion lifecycle (#601): detail and commands. Each command runs under the
# cap lock, writes its audit row in the same transaction and returns the
# refreshed detail payload.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Promotion requests (#615): the queue, grant and decline. Under
# /promotion-requests (not /promotions/requests) so the int path of
# /promotions/{promotion_id} never shadows it.
# ---------------------------------------------------------------------------


