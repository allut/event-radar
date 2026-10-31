"""Admin endpoints — protected by the admin console session cookie."""

import logging
from collections.abc import Awaitable, Callable
from datetime import date, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_admin
from app._generated.shared_constants import (
    ADMIN_CLAIMS_QUEUE_PAGE_SIZE,
    ADMIN_PROMOTIONS_PAGE_SIZE,
    ADMIN_PROMOTION_REQUESTS_PAGE_SIZE,
    ADMIN_REVIEW_QUEUE_PAGE_SIZE,
    CLAIM_KIND_PUBLISHER,
    CLAIM_STATUS_APPROVED,
    CLAIM_STATUS_PENDING,
    CLAIM_STATUS_REVOKED,
    PAGINATION_MAX_OFFSET,
    PROMOTION_DECLINE_REASON_MAX_CHARS,
)
from app.constants.admin import (
    ADMIN_ACTION_APPROVE_SUBMISSION,
    ADMIN_ACTION_DECLINE_CLAIM,
    ADMIN_ACTION_GRANT_CLAIM,
    ADMIN_ACTION_PROMOTION_CLEAR_RESTRICTION,
    ADMIN_ACTION_PROMOTION_COMPLAINT,
    ADMIN_ACTION_PROMOTION_EDIT,
    ADMIN_ACTION_PROMOTION_END,
    ADMIN_ACTION_PROMOTION_GRANT,
    ADMIN_ACTION_PROMOTION_REQUEST_DECLINE,
    ADMIN_ACTION_PROMOTION_REQUEST_GRANT,
    ADMIN_ACTION_PROMOTION_MARK_PAID,
    ADMIN_ACTION_PROMOTION_REFUND,
    ADMIN_ACTION_PROMOTION_REPOINT,
    ADMIN_ACTION_PROMOTION_VOID,
    ADMIN_ACTION_REVOKE_CLAIM,
    ADMIN_ACTION_RETRACT_SUBMISSION,
    ADMIN_CLAIMS_QUEUE_MAX_PAGE_SIZE,
    ADMIN_REVIEW_QUEUE_MAX_PAGE_SIZE,
)
from app.constants.claims import (
    ERROR_CLAIM_ALREADY_RESOLVED,
    ERROR_CLAIM_NOT_APPROVED,
    ERROR_CLAIM_NOT_FOUND,
    ERROR_CLAIM_QUEUE_INVALID_STATUS,
    ERROR_CLAIM_TARGET_ALREADY_APPROVED,
)
from app.constants.core import TALLINN_TZ
from app.constants.events import (
    EVENT_CANCELLATION_REASON_ADMIN_RETRACT,
    EVENT_STATUS_CANCELLED,
    EVENT_STATUS_CLASSIFIED,
)
from app.constants.http import HTTP_TIMEOUT_SECONDS
from app.constants.log_events import LOG_EVENT_EMAIL_SEND_FAILED
from app.constants.organizer import ERROR_SUBMISSION_NOT_FOUND
from app.constants.ranking import (
    PAGINATION_MIN_LIMIT,
    PAGINATION_MIN_OFFSET,
)
from app.constants.promotions import (
    PROMOTION_LIVE_CAP,
    ADMIN_PROMOTIONS_MAX_PAGE_SIZE,
    ERROR_PROMOTION_ADVERTISER_LEGAL_NAME_REQUIRED,
    ERROR_PROMOTION_FIELD_NOT_NULLABLE,
    ERROR_PROMOTION_INVALID_STATE,
    ERROR_PROMOTION_NOT_FOUND,
    ERROR_PROMOTION_NOTE_REQUIRED,
    ERROR_PROMOTION_SLOTS_STILL_ENABLED,
    PROMOTION_ADVERTISER_NAME_MAX_CHARS,
    PROMOTION_BILLING_EMAIL_MAX_CHARS,
    PROMOTION_COMPLAINANT_MAX_CHARS,
    PROMOTION_COMPLAINT_SOURCE_OTHER,
    PROMOTION_COMPLAINT_SOURCES,
    PROMOTION_COMPLAINT_TARGET,
    PROMOTION_END_REASON_FEATURE_WITHDRAWN,
    PROMOTION_WITHDRAWN_NOTE,
    PROMOTION_WITHDRAWN_REFUND_NOTE,
    ERROR_PROMOTION_REQUEST_INVALID_STATUS,
    ERROR_PROMOTION_REQUEST_NOT_FOUND,
    PROMOTION_ERROR_MESSAGES,
    PROMOTION_ERROR_REASON_REQUIRED,
    PROMOTION_CHECKOUT_ERROR_MESSAGES,
    PROMOTION_ERROR_REFUND_PROVIDER,
    PROMOTION_INVOICE_REFERENCE_MAX_LEN,
    PROMOTION_NOTE_MAX_CHARS,
    PROMOTION_NULLABLE_TEXT_FIELDS,
    PROMOTION_REGISTRY_CODE_MAX_LEN,
    PROMOTION_REQUEST_STATUS_PENDING,
    VALID_PROMOTION_REQUEST_STATUSES,
    VALID_PROMOTION_STATES,
)
from app.constants.rate_limits import (
    RATE_LIMIT_ADMIN,
    RATE_LIMIT_BROWSE,
    RATE_LIMIT_SCOPE_ADMIN_READ,
)
from app.constants.reports import (
    REPORT_AUTO_RESOLVE_NOTE,
    REPORT_STATUS_OPEN,
)
from app.claims.lifecycle import (
    approved_claim_exists,
    auto_decline_other_pending_claims,
    transition_pending_claim,
)
from app.claims.pinning import clear_claim_pins, representative_event_for_claim
from app.claims.target_resolution import ClaimTarget, bulk_resolve_publisher_events
from app.config import settings
from app.db import AsyncSessionLocal
from app.email.promotion_notice import (
    send_promotion_ended_email,
    send_promotion_request_declined_email,
    send_promotion_void_email,
)
from app.email.claim_resolution import send_claim_declined_email, send_claim_granted_email
from app.integrations.payments import PaymentGateway, PaymentProviderError
from app.integrations.providers import get_payment_gateway
from app.promotions.cap import cap_strip
from app.promotions.request_queue import list_requests as list_promotion_requests
from app.promotions.request_queue import pending_count as pending_request_count
from app.promotions.requests import (
    RequestNotFound,
    decline_request as decline_promotion_request,
    grant_request as grant_promotion_request,
)
from app.promotions.grant import (
    GrantRequest,
    PromotionRefused,
    grant_promotion,
    validate_grant,
)
from app.promotions.lifecycle import (
    clear_restriction,
    PromotionNotFound,
    edit_promotion,
    end_early,
    mark_paid,
    record_refund,
    repoint_promotion,
    void_promotion,
)
from app.promotions.views import (
    grant_context,
    daily_stats_table,
    list_promotions,
    promotion_detail,
    load_daily_stats,
    serialize_promotion,
    validation_payload,
)
from app.promotions.trust import trust_panel
from app.promotions.windows import now_tallinn, tallinn_today
from app.promotions.withdraw import WithdrawResult, withdraw_all, withdraw_promotion
from app.models.models import (
    Claim,
    Event,
    EventReport,
    Organizer,
    Promotion,
    Source,
)
from app.events.cancellation import (
    cancel_event_and_resolve_reports,
    send_report_resolution_emails,
)
from app.publish import publish_pending
from app.rate_limit import limiter
from app.routers.utils import (
    PromotionGrantBody,
    ResolutionBody,
    event_or_404,
    validated_resolution_note,
    claim_dns_record_name,
    log_admin_action,
    promotion_refusal,
    run_admin_job,
    serialize_event,
)
from app.events.localize import (
    resolve_title,
)
from app.events.queries import canonical_event_filter, select_events_with_classification

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")


@router.get("/submissions", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_BROWSE, scope=RATE_LIMIT_SCOPE_ADMIN_READ)
async def admin_list_submissions(
    request: Request,
    limit: int = Query(
        ADMIN_REVIEW_QUEUE_PAGE_SIZE,
        ge=PAGINATION_MIN_LIMIT,
        le=ADMIN_REVIEW_QUEUE_MAX_PAGE_SIZE,
    ),
    offset: int = Query(
        PAGINATION_MIN_OFFSET, ge=PAGINATION_MIN_OFFSET, le=PAGINATION_MAX_OFFSET
    ),
) -> dict:
    """Post-hoc review queue: organizer-submitted events still flagged
    ``needs_review`` (set on submit/edit — see routers/organizer_events.py).
    These are already live (auto-publish); this is eyeballing, not a gate.
    Excludes cancelled submissions — retract already clears ``needs_review``,
    but this filter is defense-in-depth so a cancelled row can never clutter
    the queue regardless of that flag's state. Most recently submitted/edited
    first.
    """
    async with AsyncSessionLocal() as db:
        queue_filter = (Event.needs_review == true(), Event.status != EVENT_STATUS_CANCELLED)
        # Exact total on every page (spec #551): the numbered pager derives
        # its last page and past-end clamp from it.
        total = (
            await db.scalar(select(func.count(Event.id)).where(*queue_filter))
        ) or 0

        # id breaks created_at ties, so offset paging never repeats or skips
        # rows that share a timestamp.
        stmt = (
            select_events_with_classification()
            .where(*queue_filter)
            .order_by(Event.created_at.desc(), Event.id.desc())
            .limit(limit + 1)
            .offset(offset)
        )
        events = list((await db.scalars(stmt)).all())
        has_more = len(events) > limit
        events = events[:limit]

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "events": [
            {
                **serialize_event(e),
                "status": e.status,
                "submitted_by_organizer_id": e.submitted_by_organizer_id,
                "created_at": e.created_at.isoformat(),
            }
            for e in events
        ],
    }


async def _submission_or_404(db: AsyncSession, event_id: int) -> Event:
    event = await db.get(Event, event_id)
    if event is None or event.submitted_by_organizer_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_SUBMISSION_NOT_FOUND
        )
    return event


@router.post(
    "/submissions/{event_id}/retract", dependencies=[Depends(get_current_admin)]
)
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_retract_submission(
    event_id: int, body: ResolutionBody, request: Request
) -> dict:
    """Cancel an organizer-submitted event (soft delete — mirrors organizer's
    own DELETE /organizer/events/{id}; events are never hard-deleted). Also
    clears needs_review so this resolves the review-queue entry outright —
    admin_list_submissions additionally excludes cancelled events regardless."""
    note = validated_resolution_note(body)

    async def _run() -> dict:
        async with AsyncSessionLocal() as db:
            event = await _submission_or_404(db, event_id)
            event.needs_review = False
            resolved = await cancel_event_and_resolve_reports(
                db,
                event,
                EVENT_CANCELLATION_REASON_ADMIN_RETRACT,
                REPORT_AUTO_RESOLVE_NOTE,
            )
            result = {"id": event.id, "status": event.status, "note": note}
            emit_admin_log = log_admin_action(
                db, ADMIN_ACTION_RETRACT_SUBMISSION, event_id, result
            )
            await db.commit()
            emit_admin_log()
            await send_report_resolution_emails(
                db, event, resolved, REPORT_AUTO_RESOLVE_NOTE
            )
            return result

    return await run_admin_job("Retract submission", _run())


@router.post(
    "/submissions/{event_id}/approve", dependencies=[Depends(get_current_admin)]
)
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_approve_submission(
    event_id: int, body: ResolutionBody, request: Request
) -> dict:
    """Clear needs_review — an admin has eyeballed the submission and it's fine
    as-is. Also flips the submitting organizer to ``verified`` (a first-time
    approval is what makes an organizer trusted going forward — see
    Organizer.verified / app/publish.py) and runs the publish gate so this
    event (and any other now-eligible backlog) goes live immediately rather
    than waiting for the next scheduled publish_pending pass."""
    note = validated_resolution_note(body)

    async def _run() -> dict:
        async with AsyncSessionLocal() as db:
            event = await _submission_or_404(db, event_id)
            event.needs_review = False
            if event.submitted_by_organizer_id is not None:
                organizer = await db.get(Organizer, event.submitted_by_organizer_id)
                # FAQ #first-event-not-live describes this behaviour — update the copy (all locales) if it changes
                if organizer is not None:
                    organizer.verified = True
            # organizer.verified flipping True can unlock this organizer's
            # whole backlog, not just this event: scope the gate to their
            # classified events, so the request never scans every classified
            # row. Anyone else's eligible rows wait for the scheduled pass.
            # Diagnostic breakdown is unused by this endpoint's response.
            backlog_ids = (
                await db.scalars(
                    select(Event.id).where(
                        Event.submitted_by_organizer_id == event.submitted_by_organizer_id,
                        Event.status == EVENT_STATUS_CLASSIFIED,
                    )
                )
            ).all()
            await publish_pending(
                db, event_ids=list({event.id, *backlog_ids}), diagnostics=False
            )
            result = {"id": event.id, "needs_review": event.needs_review, "note": note}
            emit_admin_log = log_admin_action(
                db, ADMIN_ACTION_APPROVE_SUBMISSION, event_id, result
            )
            await db.commit()
            emit_admin_log()
            return result

    return await run_admin_job("Approve submission", _run())


# ---------------------------------------------------------------------------
# Claims queue (#420): grant/decline an admin-review-routed claim, revoke an
# already-granted one. Distinct from /admin/submissions (organizer-trust
# review) and /admin/reports (content moderation) — a claim's grant/decline/
# revoke is its own decision shape. See CONTEXT.md's Event Claiming glossary
# and app/claims/lifecycle.py for the organizer-facing create/cancel/recheck
# endpoints this complements.
# ---------------------------------------------------------------------------

def _serialize_admin_claim(claim: Claim, event: Event | None) -> dict:
    """Evidence shown varies by mechanism, all derived from columns already
    on the row — no live re-verification: DNS-TXT/Piletilevi-promoter claims
    get the expected TXT record (claim_dns_record_name — shared with the
    organizer-facing pending screen's identical serializer), Fienta claims
    get the round-trip token, a piletilevi_mailbox claim (#428) gets the
    claimant's account email alongside the resolved contact
    (verification_contact) so the admin can see the match/mismatch, and a
    Series claim (always admin_review, and always carrying a justification —
    #428) or any other Publisher claim that fell back to admin_review gets
    claimant identity plus that justification text."""
    dns_record_name = claim_dns_record_name(
        claim.verification_mechanism, claim.verification_domain
    )
    return {
        "id": claim.id,
        "kind": claim.kind,
        "status": claim.status,
        "organizer": {
            "id": claim.organizer.id,
            "email": claim.organizer.email,
            "name": claim.organizer.name,
        },
        "publisher": (
            {"id": claim.publisher.id, "name": claim.publisher.name}
            if claim.publisher is not None
            else None
        ),
        "event_series_key": claim.event_series_key,
        "verification_mechanism": claim.verification_mechanism,
        "verification_domain": claim.verification_domain,
        "verification_contact": claim.verification_contact,
        "dns_record_name": dns_record_name,
        "proof_token": claim.proof_token,
        "justification": claim.justification,
        "event_id": event.id if event is not None else None,
        "event_title": event.title_orig if event is not None else None,
        "created_at": claim.created_at.isoformat(),
        "resolved_at": claim.resolved_at.isoformat() if claim.resolved_at else None,
    }


@router.get("/claims", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_BROWSE, scope=RATE_LIMIT_SCOPE_ADMIN_READ)
async def admin_list_claims(
    request: Request,
    status_filter: str = Query(CLAIM_STATUS_PENDING, alias="status"),
    limit: int = Query(
        ADMIN_CLAIMS_QUEUE_PAGE_SIZE,
        ge=PAGINATION_MIN_LIMIT,
        le=ADMIN_CLAIMS_QUEUE_MAX_PAGE_SIZE,
    ),
    offset: int = Query(
        PAGINATION_MIN_OFFSET, ge=PAGINATION_MIN_OFFSET, le=PAGINATION_MAX_OFFSET
    ),
) -> dict:
    """The Pending review / Granted tabs. Event evidence for the "Open full
    details" link is only resolved for Publisher-kind claims, bulk-loaded in
    two fixed queries regardless of page size (mirrors admin_list_reports'
    own bulk `.in_()` pattern) — a Series claim's event is a bounded scan
    (representative_event_for_claim), too expensive to run per row on a list
    endpoint, so event_id/event_title stay null for those and the frontend
    hides the link."""
    if status_filter not in (CLAIM_STATUS_PENDING, CLAIM_STATUS_APPROVED):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_CLAIM_QUEUE_INVALID_STATUS,
        )

    async with AsyncSessionLocal() as db:
        queue_filter = (Claim.status == status_filter,)
        # Exact total on every page (spec #551): the numbered pager derives
        # its last page and past-end clamp from it.
        total = (
            await db.scalar(select(func.count(Claim.id)).where(*queue_filter))
        ) or 0

        order_col = Claim.created_at if status_filter == CLAIM_STATUS_PENDING else Claim.resolved_at
        stmt = (
            select(Claim)
            .options(selectinload(Claim.organizer), selectinload(Claim.publisher))
            .where(*queue_filter)
            .order_by(order_col.desc(), Claim.id.desc())
            .limit(limit + 1)
            .offset(offset)
        )
        claims = list((await db.scalars(stmt)).all())
        has_more = len(claims) > limit
        claims = claims[:limit]

        # Bulk-load the representative event per Publisher-kind claim in this
        # page — two fixed queries total, never one per row (shared with the
        # #421 expiry-notification sweep via bulk_resolve_publisher_events).
        publisher_ids = {
            claim.publisher_id
            for claim in claims
            if claim.kind == CLAIM_KIND_PUBLISHER and claim.publisher_id is not None
        }
        event_by_publisher = await bulk_resolve_publisher_events(db, publisher_ids)

        rows = []
        for claim in claims:
            event = (
                event_by_publisher.get(claim.publisher_id)
                if claim.publisher_id is not None
                else None
            )
            rows.append(_serialize_admin_claim(claim, event))

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "claims": rows,
    }


async def _claim_or_404(db: AsyncSession, claim_id: int) -> Claim:
    claim = await db.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_CLAIM_NOT_FOUND)
    return claim


@router.post("/claims/{claim_id}/grant", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_grant_claim(claim_id: int, body: ResolutionBody, request: Request) -> dict:
    """Manually approve a pending claim — available for any pending claim
    regardless of mechanism, letting an admin override an inconclusive or
    failed automated check (e.g. a DNS-TXT lookup that hasn't propagated
    yet) as well as decide a genuine admin_review (Series) claim.

    Since #431 (multiple pending claims can coexist on the same target),
    this must apply the same guard/preemption as the organizer-facing
    auto-grant path (app.claims.lifecycle.create_claim/recheck_claim):
    reject with the same support-facing conflict when the target already
    has an *approved* claim (checked up front, and again via IntegrityError
    on the narrowed migration-0048 unique index for the race where another
    claim on this target was approved concurrently), and auto-decline every
    other still-pending sibling claim on the same target once this grant
    lands.
    """
    note = validated_resolution_note(body)

    async def _run() -> dict:
        async with AsyncSessionLocal() as db:
            claim = await _claim_or_404(db, claim_id)
            if claim.status != CLAIM_STATUS_PENDING:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=ERROR_CLAIM_ALREADY_RESOLVED,
                )
            target = ClaimTarget(claim.kind, claim.publisher_id, claim.event_series_key)
            if await approved_claim_exists(db, target):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=ERROR_CLAIM_TARGET_ALREADY_APPROVED,
                )
            try:
                transitioned = await transition_pending_claim(
                    db, claim, CLAIM_STATUS_APPROVED, datetime.now(TALLINN_TZ)
                )
                if not transitioned:
                    await db.rollback()
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=ERROR_CLAIM_ALREADY_RESOLVED,
                    )
                organizer = await db.get(Organizer, claim.organizer_id)
                event = await representative_event_for_claim(db, claim)
                result = {"id": claim.id, "status": claim.status, "note": note}
                emit_admin_log = log_admin_action(
                    db, ADMIN_ACTION_GRANT_CLAIM, claim_id, result
                )
                await db.commit()
            except IntegrityError:
                await db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=ERROR_CLAIM_TARGET_ALREADY_APPROVED,
                ) from None
            emit_admin_log()
            if organizer is not None:
                try:
                    await send_claim_granted_email(
                        organizer.email,
                        resolve_title(event, organizer.locale) if event else None,
                        note,
                        organizer.locale,
                    )
                except Exception:
                    log.error(
                        "Failed to send claim-granted email (claim_id=%s)",
                        claim_id,
                        exc_info=True,
                        extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
                    )
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
                await auto_decline_other_pending_claims(
                    db, client, target, claim.id, claim.organizer_id
                )
            return result

    return await run_admin_job("Grant claim", _run())


@router.post("/claims/{claim_id}/decline", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_decline_claim(claim_id: int, body: ResolutionBody, request: Request) -> dict:
    """Decline a pending claim — frees its Publisher/Series key immediately
    (CLAIM_ACTIVE_STATUSES excludes revoked, same as a self-cancel). Unlike
    POST .../revoke this never touches Event.pinned_fields: a pending claim
    was never granted, so nothing was ever pinned against it."""
    note = validated_resolution_note(body)

    async def _run() -> dict:
        async with AsyncSessionLocal() as db:
            claim = await _claim_or_404(db, claim_id)
            if claim.status != CLAIM_STATUS_PENDING:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=ERROR_CLAIM_ALREADY_RESOLVED,
                )
            if not await transition_pending_claim(
                db, claim, CLAIM_STATUS_REVOKED, datetime.now(TALLINN_TZ)
            ):
                await db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=ERROR_CLAIM_ALREADY_RESOLVED,
                )
            organizer = await db.get(Organizer, claim.organizer_id)
            event = await representative_event_for_claim(db, claim)
            result = {"id": claim.id, "status": claim.status, "note": note}
            emit_admin_log = log_admin_action(db, ADMIN_ACTION_DECLINE_CLAIM, claim_id, result)
            await db.commit()
            emit_admin_log()
            if organizer is not None:
                try:
                    await send_claim_declined_email(
                        organizer.email,
                        resolve_title(event, organizer.locale) if event else None,
                        note,
                        organizer.locale,
                    )
                except Exception:
                    log.error(
                        "Failed to send claim-declined email (claim_id=%s)",
                        claim_id,
                        exc_info=True,
                        extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
                    )
            return result

    return await run_admin_job("Decline claim", _run())


@router.post("/claims/{claim_id}/revoke", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_revoke_claim(claim_id: int, body: ResolutionBody, request: Request) -> dict:
    """Revoke an already-granted claim (report escalation or discretion) —
    deletes the row outright (unlike decline, which just flips status) and
    reverts pinned fields on every event this claim covers to source
    authority immediately (#442), not just the representative one, so the
    next ingestion/refetch pass can overwrite them all again."""
    note = validated_resolution_note(body)

    async def _run() -> dict:
        async with AsyncSessionLocal() as db:
            claim = await _claim_or_404(db, claim_id)
            if claim.status != CLAIM_STATUS_APPROVED:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=ERROR_CLAIM_NOT_APPROVED,
                )
            event = await representative_event_for_claim(db, claim)
            organizer_id = claim.organizer_id
            kind = claim.kind
            await clear_claim_pins(db, claim)
            await db.delete(claim)
            result = {
                "id": claim_id,
                "event_id": event.id if event is not None else None,
                "note": note,
                # organizer_id/kind: not shown in the admin UI, only read back
                # by organizer_claims.py's tombstone lookup (#446) — the row
                # itself is gone, so this AdminAction entry is the only place
                # left to confirm the caller actually owned the deleted claim.
                "organizer_id": organizer_id,
                "kind": kind,
            }
            emit_admin_log = log_admin_action(db, ADMIN_ACTION_REVOKE_CLAIM, claim_id, result)
            await db.commit()
            emit_admin_log()
            return result

    return await run_admin_job("Revoke claim", _run())


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


@router.get("/promotions/cap-strip", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_BROWSE, scope=RATE_LIMIT_SCOPE_ADMIN_READ)
async def admin_promotion_cap_strip(request: Request) -> dict:
    """The 14-day cap strip: reserved, paid and live Promotions per Tallinn
    day, starting today, each out of the cap."""
    today = tallinn_today(now_tallinn())
    async with AsyncSessionLocal() as db:
        days = await cap_strip(db, today)
    return {
        "today": today.isoformat(),
        "cap": PROMOTION_LIVE_CAP,
        "days": [d.as_dict() for d in days],
    }


@router.get("/promotions/trust", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_BROWSE, scope=RATE_LIMIT_SCOPE_ADMIN_READ)
async def admin_promotion_trust(request: Request) -> dict:
    """The Trust panel (#620): reports on promoted events, Email ad consent
    withdrawals by source, slot dislikes and logged complaints for the rolling
    4 weeks and since launch, next to live Promotions, slots served and current
    consenters. Read only; nothing here flips a flag."""
    async with AsyncSessionLocal() as db:
        return await trust_panel(db, now_tallinn())


class _PromotionComplaintBody(BaseModel):
    note: str = Field(min_length=1, max_length=PROMOTION_NOTE_MAX_CHARS)
    source: str = PROMOTION_COMPLAINT_SOURCE_OTHER
    complainant: str | None = Field(default=None, max_length=PROMOTION_COMPLAINANT_MAX_CHARS)

    @field_validator("source")
    @classmethod
    def _known_source(cls, value: str) -> str:
        if value not in PROMOTION_COMPLAINT_SOURCES:
            raise ValueError(f"source must be one of {PROMOTION_COMPLAINT_SOURCES}")
        return value


@router.post(
    "/promotions/complaints",
    dependencies=[Depends(get_current_admin)],
    status_code=status.HTTP_201_CREATED,
)
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_log_promotion_complaint(
    body: _PromotionComplaintBody, request: Request
) -> dict:
    """Log a complaint about the ads that arrived by email or the contact form.
    Audited as `promotion_complaint` and counted in the Trust panel. `note` is
    required; `complainant` (who, so two complaints from one person count
    once) is optional."""
    note = body.note.strip()
    if not note:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_PROMOTION_NOTE_REQUIRED,
        )
    complainant = (body.complainant or "").strip() or None

    async def _run() -> dict:
        async with AsyncSessionLocal() as db:
            result = {"note": note, "source": body.source, "complainant": complainant}
            emit_admin_log = log_admin_action(
                db, ADMIN_ACTION_PROMOTION_COMPLAINT, PROMOTION_COMPLAINT_TARGET, result
            )
            await db.commit()
            emit_admin_log()
            return {"logged": True, **result}

    return await run_admin_job("Log promotion complaint", _run())


def _withdraw_audit(result: WithdrawResult) -> dict:
    return {
        **_promotion_audit_summary(result.promotion),
        "reason": PROMOTION_WITHDRAWN_NOTE,
        "end_reason": PROMOTION_END_REASON_FEATURE_WITHDRAWN,
        "unused_days": result.unused_days,
        "refund_cents": result.refund_cents,
    }


def _withdraw_guard() -> None:
    """Withdraw only runs after the slots flag is off (step two of the
    runbook), so no ad is still being served while Promotions end."""
    if settings.PROMOTIONS_SLOTS_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=ERROR_PROMOTION_SLOTS_STILL_ENABLED
        )


def _withdraw_summary(result: WithdrawResult) -> dict:
    return {
        "id": result.promotion.id,
        "event_id": result.promotion.event_id,
        "unused_days": result.unused_days,
        "refund_cents": result.refund_cents,
        "refunded_cents": result.promotion.refunded_cents,
    }


async def _audit_withdrawals(db: AsyncSession, results: list[WithdrawResult]) -> list[Callable[[], None]]:
    emits: list[Callable[[], None]] = []
    for item in results:
        emits.append(
            log_admin_action(
                db, ADMIN_ACTION_PROMOTION_END, item.promotion.id, _withdraw_audit(item)
            )
        )
        if item.refund_cents > 0:
            emits.append(
                log_admin_action(
                    db,
                    ADMIN_ACTION_PROMOTION_REFUND,
                    item.promotion.id,
                    {**_promotion_audit_summary(item.promotion), "amount_cents": item.refund_cents,
                     "note": PROMOTION_WITHDRAWN_REFUND_NOTE},
                )
            )
    return emits


@router.post("/promotions/withdraw-all", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_withdraw_all_promotions(
    request: Request, gateway: PaymentGateway = Depends(get_payment_gateway)
) -> dict:
    """Withdraw (#620): end every paid, unfinished Promotion with
    `feature_withdrawn` and record a full refund of its unused days. 409
    `slots_still_enabled` while `PROMOTIONS_SLOTS_ENABLED` is on. A Promotion
    that cannot be ended is listed in `skipped` (a card refund Stripe refused
    has code `refund_provider_failed`); the rest still end."""
    _withdraw_guard()

    async def _run() -> dict:
        now = now_tallinn()
        async with AsyncSessionLocal() as db:
            outcome = await withdraw_all(db, now, gateway)
            emits = await _audit_withdrawals(db, outcome.withdrawn)
            promotions = [item.promotion for item in outcome.withdrawn]
            organizers = {
                o.id: o
                for o in await db.scalars(
                    select(Organizer).where(Organizer.id.in_({p.organizer_id for p in promotions}))
                )
            }
            events = {
                e.id: e
                for e in await db.scalars(
                    select(Event).where(Event.id.in_({p.event_id for p in promotions}))
                )
            }
            mails = [(p, organizers.get(p.organizer_id), events.get(p.event_id)) for p in promotions]
            await db.commit()
            for emit in emits:
                emit()
            for promotion, organizer, event in mails:
                if organizer is not None and event is not None:
                    await _notify_promotion_ended(
                        organizer, event, promotion, PROMOTION_WITHDRAWN_NOTE, False
                    )
            return {
                "withdrawn": [_withdraw_summary(item) for item in outcome.withdrawn],
                "skipped": outcome.skipped,
            }

    return await run_admin_job("Withdraw promotions", _run())


@router.get("/promotions", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_BROWSE, scope=RATE_LIMIT_SCOPE_ADMIN_READ)
async def admin_list_promotions(
    request: Request,
    state: str | None = Query(None),
    limit: int = Query(
        ADMIN_PROMOTIONS_PAGE_SIZE,
        ge=PAGINATION_MIN_LIMIT,
        le=ADMIN_PROMOTIONS_MAX_PAGE_SIZE,
    ),
    offset: int = Query(
        PAGINATION_MIN_OFFSET, ge=PAGINATION_MIN_OFFSET, le=PAGINATION_MAX_OFFSET
    ),
) -> dict:
    """Promotions, newest window first. `state` (scheduled, live, finished) is
    computed from the window and today's Tallinn date, never stored."""
    if state is not None and state not in VALID_PROMOTION_STATES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_PROMOTION_INVALID_STATE,
        )
    now = now_tallinn()
    today = tallinn_today(now)
    async with AsyncSessionLocal() as db:
        items, total = await list_promotions(db, state=state, limit=limit, offset=offset, now=now)
    return {
        "today": today.isoformat(),
        "promotions": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
    }


@router.get("/promotions/{promotion_id}/daily-stats", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_BROWSE, scope=RATE_LIMIT_SCOPE_ADMIN_READ)
async def admin_promotion_daily_stats(promotion_id: int, request: Request) -> dict:
    """The per-day delivery table for one Promotion: anonymous counts for each
    complete window day (today is left out), zeros where nothing was counted."""
    today = tallinn_today(now_tallinn())
    async with AsyncSessionLocal() as db:
        promotion = await db.get(Promotion, promotion_id)
        if promotion is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_PROMOTION_NOT_FOUND
            )
        stored = (await load_daily_stats(db, [promotion_id]))[promotion_id]
    return {
        "promotion_id": promotion_id,
        "today": today.isoformat(),
        "days": daily_stats_table(promotion, stored, today),
    }


@router.get(
    "/events/{event_id}/promotion-context", dependencies=[Depends(get_current_admin)]
)
@limiter.shared_limit(RATE_LIMIT_BROWSE, scope=RATE_LIMIT_SCOPE_ADMIN_READ)
async def admin_promotion_context(event_id: int, request: Request) -> dict:
    """Grant form context: resolved owner (null = cannot grant), prefill,
    window rules, pricing and the event's existing Promotions."""
    async with AsyncSessionLocal() as db:
        event = await event_or_404(db, event_id)
        return await grant_context(db, event, now_tallinn())


@router.get(
    "/events/{event_id}/promotions/validate", dependencies=[Depends(get_current_admin)]
)
@limiter.shared_limit(RATE_LIMIT_BROWSE, scope=RATE_LIMIT_SCOPE_ADMIN_READ)
async def admin_validate_promotion_dates(
    event_id: int,
    request: Request,
    start_date: date,
    end_date: date,
    is_complimentary: bool = False,
) -> dict:
    """Live date validation for the grant form: every window, overlap and cap
    problem for the candidate window, plus the price. Writes nothing."""
    async with AsyncSessionLocal() as db:
        event = await event_or_404(db, event_id)
        violations = await validate_grant(db, event, start_date, end_date, now_tallinn())
    return validation_payload(start_date, end_date, violations, is_complimentary)


@router.post(
    "/events/{event_id}/promotions",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_admin)],
)
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_grant_promotion(
    event_id: int, body: PromotionGrantBody, request: Request
) -> dict:
    """Grant a Promotion for an owned event. Refused (409 no_owner / overlap /
    cap_exceeded, 422 for window and field rules) with `detail.errors` listing
    every rule broken. The cap check and insert run under one advisory lock,
    and the PROMOTION_GRANT audit row rides the same transaction."""
    grant_request = GrantRequest(
        start_date=body.start_date,
        end_date=body.end_date,
        advertiser_legal_name=body.advertiser_legal_name.strip(),
        advertiser_registry_code=body.advertiser_registry_code.strip(),
        billing_email=str(body.billing_email) if body.billing_email else None,
        is_complimentary=body.is_complimentary,
        complimentary_note=body.complimentary_note,
        invoice_reference=(body.invoice_reference or "").strip() or None,
        restriction_clearance_confirmed=body.restriction_clearance_confirmed,
        restriction_clearance_note=body.restriction_clearance_note,
    )
    if not grant_request.advertiser_legal_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_PROMOTION_ADVERTISER_LEGAL_NAME_REQUIRED,
        )

    async def _run() -> dict:
        now = now_tallinn()
        async with AsyncSessionLocal() as db:
            event = await event_or_404(db, event_id)
            try:
                promotion = await grant_promotion(db, event, grant_request, now)
            except PromotionRefused as refused:
                await db.rollback()
                raise promotion_refusal(refused) from None
            result = {
                "id": promotion.id,
                "event_id": promotion.event_id,
                "organizer_id": promotion.organizer_id,
                "status": promotion.status,
                "start_date": promotion.start_date.isoformat(),
                "end_date": promotion.end_date.isoformat(),
                "days": promotion.days,
                "net_price_cents": promotion.net_price_cents,
                "vat_rate_percent": str(promotion.vat_rate_percent),
                "is_complimentary": promotion.is_complimentary,
                "complimentary_note": promotion.complimentary_note,
                "invoice_reference": promotion.invoice_reference,
                "advertiser_legal_name": promotion.advertiser_legal_name,
                "advertiser_registry_code": promotion.advertiser_registry_code,
                "restriction_cleared": promotion.restriction_cleared,
                "restriction_clearance_note": promotion.restriction_clearance_note,
            }
            emit_admin_log = log_admin_action(
                db, ADMIN_ACTION_PROMOTION_GRANT, promotion.id, result
            )
            organizer = await db.get(Organizer, promotion.organizer_id)
            payload = serialize_promotion(
                promotion,
                event.title_orig,
                organizer.name if organizer else None,
                tallinn_today(now),
            )
            await db.commit()
            emit_admin_log()
            return payload

    return await run_admin_job("Grant promotion", _run())


# ---------------------------------------------------------------------------
# Promotion lifecycle (#601): detail and commands. Each command runs under the
# cap lock, writes its audit row in the same transaction and returns the
# refreshed detail payload.
# ---------------------------------------------------------------------------


class _PromotionMarkPaidBody(BaseModel):
    invoice_reference: str | None = Field(default=None, max_length=PROMOTION_INVOICE_REFERENCE_MAX_LEN)


class _PromotionEditBody(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    advertiser_legal_name: str | None = Field(
        default=None, max_length=PROMOTION_ADVERTISER_NAME_MAX_CHARS
    )
    advertiser_registry_code: str | None = Field(default=None, max_length=PROMOTION_REGISTRY_CODE_MAX_LEN)
    billing_email: EmailStr | None = Field(
        default=None, max_length=PROMOTION_BILLING_EMAIL_MAX_CHARS
    )
    invoice_reference: str | None = Field(default=None, max_length=PROMOTION_INVOICE_REFERENCE_MAX_LEN)


class _PromotionRepointBody(BaseModel):
    event_id: int


class _PromotionClearBody(BaseModel):
    note: str = Field(max_length=PROMOTION_NOTE_MAX_CHARS)


class _PromotionReasonBody(BaseModel):
    reason: str = Field(max_length=PROMOTION_NOTE_MAX_CHARS)


class _PromotionRefundBody(BaseModel):
    amount_cents: int
    note: str = Field(max_length=PROMOTION_NOTE_MAX_CHARS)


def _promotion_audit_summary(promotion: Promotion) -> dict:
    return {
        "promotion_id": promotion.id,
        "event_id": promotion.event_id,
        "organizer_id": promotion.organizer_id,
        "status": promotion.status,
        "start_date": promotion.start_date.isoformat(),
        "end_date": promotion.end_date.isoformat(),
        "days": promotion.days,
        "net_price_cents": promotion.net_price_cents,
        "refunded_cents": promotion.refunded_cents,
    }


async def _notify_promotion_ended(
    organizer: Organizer, event: Event, promotion: Promotion, reason: str, voided: bool
) -> None:
    """Email the Organizer the reason, in their locale. Best-effort after the
    commit: a failed send is logged, never undoes the command."""
    send = send_promotion_void_email if voided else send_promotion_ended_email
    try:
        await send(
            organizer.email,
            resolve_title(event, organizer.locale),
            promotion.start_date,
            promotion.end_date,
            reason,
            organizer.locale,
        )
    except Exception:
        log.error(
            "Failed to send promotion %s email (promotion_id=%s)",
            "void" if voided else "ended",
            promotion.id,
            exc_info=True,
            extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
        )


async def _run_promotion_command(
    promotion_id: int,
    action: str,
    command: Callable[[AsyncSession, datetime], Awaitable[Promotion]],
    audit_extra: dict,
    notify_reason: str | None = None,
    voided: bool = False,
) -> dict:
    async def _run() -> dict:
        now = now_tallinn()
        async with AsyncSessionLocal() as db:
            try:
                promotion = await command(db, now)
            except PromotionNotFound:
                await db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_PROMOTION_NOT_FOUND
                ) from None
            except PromotionRefused as refused:
                await db.rollback()
                raise promotion_refusal(refused) from None
            except PaymentProviderError:
                await db.rollback()
                log.error("Stripe refused a Promotion command (%s)", action, exc_info=True)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=PROMOTION_CHECKOUT_ERROR_MESSAGES[PROMOTION_ERROR_REFUND_PROVIDER],
                ) from None
            emit_admin_log = log_admin_action(
                db, action, promotion.id, {**_promotion_audit_summary(promotion), **audit_extra}
            )
            payload = await promotion_detail(db, promotion, now)
            organizer = await db.get(Organizer, promotion.organizer_id)
            event = await db.get(Event, promotion.event_id)
            await db.commit()
            emit_admin_log()
            if notify_reason is not None and organizer is not None and event is not None:
                await _notify_promotion_ended(organizer, event, promotion, notify_reason, voided)
            return payload

    return await run_admin_job(f"Promotion {action}", _run())


# ---------------------------------------------------------------------------
# Promotion requests (#615): the queue, grant and decline. Under
# /promotion-requests (not /promotions/requests) so the int path of
# /promotions/{promotion_id} never shadows it.
# ---------------------------------------------------------------------------


class _PromotionRequestDeclineBody(BaseModel):
    reason: str = Field(max_length=PROMOTION_DECLINE_REASON_MAX_CHARS)


@router.get("/promotion-requests", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_BROWSE, scope=RATE_LIMIT_SCOPE_ADMIN_READ)
async def admin_list_promotion_requests(
    request: Request,
    request_status: str = Query(PROMOTION_REQUEST_STATUS_PENDING, alias="status"),
    limit: int = Query(
        ADMIN_PROMOTION_REQUESTS_PAGE_SIZE,
        ge=PAGINATION_MIN_LIMIT,
        le=ADMIN_PROMOTIONS_MAX_PAGE_SIZE,
    ),
    offset: int = Query(
        PAGINATION_MIN_OFFSET, ge=PAGINATION_MIN_OFFSET, le=PAGINATION_MAX_OFFSET
    ),
) -> dict:
    """The request queue (pending by default, oldest first) with the pending
    count, each pending request's `not_eligible_reason` and its event's
    `promotion_restriction` tag."""
    if request_status not in VALID_PROMOTION_REQUEST_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_PROMOTION_REQUEST_INVALID_STATUS,
        )
    async with AsyncSessionLocal() as db:
        items, total = await list_promotion_requests(
            db, status=request_status, limit=limit, offset=offset, now=now_tallinn()
        )
        count = await pending_request_count(db)
    return {
        "pending_count": count,
        "requests": items,
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(items) < total,
    }


@router.post(
    "/promotion-requests/{request_id}/grant",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_admin)],
)
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_grant_promotion_request(
    request_id: int, body: PromotionGrantBody, request: Request
) -> dict:
    """Grant a pending request from the form prefilled with it (dates and
    fields editable). Creates the Promotion and marks the request granted in
    one transaction, audited as promotion_request_grant. Same refusals as a
    direct grant, plus 409 request_not_pending / request_owner_changed. The
    Organizer is not emailed."""
    grant_request = GrantRequest(
        start_date=body.start_date,
        end_date=body.end_date,
        advertiser_legal_name=body.advertiser_legal_name.strip(),
        advertiser_registry_code=body.advertiser_registry_code.strip(),
        billing_email=str(body.billing_email) if body.billing_email else None,
        is_complimentary=body.is_complimentary,
        complimentary_note=body.complimentary_note,
        invoice_reference=(body.invoice_reference or "").strip() or None,
        restriction_clearance_confirmed=body.restriction_clearance_confirmed,
        restriction_clearance_note=body.restriction_clearance_note,
    )
    if not grant_request.advertiser_legal_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_PROMOTION_ADVERTISER_LEGAL_NAME_REQUIRED,
        )

    async def _run() -> dict:
        now = now_tallinn()
        async with AsyncSessionLocal() as db:
            try:
                promotion_request, promotion = await grant_promotion_request(
                    db, request_id, grant_request, now
                )
            except RequestNotFound:
                await db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=ERROR_PROMOTION_REQUEST_NOT_FOUND,
                ) from None
            except PromotionRefused as refused:
                await db.rollback()
                raise promotion_refusal(refused) from None
            emit_admin_log = log_admin_action(
                db,
                ADMIN_ACTION_PROMOTION_REQUEST_GRANT,
                promotion_request.id,
                {
                    "request_id": promotion_request.id,
                    "promotion_id": promotion.id,
                    "event_id": promotion.event_id,
                    "organizer_id": promotion.organizer_id,
                    "start_date": promotion.start_date.isoformat(),
                    "end_date": promotion.end_date.isoformat(),
                    "is_complimentary": promotion.is_complimentary,
                },
            )
            event = await db.get(Event, promotion.event_id)
            organizer = await db.get(Organizer, promotion.organizer_id)
            payload = serialize_promotion(
                promotion,
                event.title_orig if event else "",
                organizer.name if organizer else None,
                tallinn_today(now),
            )
            payload["request_id"] = promotion_request.id
            await db.commit()
            emit_admin_log()
            return payload

    return await run_admin_job("Grant promotion request", _run())


@router.post(
    "/promotion-requests/{request_id}/decline", dependencies=[Depends(get_current_admin)]
)
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_decline_promotion_request(
    request_id: int, body: _PromotionRequestDeclineBody, request: Request
) -> dict:
    """Decline a pending request. A reason is required (422 reason_required);
    it is emailed to the Organizer in their locale after the commit, and
    audited as promotion_request_decline."""
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": PROMOTION_ERROR_REASON_REQUIRED,
                "message": PROMOTION_ERROR_MESSAGES[PROMOTION_ERROR_REASON_REQUIRED],
            },
        )

    async def _run() -> dict:
        now = now_tallinn()
        async with AsyncSessionLocal() as db:
            try:
                promotion_request = await decline_promotion_request(db, request_id, reason, now)
            except RequestNotFound:
                await db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=ERROR_PROMOTION_REQUEST_NOT_FOUND,
                ) from None
            except PromotionRefused as refused:
                await db.rollback()
                raise promotion_refusal(refused) from None
            emit_admin_log = log_admin_action(
                db,
                ADMIN_ACTION_PROMOTION_REQUEST_DECLINE,
                promotion_request.id,
                {
                    "request_id": promotion_request.id,
                    "event_id": promotion_request.event_id,
                    "organizer_id": promotion_request.organizer_id,
                    "reason": reason,
                },
            )
            organizer = await db.get(Organizer, promotion_request.organizer_id)
            event = await db.get(Event, promotion_request.event_id)
            payload = {
                "id": promotion_request.id,
                "status": promotion_request.status,
                "decline_reason": promotion_request.decline_reason,
            }
            await db.commit()
            emit_admin_log()
            if organizer is not None and event is not None:
                try:
                    await send_promotion_request_declined_email(
                        organizer.email,
                        resolve_title(event, organizer.locale),
                        promotion_request.start_date,
                        promotion_request.end_date,
                        reason,
                        organizer.locale,
                    )
                except Exception:
                    log.error(
                        "Failed to send promotion request declined email (request_id=%s)",
                        promotion_request.id,
                        exc_info=True,
                        extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
                    )
            return payload

    return await run_admin_job("Decline promotion request", _run())


@router.get("/promotions/{promotion_id}", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_BROWSE, scope=RATE_LIMIT_SCOPE_ADMIN_READ)
async def admin_promotion_detail(promotion_id: int, request: Request) -> dict:
    """One Promotion with its event, content snapshots (newest first), audit
    trail, available commands and re-point candidates."""
    async with AsyncSessionLocal() as db:
        promotion = await db.get(Promotion, promotion_id)
        if promotion is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_PROMOTION_NOT_FOUND
            )
        return await promotion_detail(db, promotion, now_tallinn())


@router.post("/promotions/{promotion_id}/mark-paid", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_mark_promotion_paid(
    promotion_id: int, body: _PromotionMarkPaidBody, request: Request
) -> dict:
    """`unpaid -> paid`, any time before the start date (Tallinn). Optionally
    records the invoice reference (`ER-M-` series)."""
    return await _run_promotion_command(
        promotion_id,
        ADMIN_ACTION_PROMOTION_MARK_PAID,
        lambda db, now: mark_paid(db, promotion_id, now, body.invoice_reference),
        {"invoice_reference": (body.invoice_reference or "").strip() or None},
    )


@router.patch("/promotions/{promotion_id}", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_edit_promotion(
    promotion_id: int, body: _PromotionEditBody, request: Request
) -> dict:
    """Edit the fields sent. Before the start date: dates (cap rechecked,
    price recomputed), advertiser details and invoice reference. While live:
    only an earlier `end_date`. Send `billing_email` / `invoice_reference` as
    null to clear them."""
    changes = body.model_dump(exclude_unset=True)
    for key, value in changes.items():
        if value is None and key not in PROMOTION_NULLABLE_TEXT_FIELDS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=ERROR_PROMOTION_FIELD_NOT_NULLABLE.format(key=key),
            )
    logged = {k: (v.isoformat() if isinstance(v, date) else v) for k, v in changes.items()}
    return await _run_promotion_command(
        promotion_id,
        ADMIN_ACTION_PROMOTION_EDIT,
        lambda db, now: edit_promotion(db, promotion_id, changes, now),
        {"changes": logged},
    )


@router.post("/promotions/{promotion_id}/repoint", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_repoint_promotion(
    promotion_id: int, body: _PromotionRepointBody, request: Request
) -> dict:
    """Move the Promotion to another event the same Organizer owns in the same
    dedup group."""
    return await _run_promotion_command(
        promotion_id,
        ADMIN_ACTION_PROMOTION_REPOINT,
        lambda db, now: repoint_promotion(db, promotion_id, body.event_id, now),
        {"to_event_id": body.event_id},
    )


@router.post("/promotions/{promotion_id}/clear-restriction", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_clear_promotion_restriction(
    promotion_id: int, body: _PromotionClearBody, request: Request
) -> dict:
    """Clear the event's current Promotion restriction on a scheduled or live
    Promotion (a required note); the fill gate then lets it resume. 422 when
    the event is not restricted or the note is empty. Covers only that restriction."""
    return await _run_promotion_command(
        promotion_id,
        ADMIN_ACTION_PROMOTION_CLEAR_RESTRICTION,
        lambda db, now: clear_restriction(db, promotion_id, body.note, now),
        {"note": body.note.strip()},
    )


@router.post("/promotions/{promotion_id}/end", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_end_promotion(
    promotion_id: int, body: _PromotionReasonBody, request: Request
) -> dict:
    """`paid -> ended_early` with a required reason, which is emailed to the
    Organizer in their locale. Releases every cap day."""
    reason = body.reason.strip()
    return await _run_promotion_command(
        promotion_id,
        ADMIN_ACTION_PROMOTION_END,
        lambda db, now: end_early(db, promotion_id, reason, now),
        {"reason": reason},
        notify_reason=reason,
    )


@router.post("/promotions/{promotion_id}/withdraw", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_withdraw_promotion(
    promotion_id: int, request: Request, gateway: PaymentGateway = Depends(get_payment_gateway)
) -> dict:
    """Withdraw (#620) one paid Promotion: `ended_early` with
    `feature_withdrawn` and a full refund of its unused days, emailed to the
    Organizer. A card-paid one is refunded through Stripe (502 when Stripe
    refuses; it stays paid). 409 `slots_still_enabled` while the slots flag is
    on. Returns the refreshed detail."""
    _withdraw_guard()

    async def _run() -> dict:
        now = now_tallinn()
        async with AsyncSessionLocal() as db:
            try:
                item = await withdraw_promotion(db, promotion_id, now, gateway)
            except PromotionNotFound:
                await db.rollback()
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_PROMOTION_NOT_FOUND
                ) from None
            except PromotionRefused as refused:
                await db.rollback()
                raise promotion_refusal(refused) from None
            except PaymentProviderError:
                await db.rollback()
                log.error("Stripe refused a Promotion withdraw refund", exc_info=True)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=PROMOTION_CHECKOUT_ERROR_MESSAGES[PROMOTION_ERROR_REFUND_PROVIDER],
                ) from None
            emits = await _audit_withdrawals(db, [item])
            payload = await promotion_detail(db, item.promotion, now)
            organizer = await db.get(Organizer, item.promotion.organizer_id)
            event = await db.get(Event, item.promotion.event_id)
            await db.commit()
            for emit in emits:
                emit()
            if organizer is not None and event is not None:
                await _notify_promotion_ended(
                    organizer, event, item.promotion, PROMOTION_WITHDRAWN_NOTE, False
                )
            return payload

    return await run_admin_job("Withdraw promotion", _run())


@router.post("/promotions/{promotion_id}/void", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_void_promotion(
    promotion_id: int, body: _PromotionReasonBody, request: Request
) -> dict:
    """`unpaid -> void` with a required reason, which is emailed to the
    Organizer in their locale. Releases every cap day."""
    reason = body.reason.strip()
    return await _run_promotion_command(
        promotion_id,
        ADMIN_ACTION_PROMOTION_VOID,
        lambda db, now: void_promotion(db, promotion_id, reason, now),
        {"reason": reason},
        notify_reason=reason,
        voided=True,
    )


@router.post("/promotions/{promotion_id}/refund", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_record_promotion_refund(
    promotion_id: int,
    body: _PromotionRefundBody,
    request: Request,
    gateway: PaymentGateway = Depends(get_payment_gateway),
) -> dict:
    """Refund gross `amount_cents` with a required note. Cumulative, capped at
    what was charged. An off-platform payment is only recorded; a Stripe-paid
    one is issued (credit note and card refund in one Stripe call), 502 when
    Stripe refuses and nothing is recorded. `refund_prefill` on the detail
    holds the suggested amount."""
    return await _run_promotion_command(
        promotion_id,
        ADMIN_ACTION_PROMOTION_REFUND,
        lambda db, now: record_refund(
            db, promotion_id, body.amount_cents, body.note, now, gateway=gateway
        ),
        {"amount_cents": body.amount_cents, "note": body.note.strip()},
    )
