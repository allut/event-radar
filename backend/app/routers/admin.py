"""Admin endpoints — protected by HTTP Basic auth."""

import logging
import secrets
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cleanup import cleanup_stale_data
from app.config import settings
from app.constants import (
    ADMIN_AUTH_FAILURES_MAX_ENTRIES,
    ADMIN_AUTH_LOCKOUT_SECONDS,
    ADMIN_AUTH_MAX_FAILURES,
    ADMIN_DEDUP_GROUPS_MAX_PAGE_SIZE,
    ADMIN_DEDUP_GROUPS_PAGE_SIZE,
    ADMIN_REVIEW_QUEUE_MAX_PAGE_SIZE,
    ADMIN_REVIEW_QUEUE_PAGE_SIZE,
    ADMIN_USERNAME_DEFAULT,
    APP_ENV_DEVELOPMENT,
    ERROR_ADMIN_DISABLED,
    ERROR_ADMIN_INCORRECT_CREDENTIALS,
    ERROR_ADMIN_LOCKOUT,
    ERROR_SUBMISSION_NOT_FOUND,
    ERROR_UNKNOWN_SOURCE,
    ADMIN_REPORTS_QUEUE_MAX_PAGE_SIZE,
    ADMIN_REPORTS_QUEUE_PAGE_SIZE,
    ERROR_EVENT_NOT_FOUND,
    ERROR_RESOLUTION_NOTE_REQUIRED,
    EVENT_CANCELLATION_REASON_ADMIN_RETRACT,
    EVENT_CANCELLATION_REASON_REPORT_TAKEDOWN,
    EVENT_STATUS_CANCELLED,
    LOG_EVENT_AUTH_FAILED,
    PAGINATION_MAX_OFFSET,
    PAGINATION_MIN_LIMIT,
    PAGINATION_MIN_OFFSET,
    RATE_LIMIT_ADMIN,
    REPORT_AUTO_RESOLVE_NOTE,
    REPORT_STATUS_OPEN,
)
from app.db import AsyncSessionLocal
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
from app.models.models import Event, EventReport, Organizer, Source
from app.publish import publish_pending
from app.ranking.score import build_daily_feeds
from app.rate_limit import client_key, limiter
from app.routers.utils import (
    cancel_event_and_resolve_reports,
    canonical_event_filter,
    require_configured_secret,
    resolve_open_reports,
    run_admin_job,
    run_in_session,
    select_events_with_classification,
    send_report_resolution_emails,
    serialize_event,
    validate_report_reason,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")
_security = HTTPBasic()

# (client_key -> (consecutive_failure_count, locked_until_monotonic)). In-memory,
# single-process — see ADMIN_AUTH_MAX_FAILURES in constants.py for the trade-off.
# Bounded LRU (ADMIN_AUTH_FAILURES_MAX_ENTRIES) — mirrors browse.py's _score_cache
# pattern — so sustained scanning/brute-force traffic can't grow this unboundedly.
_admin_auth_failures: OrderedDict[str, tuple[int, float]] = OrderedDict()


def _evict_one_admin_auth_failure(now: float) -> None:
    """Evict the oldest entry whose lockout has already expired (or was never
    locked), falling back to the oldest entry overall only if every entry is
    currently under an active lockout. A blind oldest-first eviction would let
    a high-cardinality distributed brute-force (>ADMIN_AUTH_FAILURES_MAX_ENTRIES
    distinct client_keys) evict — and thereby prematurely lift — another
    client's still-active lockout, undermining the lockout this dict exists
    to enforce."""
    for key, (_count, locked_until) in _admin_auth_failures.items():
        if locked_until <= now:
            del _admin_auth_failures[key]
            return
    _admin_auth_failures.popitem(last=False)


def _require_admin(
    request: Request, credentials: HTTPBasicCredentials = Depends(_security)
) -> None:
    key = client_key(request)
    now = time.monotonic()
    _count, locked_until = _admin_auth_failures.get(key, (0, 0.0))
    if now < locked_until:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=ERROR_ADMIN_LOCKOUT,
        )

    password = settings.ADMIN_PASSWORD
    if not require_configured_secret(
        password,
        feature="Admin endpoints",
        setting_name="ADMIN_PASSWORD",
        app_env=settings.APP_ENV,
        allow_insecure_dev=settings.ALLOW_INSECURE_DEV,
    ):
        return
    if (
        settings.ADMIN_USERNAME == ADMIN_USERNAME_DEFAULT
        and settings.APP_ENV != APP_ENV_DEVELOPMENT
    ):
        # Fail closed like the password check: a well-known username halves the
        # credential pair an attacker needs to brute-force.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ERROR_ADMIN_DISABLED,
        )
    username_ok = secrets.compare_digest(
        credentials.username.encode(),
        settings.ADMIN_USERNAME.encode(),
    )
    password_ok = secrets.compare_digest(
        credentials.password.encode(),
        password.encode(),
    )
    if not (username_ok and password_ok):
        failures = _count + 1
        locked_until = (
            now + ADMIN_AUTH_LOCKOUT_SECONDS
            if failures >= ADMIN_AUTH_MAX_FAILURES
            else 0.0
        )
        _admin_auth_failures[key] = (failures, locked_until)
        _admin_auth_failures.move_to_end(key)
        while len(_admin_auth_failures) > ADMIN_AUTH_FAILURES_MAX_ENTRIES:
            _evict_one_admin_auth_failure(now)
        log.warning(
            "admin auth failed: username=%r failures=%d",
            credentials.username,
            failures,
            extra={"event": LOG_EVENT_AUTH_FAILED},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_ADMIN_INCORRECT_CREDENTIALS,
            headers={"WWW-Authenticate": "Basic"},
        )
    _admin_auth_failures.pop(key, None)


@router.post("/ingest", dependencies=[Depends(_require_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_ingest_all(request: Request) -> dict:
    """Trigger ingestion for all enabled sources."""

    async def _run() -> dict:
        return {"results": await ingest_all_enabled()}

    return await run_admin_job("Ingestion", _run())


@router.post("/ingest/{slug}", dependencies=[Depends(_require_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_ingest_source(slug: str, request: Request) -> dict:
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

    return await run_admin_job("Ingestion", _run())


@router.post("/dedup", dependencies=[Depends(_require_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_dedup_run(request: Request) -> dict:
    """Trigger a dedup pass, draining the backlog until it clears or the cap is hit."""
    return await run_admin_job("Dedup", dedup_pass_drain_now())


def _serialize_dedup_groups(rows: Sequence[Event]) -> dict[int, list[dict]]:
    """Group event rows by dedup_group_id into response dicts."""
    groups: dict[int, list[dict]] = {}
    for e in rows:
        if e.dedup_group_id is None:
            continue
        groups.setdefault(e.dedup_group_id, []).append(
            {
                "id": e.id,
                "title": e.title_orig,
                "starts_at": e.starts_at.isoformat(),
                "venue": e.venue_name,
                "status": e.status,
                "url": e.url,
                "is_explicit": e.is_explicit,
            }
        )
    return groups


@router.get("/dedup/groups", dependencies=[Depends(_require_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
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
        total_groups = (
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
                .limit(limit)
                .offset(offset)
            )
        ).all()

        if not page_group_ids:
            return {
                "group_count": 0,
                "event_count": 0,
                "total_groups": total_groups,
                "limit": limit,
                "offset": offset,
                "has_more": False,
                "groups": [],
            }

        rows = (
            await db.scalars(
                select(Event)
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
        "total_groups": total_groups,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(page_group_ids) < total_groups,
        "groups": [
            {"dedup_group_id": gid, "events": members}
            for gid, members in sorted(groups.items())
        ],
    }


@router.get("/submissions", dependencies=[Depends(_require_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
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
        queue_filter = (Event.needs_review.is_(True), Event.status != EVENT_STATUS_CANCELLED)
        total = (
            await db.scalar(select(func.count(Event.id)).where(*queue_filter))
        ) or 0

        stmt = (
            select_events_with_classification()
            .where(*queue_filter)
            .order_by(Event.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        events = (await db.scalars(stmt)).all()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "has_more": offset + len(events) < total,
        "events": [
            {
                **serialize_event(e),
                "status": e.status,
                "submitted_by_organizer_id": e.submitted_by_organizer_id,
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
    "/submissions/{event_id}/retract", dependencies=[Depends(_require_admin)]
)
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_retract_submission(event_id: int, request: Request) -> dict:
    """Cancel an organizer-submitted event (soft delete — mirrors organizer's
    own DELETE /organizer/events/{id}; events are never hard-deleted). Also
    clears needs_review so this resolves the review-queue entry outright —
    admin_list_submissions additionally excludes cancelled events regardless."""

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
            await db.commit()
            await send_report_resolution_emails(
                db, event, resolved, REPORT_AUTO_RESOLVE_NOTE
            )
            return {"id": event.id, "status": event.status}

    return await run_admin_job("Retract submission", _run())


@router.post(
    "/submissions/{event_id}/approve", dependencies=[Depends(_require_admin)]
)
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_approve_submission(event_id: int, request: Request) -> dict:
    """Clear needs_review — an admin has eyeballed the submission and it's fine
    as-is. Also flips the submitting organizer to ``verified`` (a first-time
    approval is what makes an organizer trusted going forward — see
    Organizer.verified / app/publish.py) and runs the publish gate so this
    event (and any other now-eligible backlog) goes live immediately rather
    than waiting for the next scheduled publish_pending pass."""

    async def _run() -> dict:
        async with AsyncSessionLocal() as db:
            event = await _submission_or_404(db, event_id)
            event.needs_review = False
            if event.submitted_by_organizer_id is not None:
                organizer = await db.get(Organizer, event.submitted_by_organizer_id)
                if organizer is not None:
                    organizer.verified = True
            # organizer.verified flipping True can unlock this organizer's
            # whole backlog, not just this event — leave event_ids unscoped.
            # Diagnostic breakdown is unused by this endpoint's response.
            await publish_pending(db, diagnostics=False)
            await db.commit()
            return {"id": event.id, "needs_review": event.needs_review}

    return await run_admin_job("Approve submission", _run())


class _ResolutionBody(BaseModel):
    resolution_note: str


@router.get("/reports", dependencies=[Depends(_require_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
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
) -> dict:
    """Content-moderation review queue: one row per event aggregating its
    REPORT_STATUS_OPEN reports (distinct from GET /admin/submissions, which
    is organizer-trust review — see CONTEXT.md's Report/Resolve glossary).
    Excludes cancelled events. ``reason``/``illegal_only`` narrow which
    events qualify for the queue (an event with at least one matching open
    report); each qualifying event's row still aggregates *all* of its open
    reports, not just the matching ones. Ordered illegal-first, then by
    report count, then oldest-waiting first.
    """
    if reason is not None:
        validate_report_reason(reason)

    match_conditions = [EventReport.status == REPORT_STATUS_OPEN]
    if reason is not None:
        match_conditions.append(EventReport.reason == reason)
    if illegal_only:
        match_conditions.append(EventReport.is_illegal_allegation.is_(True))

    matching_event_ids = select(EventReport.event_id).where(*match_conditions).distinct()

    has_illegal_col = func.bool_or(EventReport.is_illegal_allegation).label(
        "has_illegal_allegation"
    )
    report_count_col = func.count(EventReport.id).label("report_count")
    oldest_col = func.min(EventReport.created_at).label("oldest_open_report_at")

    agg = (
        select(
            EventReport.event_id,
            has_illegal_col,
            report_count_col,
            oldest_col,
        )
        .join(Event, Event.id == EventReport.event_id)
        .where(
            EventReport.status == REPORT_STATUS_OPEN,
            Event.status != EVENT_STATUS_CANCELLED,
            EventReport.event_id.in_(matching_event_ids),
        )
        .group_by(EventReport.event_id)
    )

    async with AsyncSessionLocal() as db:
        total = (
            await db.scalar(select(func.count()).select_from(agg.subquery()))
        ) or 0

        page = (
            await db.execute(
                agg.order_by(
                    has_illegal_col.desc(), report_count_col.desc(), oldest_col.asc()
                )
                .limit(limit)
                .offset(offset)
            )
        ).all()

        event_ids = [row.event_id for row in page]
        events_by_id: dict[int, Event] = {}
        reports_by_event: dict[int, list[EventReport]] = {}
        if event_ids:
            events = (
                await db.scalars(select(Event).where(Event.id.in_(event_ids)))
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
                "venue": event.venue_name,
                "submitted_by_organizer_id": event.submitted_by_organizer_id,
                "report_count": row.report_count,
                "reasons": sorted({r.reason for r in event_reports}),
                "has_illegal_allegation": bool(row.has_illegal_allegation),
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
        "has_more": offset + len(rows) < total,
        "events": rows,
    }


async def _event_or_404(db: AsyncSession, event_id: int) -> Event:
    event = await db.get(Event, event_id)
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_EVENT_NOT_FOUND
        )
    return event


def _validated_resolution_note(body: _ResolutionBody) -> str:
    note = body.resolution_note.strip()
    if not note:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=ERROR_RESOLUTION_NOTE_REQUIRED,
        )
    return note


@router.post(
    "/reports/{event_id}/resolve", dependencies=[Depends(_require_admin)]
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
            await db.commit()
            await send_report_resolution_emails(db, event, resolved, note)
            return {"event_id": event.id, "resolved_count": len(resolved)}

    return await run_admin_job("Resolve reports", _run())


@router.post(
    "/reports/{event_id}/takedown", dependencies=[Depends(_require_admin)]
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
            await db.commit()
            await send_report_resolution_emails(db, event, resolved, note)
            return {
                "event_id": event.id,
                "status": event.status,
                "resolved_count": len(resolved),
            }

    return await run_admin_job("Takedown reported event", _run())


@router.post("/classify", dependencies=[Depends(_require_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_classify(request: Request) -> dict:
    """Trigger LLM classification, draining the backlog until it clears or the cap is hit."""
    return await run_admin_job("Classification", classify_pending_drain_now())


@router.post("/publish", dependencies=[Depends(_require_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_publish(request: Request) -> dict:
    """Promote qualifying classified events to published (one bulk UPDATE)."""
    return await run_admin_job("Publish", publish_pending_job())


@router.post("/geocode", dependencies=[Depends(_require_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_geocode(request: Request) -> dict:
    """Backfill lat/lng for events with a venue_address but no coordinates (one batch)."""
    return await run_admin_job("Geocoding", geocode_pending_job())


@router.post("/refetch", dependencies=[Depends(_require_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_refetch(request: Request) -> dict:
    """Re-fetch detail pages for all future events and reconcile stored fields (one batch).

    Standalone, like /admin/geocode — not part of /admin/pipeline/run. Run it
    before a manual geocode if you want coords NULLed by an address change
    re-resolved in the same operation.
    """
    return await run_admin_job("Refetch", refetch_event_details_job())


@router.post("/sync-organizers", dependencies=[Depends(_require_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_sync_organizers(request: Request) -> dict:
    """Trigger Fienta organizer sync (discover new organizers, flag stale ones)."""
    return await run_admin_job(
        "Organizer sync", run_in_session(sync_fienta_organizers, commit=True)
    )


@router.post("/cleanup", dependencies=[Depends(_require_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_cleanup(
    request: Request,
    dry_run: bool = Query(
        True,
        description="When true (default), counts candidate rows but deletes nothing",
    ),
) -> dict:
    """Trigger data retention cleanup (prunes satellite tables; never events).

    Defaults to dry-run, matching every other destructive admin/maintenance
    tool in this codebase (reset_events.py, /admin/pipeline/run) — pass
    ?dry_run=false to actually delete.

    See app.cleanup.cleanup_stale_data for the per-table retention windows.
    """
    return await run_admin_job(
        "Cleanup",
        run_in_session(
            lambda db: cleanup_stale_data(db, dry_run=dry_run), commit=not dry_run
        ),
    )


@router.post("/build-feeds", dependencies=[Depends(_require_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_build_feeds(request: Request) -> dict:
    """Trigger daily feed builder for all active users (writes to daily_feeds)."""
    # build_daily_feeds commits internally (score.py); no second commit needed.
    return await run_admin_job(
        "Feed build", run_in_session(build_daily_feeds, commit=False)
    )


@router.post("/send-digests", dependencies=[Depends(_require_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_send_digests(
    request: Request,
    dry_run: bool = Query(True, description="When true (default), counts would-send but skips actual email delivery"),
) -> dict:
    """Trigger daily digest send. Defaults to dry-run — pass ?dry_run=false to actually send."""
    return await run_admin_job(
        "Digest send",
        run_in_session(lambda db: send_daily_digests(db, dry_run=dry_run), commit=False),
    )


@router.post("/pipeline/run", dependencies=[Depends(_require_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_pipeline_run(
    request: Request,
    dry_run: bool = Query(True, description="When true (default), digest stage counts would-send but skips actual email delivery"),
) -> dict:
    """Run all seven pipeline stages in dependency order.

    Stops at the first failure — later stages depend on earlier output.
    Returns {ok, stages} where stages is an ordered dict of per-stage results.
    """
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
    for stage_name, runner in stage_runners:
        try:
            stages[stage_name] = await runner()
        except Exception:
            log.exception("pipeline: %s failed", stage_name)
            stages[stage_name] = {"error": f"{stage_name} failed; see server logs"}
            return {"ok": False, "stages": stages}

    return {"ok": True, "stages": stages}


@router.get("/stats", dependencies=[Depends(_require_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_stats(request: Request) -> dict:
    """Aggregate counts used by checkpoint tests and manual monitoring."""
    async with AsyncSessionLocal() as db:
        total = (
            await db.scalar(
                select(func.count(Event.id)).where(
                    Event.status != EVENT_STATUS_CANCELLED
                )
            )
        ) or 0

        canonical = (
            await db.scalar(
                select(func.count(Event.id)).where(
                    Event.status != EVENT_STATUS_CANCELLED,
                    canonical_event_filter(),
                )
            )
        ) or 0

        sources_total = (await db.scalar(select(func.count(Source.id)))) or 0
        sources_enabled = (
            await db.scalar(
                select(func.count(Source.id)).where(Source.enabled.is_(True))
            )
        ) or 0

    return {
        "events": {"total": total, "canonical": canonical},
        "sources": {"total": sources_total, "enabled": sources_enabled},
    }
