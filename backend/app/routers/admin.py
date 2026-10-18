"""Admin endpoints — protected by the admin console session cookie."""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from datetime import date, datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import and_, func, select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_admin
from app.cleanup import cleanup_stale_data
from app._generated.shared_constants import (
    DEFAULT_USER_LOCALE,
    PAGINATION_MAX_OFFSET,
    VALID_LOCALES,
)
from app.constants.admin import (
    ADMIN_ACTION_APPROVE_SUBMISSION,
    ADMIN_ACTION_BUILD_FEEDS,
    ADMIN_ACTION_CLEANUP,
    ADMIN_ACTION_CLASSIFY,
    ADMIN_ACTION_DECLINE_CLAIM,
    ADMIN_ACTION_DEDUP,
    ADMIN_ACTION_GEOCODE,
    ADMIN_ACTION_GRANT_CLAIM,
    ADMIN_ACTION_INGEST,
    ADMIN_ACTION_INGEST_SOURCE,
    ADMIN_ACTION_PIPELINE_RUN,
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
    ADMIN_ACTION_PUBLISH,
    ADMIN_ACTION_REFETCH,
    ADMIN_ACTION_RESOLVE_REPORTS,
    ADMIN_ACTION_RETRACT_SUBMISSION,
    ADMIN_ACTION_SEND_DIGESTS,
    ADMIN_ACTION_SYNC_ORGANIZERS,
    ADMIN_ACTION_TAKEDOWN_REPORTED_EVENT,
    ADMIN_CLAIMS_QUEUE_MAX_PAGE_SIZE,
    ADMIN_CLAIMS_QUEUE_PAGE_SIZE,
    ADMIN_DEDUP_GROUPS_MAX_PAGE_SIZE,
    ADMIN_DEDUP_GROUPS_PAGE_SIZE,
    ADMIN_EVENT_INSPECTOR_RAW_EVENTS_LIMIT,
    ADMIN_REVIEW_QUEUE_MAX_PAGE_SIZE,
    ADMIN_REVIEW_QUEUE_PAGE_SIZE,
    ADMIN_REPORTS_QUEUE_MAX_PAGE_SIZE,
    ADMIN_REPORTS_QUEUE_PAGE_SIZE,
)
from app.constants.claims import (
    CLAIM_KIND_PUBLISHER,
    CLAIM_STATUS_APPROVED,
    CLAIM_STATUS_PENDING,
    CLAIM_STATUS_REVOKED,
    ERROR_CLAIM_ALREADY_RESOLVED,
    ERROR_CLAIM_NOT_APPROVED,
    ERROR_CLAIM_NOT_FOUND,
    ERROR_CLAIM_QUEUE_INVALID_STATUS,
    ERROR_CLAIM_TARGET_ALREADY_APPROVED,
)
from app.constants.core import SQL_BIGINT_MAX, TALLINN_TZ
from app.constants.events import (
    ERROR_EVENT_NOT_FOUND,
    EVENT_CANCELLATION_REASON_ADMIN_RETRACT,
    EVENT_CANCELLATION_REASON_REPORT_TAKEDOWN,
    EVENT_STATUS_CANCELLED,
)
from app.constants.http import MIME_APPLICATION_NDJSON, HTTP_TIMEOUT_SECONDS
from app.constants.ingestion import ERROR_UNKNOWN_SOURCE
from app.constants.jobs import PIPELINE_RUN_OVERLAPPING_LOCK_KEYS
from app.constants.log_events import LOG_EVENT_EMAIL_SEND_FAILED
from app.constants.organizer import ERROR_SUBMISSION_NOT_FOUND
from app.constants.ranking import (
    PAGINATION_MIN_LIMIT,
    PAGINATION_MIN_OFFSET,
)
from app.constants.promotions import (
    PROMOTION_LIVE_CAP,
    ADMIN_PROMOTIONS_MAX_PAGE_SIZE,
    ADMIN_PROMOTIONS_PAGE_SIZE,
    ERROR_PROMOTION_INVALID_STATE,
    ERROR_PROMOTION_NOT_FOUND,
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
    ADMIN_PROMOTION_REQUESTS_PAGE_SIZE,
    PROMOTION_DECLINE_REASON_MAX_CHARS,
    PROMOTION_ERROR_MESSAGES,
    PROMOTION_ERROR_REASON_REQUIRED,
    PROMOTION_CHECKOUT_ERROR_MESSAGES,
    PROMOTION_ERROR_REFUND_PROVIDER,
    PROMOTION_NOTE_MAX_CHARS,
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
    ADMIN_RESOLUTION_NOTE_MAX_CHARS,
    ERROR_RESOLUTION_NOTE_REQUIRED,
    REPORT_AUTO_RESOLVE_NOTE,
    REPORT_STATUS_OPEN,
)
from app.constants.security import SECURITY_HEADERS
from app.claims.lifecycle import (
    approved_claim_exists,
    auto_decline_other_pending_claims,
    transition_pending_claim,
)
from app.claims.pinning import clear_claim_pins, representative_event_for_claim
from app.claims.target_resolution import ClaimTarget, bulk_resolve_publisher_events
from app.config import settings
from app.db import AsyncSessionLocal, run_in_session
from app.email.promotion_notice import (
    send_promotion_ended_email,
    send_promotion_request_declined_email,
    send_promotion_void_email,
)
from app.email.claim_resolution import send_claim_declined_email, send_claim_granted_email
from app.email.digest import send_daily_digests
from app.ingestion.jobs import (
    classify_pending_drain_now,
    dedup_pass_drain_now,
    geocode_pending_job,
    ingest_all_enabled,
    ingest_source,
    publish_pending_job,
    refetch_event_details_job,
)
from app.ingestion.organizer_sync import sync_fienta_organizers
from app.ingestion.registry import ADAPTER_REGISTRY
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
from app.promotions.promoted import promoted_clause
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
    DailyFeed,
    Event,
    EventReport,
    EventSource,
    Organizer,
    Promotion,
    RawEvent,
    Source,
)
from app.events.cancellation import (
    cancel_event_and_resolve_reports,
    resolve_open_reports,
    send_report_resolution_emails,
)
from app.publish import publish_pending
from app.ranking.score import build_daily_feeds
from app.rate_limit import limiter
from app.routers.utils import (
    acquire_admin_job_lock,
    claim_dns_record_name,
    log_admin_action,
    ndjson_line,
    promotion_refusal,
    release_admin_job_lock,
    run_admin_job,
    serialize_event,
    stream_admin_job,
    validate_report_reason,
)
from app.events.localize import (
    resolve_description,
    resolve_important_info,
    resolve_title,
)
from app.events.queries import canonical_event_filter, select_events_with_classification
from app.events.venue import (
    resolve_venue_address,
    resolve_venue_coords,
    resolve_venue_name,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")


def _ndjson_response(gen: AsyncIterator[bytes]) -> StreamingResponse:
    """Shared streamed-envelope response wrapper (issue #159) — every job
    trigger endpoint streams NDJSON with caching disabled unconditionally."""
    return StreamingResponse(
        gen,
        media_type=MIME_APPLICATION_NDJSON,
        headers={"Cache-Control": SECURITY_HEADERS["Cache-Control"]},
    )


@router.post("/ingest", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_ingest_all(request: Request) -> StreamingResponse:
    """Trigger ingestion for all enabled sources."""
    acquire_admin_job_lock(ADMIN_ACTION_INGEST)

    async def _run() -> dict:
        return {"results": await ingest_all_enabled()}

    return _ndjson_response(
        stream_admin_job(
            "Ingestion",
            "ingest",
            ADMIN_ACTION_INGEST,
            "all",
            _run(),
            lock_key=ADMIN_ACTION_INGEST,
        )
    )


@router.post("/ingest/{slug}", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_ingest_source(slug: str, request: Request) -> StreamingResponse:
    """Trigger ingestion for a single source by slug."""
    if slug not in ADAPTER_REGISTRY:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_UNKNOWN_SOURCE.format(slug=slug),
        )

    async def _run() -> dict:
        try:
            return await ingest_source(slug)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

    return _ndjson_response(
        stream_admin_job(
            "Ingestion", "ingest", ADMIN_ACTION_INGEST_SOURCE, slug, _run()
        )
    )


@router.post("/dedup", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_dedup_run(request: Request) -> StreamingResponse:
    """Trigger a dedup pass, draining the backlog until it clears or the cap is hit."""
    return _ndjson_response(
        stream_admin_job(
            "Dedup", "dedup", ADMIN_ACTION_DEDUP, "dedup", dedup_pass_drain_now()
        )
    )


def _dedup_event_summary(e: Event) -> dict:
    """Minimal per-event dict shared by every dedup-group listing:
    /admin/dedup/groups' _serialize_dedup_groups and the event inspector's
    sibling list (issue #157) — one field set kept in sync in one place."""
    return {
        "id": e.id,
        "title": e.title_orig,
        "starts_at": e.starts_at.isoformat(),
        "venue": resolve_venue_name(e, DEFAULT_USER_LOCALE),
        "status": e.status,
        "url": e.url,
        "is_explicit": e.is_explicit,
    }


def _serialize_dedup_groups(rows: Sequence[Event]) -> dict[int, list[dict]]:
    """Group event rows by dedup_group_id into response dicts."""
    groups: dict[int, list[dict]] = {}
    for e in rows:
        if e.dedup_group_id is None:
            continue
        groups.setdefault(e.dedup_group_id, []).append(_dedup_event_summary(e))
    return groups


@router.get("/dedup/groups", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_BROWSE, scope=RATE_LIMIT_SCOPE_ADMIN_READ)
async def admin_dedup_groups(
    request: Request,
    limit: int = Query(
        ADMIN_DEDUP_GROUPS_PAGE_SIZE,
        ge=PAGINATION_MIN_LIMIT,
        le=ADMIN_DEDUP_GROUPS_MAX_PAGE_SIZE,
    ),
    offset: int = Query(
        PAGINATION_MIN_OFFSET, ge=PAGINATION_MIN_OFFSET, le=PAGINATION_MAX_OFFSET
    ),
) -> dict:
    """Return events grouped by dedup_group_id for manual eyeballing.

    Paginated by *group* (not row), so a noisy group with many duplicates does
    not consume the whole page. ``offset`` and ``limit`` apply to the sorted
    list of distinct dedup_group_ids.
    """
    async with AsyncSessionLocal() as db:
        # Exact total on every page (spec #551): the numbered pager derives
        # its last page and past-end clamp from it.
        total = (
            await db.scalar(
                select(func.count(func.distinct(Event.dedup_group_id))).where(
                    Event.dedup_group_id.is_not(None),
                    Event.status != EVENT_STATUS_CANCELLED,
                )
            )
        ) or 0

        page_group_ids = (
            await db.scalars(
                select(Event.dedup_group_id)
                .where(
                    Event.dedup_group_id.is_not(None),
                    Event.status != EVENT_STATUS_CANCELLED,
                )
                .distinct()
                .order_by(Event.dedup_group_id)
                .limit(limit + 1)
                .offset(offset)
            )
        ).all()
        has_more = len(page_group_ids) > limit
        page_group_ids = page_group_ids[:limit]

        if not page_group_ids:
            return {
                "group_count": 0,
                "event_count": 0,
                "total": total,
                "limit": limit,
                "offset": offset,
                "has_more": False,
                "groups": [],
            }

        rows = (
            await db.scalars(
                select(Event)
                .options(selectinload(Event.venue))
                .where(
                    Event.dedup_group_id.in_(page_group_ids),
                    Event.status != EVENT_STATUS_CANCELLED,
                )
                .order_by(Event.dedup_group_id, Event.id)
            )
        ).all()

    groups = _serialize_dedup_groups(rows)

    return {
        "group_count": len(groups),
        "event_count": len(rows),
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "groups": [
            {"dedup_group_id": gid, "events": members}
            for gid, members in sorted(groups.items())
        ],
    }


class _ResolutionBody(BaseModel):
    resolution_note: str = Field(max_length=ADMIN_RESOLUTION_NOTE_MAX_CHARS)


def _validated_resolution_note(body: _ResolutionBody) -> str:
    note = body.resolution_note.strip()
    if not note:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_RESOLUTION_NOTE_REQUIRED,
        )
    return note


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
    event_id: int, body: _ResolutionBody, request: Request
) -> dict:
    """Cancel an organizer-submitted event (soft delete — mirrors organizer's
    own DELETE /organizer/events/{id}; events are never hard-deleted). Also
    clears needs_review so this resolves the review-queue entry outright —
    admin_list_submissions additionally excludes cancelled events regardless."""
    note = _validated_resolution_note(body)

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
    event_id: int, body: _ResolutionBody, request: Request
) -> dict:
    """Clear needs_review — an admin has eyeballed the submission and it's fine
    as-is. Also flips the submitting organizer to ``verified`` (a first-time
    approval is what makes an organizer trusted going forward — see
    Organizer.verified / app/publish.py) and runs the publish gate so this
    event (and any other now-eligible backlog) goes live immediately rather
    than waiting for the next scheduled publish_pending pass."""
    note = _validated_resolution_note(body)

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
            # whole backlog, not just this event — leave event_ids unscoped.
            # Diagnostic breakdown is unused by this endpoint's response.
            await publish_pending(db, diagnostics=False)
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
async def admin_grant_claim(claim_id: int, body: _ResolutionBody, request: Request) -> dict:
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
    note = _validated_resolution_note(body)

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
async def admin_decline_claim(claim_id: int, body: _ResolutionBody, request: Request) -> dict:
    """Decline a pending claim — frees its Publisher/Series key immediately
    (CLAIM_ACTIVE_STATUSES excludes revoked, same as a self-cancel). Unlike
    POST .../revoke this never touches Event.pinned_fields: a pending claim
    was never granted, so nothing was ever pinned against it."""
    note = _validated_resolution_note(body)

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
async def admin_revoke_claim(claim_id: int, body: _ResolutionBody, request: Request) -> dict:
    """Revoke an already-granted claim (report escalation or discretion) —
    deletes the row outright (unlike decline, which just flips status) and
    reverts pinned fields on every event this claim covers to source
    authority immediately (#442), not just the representative one, so the
    next ingestion/refetch pass can overwrite them all again."""
    note = _validated_resolution_note(body)

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


@router.get("/reports", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_BROWSE, scope=RATE_LIMIT_SCOPE_ADMIN_READ)
async def admin_list_reports(
    request: Request,
    reason: str | None = Query(None),
    illegal_only: bool = Query(False),
    limit: int = Query(
        ADMIN_REPORTS_QUEUE_PAGE_SIZE,
        ge=PAGINATION_MIN_LIMIT,
        le=ADMIN_REPORTS_QUEUE_MAX_PAGE_SIZE,
    ),
    offset: int = Query(
        PAGINATION_MIN_OFFSET, ge=PAGINATION_MIN_OFFSET, le=PAGINATION_MAX_OFFSET
    ),
    report: int | None = Query(None, ge=1, le=SQL_BIGINT_MAX),
) -> dict:
    """Content-moderation review queue: one row per event aggregating its
    REPORT_STATUS_OPEN reports (distinct from GET /admin/submissions, which
    is organizer-trust review — see CONTEXT.md's Report/Resolve glossary).
    Excludes cancelled events. ``reason``/``illegal_only`` narrow which
    events qualify for the queue (an event with at least one matching open
    report); each qualifying event's row still aggregates *all* of its open
    reports, not just the matching ones. Ordered promoted-first (an event with a live paid Promotion, `is_promoted`), then illegal-first, then by
    report count, then oldest-waiting first, then event id (so offset paging
    never repeats or skips rows that tie on the first three keys).

    ``report=<event_id>`` (the admin email deep link) locates that event's row
    in the queue and returns the page holding it, with the real ``offset``;
    the ``offset`` param is ignored. If the event is no longer in the queue
    (already resolved), page 1 is returned with ``report_not_found`` true.
    """
    if reason is not None:
        validate_report_reason(reason)

    agg_conditions = [
        EventReport.status == REPORT_STATUS_OPEN,
        Event.status != EVENT_STATUS_CANCELLED,
    ]
    # With no reason/illegal_only filter, "at least one matching open report"
    # degenerates to "has an open report" — already covered by the OPEN
    # condition above, so the DISTINCT event_id subquery (a full scan of
    # open reports on every plain queue load, the console's default view)
    # is a no-op and skipped (Big-O audit #5, item 2.10).
    if reason is not None or illegal_only:
        match_conditions = [EventReport.status == REPORT_STATUS_OPEN]
        if reason is not None:
            match_conditions.append(EventReport.reason == reason)
        if illegal_only:
            match_conditions.append(EventReport.is_illegal_allegation == true())
        matching_event_ids = (
            select(EventReport.event_id).where(*match_conditions).distinct()
        )
        agg_conditions.append(EventReport.event_id.in_(matching_event_ids))

    has_illegal_col = func.bool_or(EventReport.is_illegal_allegation).label(
        "has_illegal_allegation"
    )
    report_count_col = func.count(EventReport.id).label("report_count")
    oldest_col = func.min(EventReport.created_at).label("oldest_open_report_at")
    # "Promoted" (#612): a live paid Promotion on the event. Sorts first.
    promoted_col = promoted_clause(
        EventReport.event_id, tallinn_today(now_tallinn())
    ).label("is_promoted")

    agg = (
        select(
            EventReport.event_id,
            promoted_col,
            has_illegal_col,
            report_count_col,
            oldest_col,
        )
        .join(Event, Event.id == EventReport.event_id)
        .where(*agg_conditions)
        .group_by(EventReport.event_id)
    )

    order_keys = (
        promoted_col.desc(),
        has_illegal_col.desc(),
        report_count_col.desc(),
        oldest_col.asc(),
        EventReport.event_id.asc(),
    )

    async with AsyncSessionLocal() as db:
        # Exact total on every page (spec #551): the numbered pager derives
        # its last page and past-end clamp from it.
        total = (
            await db.scalar(select(func.count()).select_from(agg.subquery()))
        ) or 0

        report_not_found = False
        if report is not None:
            # One ROW_NUMBER() over the same four sort keys gives the row's
            # position; its page starts at the multiple of limit at or below.
            ranked = agg.add_columns(
                func.row_number().over(order_by=order_keys).label("position")
            ).subquery()
            position = await db.scalar(
                select(ranked.c.position).where(ranked.c.event_id == report)
            )
            if position is None:
                report_not_found = True
                offset = PAGINATION_MIN_OFFSET
            else:
                offset = (position - 1) // limit * limit

        page = (
            await db.execute(
                agg.order_by(*order_keys).limit(limit + 1).offset(offset)
            )
        ).all()
        has_more = len(page) > limit
        page = page[:limit]

        event_ids = [row.event_id for row in page]
        events_by_id: dict[int, Event] = {}
        reports_by_event: dict[int, list[EventReport]] = {}
        if event_ids:
            events = (
                await db.scalars(
                    select(Event)
                    .options(selectinload(Event.venue))
                    .where(Event.id.in_(event_ids))
                )
            ).all()
            events_by_id = {e.id: e for e in events}

            reports = (
                await db.scalars(
                    select(EventReport)
                    .where(
                        EventReport.event_id.in_(event_ids),
                        EventReport.status == REPORT_STATUS_OPEN,
                    )
                    .order_by(EventReport.created_at.asc())
                )
            ).all()
            for r in reports:
                reports_by_event.setdefault(r.event_id, []).append(r)

    rows = []
    for row in page:
        event = events_by_id.get(row.event_id)
        if event is None:
            continue
        event_reports = reports_by_event.get(row.event_id, [])
        rows.append(
            {
                "event_id": event.id,
                "title": event.title_orig,
                "status": event.status,
                "venue": resolve_venue_name(event, DEFAULT_USER_LOCALE),
                "submitted_by_organizer_id": event.submitted_by_organizer_id,
                "report_count": row.report_count,
                "reasons": sorted({r.reason for r in event_reports}),
                "has_illegal_allegation": bool(row.has_illegal_allegation),
                "is_promoted": bool(row.is_promoted),
                "reports": [
                    {
                        "reason": r.reason,
                        "detail": r.detail,
                        "is_illegal_allegation": r.is_illegal_allegation,
                        "created_at": r.created_at,
                    }
                    for r in event_reports
                ],
                "oldest_open_report_at": row.oldest_open_report_at,
            }
        )

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": has_more,
        "events": rows,
        "report_not_found": report_not_found,
    }


async def _event_or_404(db: AsyncSession, event_id: int) -> Event:
    event = await db.get(Event, event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_EVENT_NOT_FOUND
        )
    return event


def _serialize_inspector_report(r: EventReport) -> dict:
    return {
        "id": r.id,
        "user_id": r.user_id,
        "reason": r.reason,
        "is_illegal_allegation": r.is_illegal_allegation,
        "detail": r.detail,
        "status": r.status,
        "resolution_note": r.resolution_note,
        "created_at": r.created_at.isoformat(),
        "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
    }


def _serialize_raw_event(raw: RawEvent, source_slug: str) -> dict:
    """payload is included verbatim — the frontend must render it as
    escaped/pretty-printed text, never parsed as HTML (issue #157). Unlike
    description/important_info (sanitized at ingest), this is the one
    genuinely unsanitized field in the console."""
    return {
        "id": raw.id,
        "source_slug": source_slug,
        "external_id": raw.external_id,
        "payload": raw.payload,
        "fetched_at": raw.fetched_at.isoformat(),
        "processed_at": raw.processed_at.isoformat() if raw.processed_at else None,
    }


def _translation_state(m: dict | None, locale: str) -> bool:
    """True when this locale has its own stored value (not a fallback)."""
    return bool(m and m.get(locale))


def _content_by_locale(event: Event) -> dict:
    """Per-locale resolved content plus, per field, whether the value is a
    real translation or the locale -> en -> original fallback."""
    return {
        loc: {
            "title": resolve_title(event, loc),
            "description": resolve_description(event, loc),
            "important_info": resolve_important_info(event, loc),
            "venue_name": resolve_venue_name(event, loc),
            "translated": {
                "title": _translation_state(event.title_localized, loc),
                "description": _translation_state(event.description_localized, loc),
                "important_info": _translation_state(
                    event.important_info_localized, loc
                ),
            },
        }
        for loc in sorted(VALID_LOCALES)
    }


def _serialize_event_detail(event: Event) -> dict:
    cl = event.classification
    lat, lng = resolve_venue_coords(event)
    return {
        "id": event.id,
        "slug": event.slug,
        "title_orig": event.title_orig,
        "description_orig": event.description_orig,
        "important_info": event.important_info,
        "price_hint": event.price_hint,
        "starts_at": event.starts_at.isoformat(),
        "ends_at": event.ends_at.isoformat() if event.ends_at else None,
        "venue_name": resolve_venue_name(event, DEFAULT_USER_LOCALE),
        "venue_address": resolve_venue_address(event),
        "lat": lat,
        "lng": lng,
        "url": event.url,
        "image_url": event.image_url,
        "price_min": float(event.price_min) if event.price_min is not None else None,
        "price_max": float(event.price_max) if event.price_max is not None else None,
        "currency": event.currency,
        "status": event.status,
        "is_explicit": event.is_explicit,
        "is_out_of_area": event.is_out_of_area,
        "is_non_event": event.is_non_event,
        "has_free_tier": event.has_free_tier,
        "dedup_group_id": event.dedup_group_id,
        "submitted_by_organizer_id": event.submitted_by_organizer_id,
        "needs_review": event.needs_review,
        "cancellation_reason": event.cancellation_reason,
        "created_at": event.created_at.isoformat(),
        "updated_at": event.updated_at.isoformat(),
        "detail_refetched_at": (
            event.detail_refetched_at.isoformat()
            if event.detail_refetched_at
            else None
        ),
        "geocode_attempted_at": (
            event.geocode_attempted_at.isoformat()
            if event.geocode_attempted_at
            else None
        ),
        "classification": (
            {
                "categories": cl.categories,
                "vibes": cl.vibes,
                "quality_score": cl.quality_score,
                "why_go_bullets": cl.why_go_bullets,
                "language_detected": cl.language_detected,
                "model_used": cl.model_used,
                "classified_at": cl.classified_at.isoformat(),
            }
            if cl
            else None
        ),
        "content_by_locale": _content_by_locale(event),
    }


@router.get("/events/{event_id}", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_get_event(event_id: int, request: Request) -> dict:
    """Full-detail inspector payload for one event, any status (issue #157,
    part of #153). Curated projection, not a raw ORM dump — mirrors
    _serialize_dedup_groups' style. Dedup siblings and reports are fetched
    inline (cheap, already-indexed lookups), not separate round-trips.

    Feed-membership uses the `@>` (array-contains) operator, not `= ANY()` —
    the only one of the two the built-in GIN array_ops opclass can accelerate
    Shipped with no new index initially, per the research behind #153.
    """
    async with AsyncSessionLocal() as db:
        event = await db.scalar(
            select_events_with_classification().where(Event.id == event_id)
        )
        if event is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_EVENT_NOT_FOUND
            )

        siblings: Sequence[Event] = []
        if event.dedup_group_id is not None:
            # Deliberately includes cancelled siblings, unlike
            # admin_list_dedup_groups (which excludes them from its listing
            # view) — an admin drilling into one specific event wants to see
            # a cancelled sibling too (e.g. to understand why it was
            # cancelled), matching this endpoint's own "any status" event.
            siblings = (
                await db.scalars(
                    select(Event)
                    .options(selectinload(Event.venue))
                    .where(
                        Event.dedup_group_id == event.dedup_group_id,
                        Event.id != event.id,
                    )
                )
            ).all()

        reports = (
            await db.scalars(
                select(EventReport)
                .where(EventReport.event_id == event.id)
                .order_by(EventReport.created_at.desc())
            )
        ).all()

        raw_rows = (
            await db.execute(
                select(RawEvent, Source.slug)
                .join(Source, Source.id == RawEvent.source_id)
                .join(
                    EventSource,
                    and_(
                        EventSource.source_id == RawEvent.source_id,
                        EventSource.external_id == RawEvent.external_id,
                    ),
                )
                .where(EventSource.event_id == event.id)
                .order_by(RawEvent.fetched_at.desc())
                .limit(ADMIN_EVENT_INSPECTOR_RAW_EVENTS_LIMIT)
            )
        ).all()

        today = datetime.now(TALLINN_TZ).date()
        in_todays_feed = (
            await db.scalar(
                select(DailyFeed.id)
                .where(
                    DailyFeed.feed_date == today,
                    DailyFeed.event_ids.contains([event.id]),
                )
                .limit(1)
            )
        ) is not None

    return {
        "event": _serialize_event_detail(event),
        "dedup_siblings": [_dedup_event_summary(e) for e in siblings],
        "reports": [_serialize_inspector_report(r) for r in reports],
        "raw_events": [_serialize_raw_event(re, slug) for re, slug in raw_rows],
        "in_todays_feed": in_todays_feed,
    }


@router.post(
    "/reports/{event_id}/resolve", dependencies=[Depends(get_current_admin)]
)
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_resolve_reports(
    event_id: int, body: _ResolutionBody, request: Request
) -> dict:
    """Close every open report on the event with an admin-supplied note.
    No event mutation — the lightweight "this is fine" action. Never
    immunizes the event: a fresh report on a resolved row reopens it (see
    routers/reports.py's upsert-reopen semantics)."""
    note = _validated_resolution_note(body)

    async def _run() -> dict:
        async with AsyncSessionLocal() as db:
            event = await _event_or_404(db, event_id)
            resolved = await resolve_open_reports(db, event, note)
            result = {"event_id": event.id, "resolved_count": len(resolved)}
            emit_admin_log = log_admin_action(
                db, ADMIN_ACTION_RESOLVE_REPORTS, event_id, result
            )
            await db.commit()
            emit_admin_log()
            await send_report_resolution_emails(db, event, resolved, note)
            return result

    return await run_admin_job("Resolve reports", _run())


@router.post(
    "/reports/{event_id}/takedown", dependencies=[Depends(get_current_admin)]
)
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_takedown_reported_event(
    event_id: int, body: _ResolutionBody, request: Request
) -> dict:
    """Cancel the event and auto-resolve its open reports with the same
    note — the decisive action for content that actually needs to come
    down. Never touches Organizer.verified."""
    note = _validated_resolution_note(body)

    async def _run() -> dict:
        async with AsyncSessionLocal() as db:
            event = await _event_or_404(db, event_id)
            resolved = await cancel_event_and_resolve_reports(
                db, event, EVENT_CANCELLATION_REASON_REPORT_TAKEDOWN, note
            )
            result = {
                "event_id": event.id,
                "status": event.status,
                "resolved_count": len(resolved),
            }
            emit_admin_log = log_admin_action(
                db, ADMIN_ACTION_TAKEDOWN_REPORTED_EVENT, event_id, result
            )
            await db.commit()
            emit_admin_log()
            await send_report_resolution_emails(db, event, resolved, note)
            return result

    return await run_admin_job("Takedown reported event", _run())


@router.post("/classify", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_classify(request: Request) -> StreamingResponse:
    """Trigger LLM classification, draining the backlog until it clears or the cap is hit."""
    acquire_admin_job_lock(ADMIN_ACTION_CLASSIFY)
    return _ndjson_response(
        stream_admin_job(
            "Classification",
            "classify",
            ADMIN_ACTION_CLASSIFY,
            "classify",
            classify_pending_drain_now(),
            lock_key=ADMIN_ACTION_CLASSIFY,
        )
    )


@router.post("/publish", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_publish(request: Request) -> StreamingResponse:
    """Promote qualifying classified events to published (one bulk UPDATE)."""
    return _ndjson_response(
        stream_admin_job(
            "Publish", "publish", ADMIN_ACTION_PUBLISH, "publish", publish_pending_job()
        )
    )


@router.post("/geocode", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_geocode(request: Request) -> StreamingResponse:
    """Backfill lat/lng for events with a venue_address but no coordinates (one batch)."""
    return _ndjson_response(
        stream_admin_job(
            "Geocoding",
            "geocode",
            ADMIN_ACTION_GEOCODE,
            "geocode",
            geocode_pending_job(),
        )
    )


@router.post("/refetch", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_refetch(request: Request) -> StreamingResponse:
    """Re-fetch detail pages for all future events and reconcile stored fields (one batch).

    Standalone, like /admin/geocode — not part of /admin/pipeline/run. Run it
    before a manual geocode if you want coords NULLed by an address change
    re-resolved in the same operation.
    """
    return _ndjson_response(
        stream_admin_job(
            "Refetch",
            "refetch",
            ADMIN_ACTION_REFETCH,
            "refetch",
            refetch_event_details_job(),
        )
    )


@router.post("/sync-organizers", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_sync_organizers(request: Request) -> StreamingResponse:
    """Trigger Fienta organizer sync (discover new organizers, flag stale ones)."""
    return _ndjson_response(
        stream_admin_job(
            "Organizer sync",
            "sync_organizers",
            ADMIN_ACTION_SYNC_ORGANIZERS,
            "sync_organizers",
            run_in_session(sync_fienta_organizers, commit=True),
        )
    )


@router.post("/cleanup", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_cleanup(
    request: Request,
    dry_run: bool = Query(
        True,
        description="When true (default), counts candidate rows but deletes nothing",
    ),
) -> StreamingResponse:
    """Trigger data retention cleanup (prunes satellite tables; never events).

    Defaults to dry-run, matching every other destructive admin/maintenance
    tool in this codebase (reset_events.py, /admin/pipeline/run) — pass
    ?dry_run=false to actually delete.

    See app.cleanup.cleanup_stale_data for the per-table retention windows.
    """
    acquire_admin_job_lock(ADMIN_ACTION_CLEANUP)
    return _ndjson_response(
        stream_admin_job(
            "Cleanup",
            "cleanup",
            ADMIN_ACTION_CLEANUP,
            "cleanup",
            run_in_session(
                lambda db: cleanup_stale_data(db, dry_run=dry_run), commit=not dry_run
            ),
            lock_key=ADMIN_ACTION_CLEANUP,
        )
    )


@router.post("/build-feeds", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_build_feeds(request: Request) -> StreamingResponse:
    """Trigger daily feed builder for all active users (writes to daily_feeds)."""
    # build_daily_feeds commits internally (score.py); no second commit needed.
    return _ndjson_response(
        stream_admin_job(
            "Feed build",
            "build_feeds",
            ADMIN_ACTION_BUILD_FEEDS,
            "build_feeds",
            run_in_session(build_daily_feeds, commit=False),
        )
    )


@router.post("/send-digests", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_send_digests(
    request: Request,
    dry_run: bool = Query(True, description="When true (default), counts would-send but skips actual email delivery"),
) -> StreamingResponse:
    """Trigger daily digest send. Defaults to dry-run — pass ?dry_run=false to actually send."""
    acquire_admin_job_lock(ADMIN_ACTION_SEND_DIGESTS)
    return _ndjson_response(
        stream_admin_job(
            "Digest send",
            "send_digests",
            ADMIN_ACTION_SEND_DIGESTS,
            "send_digests",
            run_in_session(lambda db: send_daily_digests(db, dry_run=dry_run), commit=False),
            lock_key=ADMIN_ACTION_SEND_DIGESTS,
        )
    )


def _acquire_pipeline_run_locks() -> None:
    acquired: list[str] = []
    try:
        for key in (ADMIN_ACTION_PIPELINE_RUN, *PIPELINE_RUN_OVERLAPPING_LOCK_KEYS):
            acquire_admin_job_lock(key)
            acquired.append(key)
    except HTTPException:
        for key in acquired:
            release_admin_job_lock(key)
        raise


def _release_pipeline_run_locks() -> None:
    for key in (ADMIN_ACTION_PIPELINE_RUN, *PIPELINE_RUN_OVERLAPPING_LOCK_KEYS):
        release_admin_job_lock(key)


async def _run_pipeline_stages(dry_run: bool, queue: asyncio.Queue[bytes | None]) -> None:
    """Run all seven pipeline stages in dependency order, pushing one NDJSON
    envelope line per completed stage onto *queue*. Stops at the first
    failure — later stages depend on earlier output — so a failed run
    pushes fewer than seven lines. Runs as its own task (see
    _stream_pipeline_run) so a client disconnect can't cut a stage off
    mid-run."""
    stage_runners: list[tuple[str, Callable[[], Awaitable[object]]]] = [
        (
            "sync_organizers",
            lambda: run_in_session(sync_fienta_organizers, commit=True),
        ),
        ("ingest", ingest_all_enabled),
        ("dedup", dedup_pass_drain_now),
        ("classify", classify_pending_drain_now),
        ("publish", publish_pending_job),
        # build_daily_feeds commits internally (score.py)
        ("build_feeds", lambda: run_in_session(build_daily_feeds, commit=False)),
        (
            "send_digests",
            lambda: run_in_session(
                lambda db: send_daily_digests(db, dry_run=dry_run), commit=False
            ),
        ),
    ]

    stages: dict[str, object] = {}
    ok = True
    try:
        for stage_name, runner in stage_runners:
            try:
                result = await runner()
                stages[stage_name] = result
                await queue.put(ndjson_line(stage_name, "ok", result, None))
            except Exception:
                log.exception("pipeline: %s failed", stage_name)
                error = f"{stage_name} failed; see server logs"
                stages[stage_name] = {"error": error}
                ok = False
                await queue.put(ndjson_line(stage_name, "error", None, error))
                break

        # No single db session spans every stage above (each manages its own
        # commit), so this row can't ride the same transaction as any one
        # mutation — it gets its own short-lived session instead, still more
        # durable than the log line alone.
        async with AsyncSessionLocal() as audit_db:
            emit_admin_log = log_admin_action(
                audit_db, ADMIN_ACTION_PIPELINE_RUN, "pipeline", {"ok": ok, "stages": stages}
            )
            await audit_db.commit()
        emit_admin_log()
    finally:
        _release_pipeline_run_locks()
        await queue.put(None)


async def _stream_pipeline_run(dry_run: bool) -> AsyncIterator[bytes]:
    """Streams _run_pipeline_stages' output. Runs the stages as an
    independent task rather than a direct `await` in this generator's own
    frame — a client disconnect cancels this generator (Starlette's
    StreamingResponse races `listen_for_disconnect` against the body on
    uvicorn's pinned ASGI spec_version "2.3" — issue #159), and a direct
    `await` would let that cancellation reach into the stage loop and cut a
    stage off mid-run. Awaiting `queue.get()` instead means the run always
    finishes regardless of whether anyone is still listening."""
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    asyncio.ensure_future(_run_pipeline_stages(dry_run, queue))
    while True:
        line = await queue.get()
        if line is None:
            return
        yield line


@router.post("/pipeline/run", dependencies=[Depends(get_current_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_pipeline_run(
    request: Request,
    dry_run: bool = Query(True, description="When true (default), digest stage counts would-send but skips actual email delivery"),
) -> StreamingResponse:
    """Run all seven pipeline stages in dependency order, streamed as NDJSON
    (one line per completed stage — issue #159)."""
    _acquire_pipeline_run_locks()
    return _ndjson_response(_stream_pipeline_run(dry_run))


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


class _PromotionGrantBody(BaseModel):
    start_date: date
    end_date: date
    advertiser_legal_name: str = Field(max_length=PROMOTION_ADVERTISER_NAME_MAX_CHARS)
    advertiser_registry_code: str = Field(max_length=32)
    billing_email: EmailStr | None = Field(
        default=None, max_length=PROMOTION_BILLING_EMAIL_MAX_CHARS
    )
    is_complimentary: bool = False
    complimentary_note: str | None = Field(default=None, max_length=PROMOTION_NOTE_MAX_CHARS)
    invoice_reference: str | None = Field(default=None, max_length=64)
    # Required (both) when the event carries a Promotion restriction (#612).
    restriction_clearance_confirmed: bool = False
    restriction_clearance_note: str | None = Field(default=None, max_length=PROMOTION_NOTE_MAX_CHARS)


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
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="note required"
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
            mails = [
                (item.promotion, await db.get(Organizer, item.promotion.organizer_id),
                 await db.get(Event, item.promotion.event_id))
                for item in outcome.withdrawn
            ]
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
    today = tallinn_today(now_tallinn())
    async with AsyncSessionLocal() as db:
        items, total = await list_promotions(
            db, state=state, limit=limit, offset=offset, today=today
        )
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
        event = await _event_or_404(db, event_id)
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
        event = await _event_or_404(db, event_id)
        violations = await validate_grant(db, event, start_date, end_date, now_tallinn())
    return validation_payload(start_date, end_date, violations, is_complimentary)


@router.post(
    "/events/{event_id}/promotions",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_admin)],
)
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_grant_promotion(
    event_id: int, body: _PromotionGrantBody, request: Request
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
            detail="advertiser_legal_name is required",
        )

    async def _run() -> dict:
        now = now_tallinn()
        async with AsyncSessionLocal() as db:
            event = await _event_or_404(db, event_id)
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
    invoice_reference: str | None = Field(default=None, max_length=64)


class _PromotionEditBody(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    advertiser_legal_name: str | None = Field(
        default=None, max_length=PROMOTION_ADVERTISER_NAME_MAX_CHARS
    )
    advertiser_registry_code: str | None = Field(default=None, max_length=32)
    billing_email: EmailStr | None = Field(
        default=None, max_length=PROMOTION_BILLING_EMAIL_MAX_CHARS
    )
    invoice_reference: str | None = Field(default=None, max_length=64)


class _PromotionRepointBody(BaseModel):
    event_id: int


class _PromotionClearBody(BaseModel):
    note: str = Field(max_length=PROMOTION_NOTE_MAX_CHARS)


class _PromotionReasonBody(BaseModel):
    reason: str = Field(max_length=PROMOTION_NOTE_MAX_CHARS)


class _PromotionRefundBody(BaseModel):
    amount_cents: int
    note: str = Field(max_length=PROMOTION_NOTE_MAX_CHARS)


# Edit fields that may be sent as null (clearing them); every other field must
# carry a value when present.
_PROMOTION_CLEARABLE_FIELDS = frozenset({"billing_email", "invoice_reference"})


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
    request_id: int, body: _PromotionGrantBody, request: Request
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
            detail="advertiser_legal_name is required",
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
        if value is None and key not in _PROMOTION_CLEARABLE_FIELDS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{key} cannot be null",
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
