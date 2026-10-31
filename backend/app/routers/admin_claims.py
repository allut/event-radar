"""Admin claims queue — list, grant, decline and revoke organizer claims."""

import logging
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.dependencies import get_current_admin
from app._generated.shared_constants import (
    ADMIN_CLAIMS_QUEUE_PAGE_SIZE,
    CLAIM_KIND_PUBLISHER,
    CLAIM_STATUS_APPROVED,
    CLAIM_STATUS_PENDING,
    CLAIM_STATUS_REVOKED,
    PAGINATION_MAX_OFFSET,
)
from app.constants.admin import (
    ADMIN_ACTION_DECLINE_CLAIM,
    ADMIN_ACTION_GRANT_CLAIM,
    ADMIN_ACTION_REVOKE_CLAIM,
    ADMIN_CLAIMS_QUEUE_MAX_PAGE_SIZE,
)
from app.constants.claims import (
    ERROR_CLAIM_ALREADY_RESOLVED,
    ERROR_CLAIM_NOT_APPROVED,
    ERROR_CLAIM_NOT_FOUND,
    ERROR_CLAIM_QUEUE_INVALID_STATUS,
    ERROR_CLAIM_TARGET_ALREADY_APPROVED,
)
from app.constants.core import TALLINN_TZ
from app.constants.http import HTTP_TIMEOUT_SECONDS
from app.constants.log_events import LOG_EVENT_EMAIL_SEND_FAILED
from app.constants.ranking import (
    PAGINATION_MIN_LIMIT,
    PAGINATION_MIN_OFFSET,
)
from app.constants.rate_limits import (
    RATE_LIMIT_ADMIN,
    RATE_LIMIT_BROWSE,
    RATE_LIMIT_SCOPE_ADMIN_READ,
)
from app.claims.lifecycle import (
    approved_claim_exists,
    auto_decline_other_pending_claims,
    transition_pending_claim,
)
from app.claims.pinning import clear_claim_pins, representative_event_for_claim
from app.claims.target_resolution import ClaimTarget, bulk_resolve_publisher_events
from app.db import AsyncSessionLocal
from app.email.claim_resolution import send_claim_declined_email, send_claim_granted_email
from app.models.claims import Claim
from app.models.events import Event
from app.models.organizers import Organizer
from app.rate_limit import limiter
from app.routers.utils import (
    ResolutionBody,
    validated_resolution_note,
    claim_dns_record_name,
    log_admin_action,
    run_admin_job,
)
from app.events.localize import (
    resolve_title,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")


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
