"""Admin endpoints — protected by HTTP Basic auth."""

import asyncio
import logging
import secrets
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from datetime import datetime

from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from itsdangerous import BadSignature, SignatureExpired
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import verify_admin_session_token
from app.cleanup import cleanup_stale_data
from app.config import settings
from app.constants import (
    ADMIN_ACTION_APPROVE_SUBMISSION,
    ADMIN_ACTION_BUILD_FEEDS,
    ADMIN_ACTION_CLEANUP,
    ADMIN_ACTION_CLASSIFY,
    ADMIN_ACTION_DEDUP,
    ADMIN_ACTION_GEOCODE,
    ADMIN_ACTION_INGEST,
    ADMIN_ACTION_INGEST_SOURCE,
    ADMIN_ACTION_PIPELINE_RUN,
    ADMIN_ACTION_PUBLISH,
    ADMIN_ACTION_REFETCH,
    ADMIN_ACTION_RESOLVE_REPORTS,
    ADMIN_ACTION_RETRACT_SUBMISSION,
    ADMIN_ACTION_SEND_DIGESTS,
    ADMIN_ACTION_SYNC_ORGANIZERS,
    ADMIN_ACTION_TAKEDOWN_REPORTED_EVENT,
    ADMIN_AUTH_FAILURES_MAX_ENTRIES,
    ADMIN_AUTH_LOCKOUT_SECONDS,
    ADMIN_AUTH_MAX_FAILURES,
    ADMIN_DEDUP_GROUPS_MAX_PAGE_SIZE,
    ADMIN_DEDUP_GROUPS_PAGE_SIZE,
    ADMIN_EVENT_INSPECTOR_RAW_EVENTS_LIMIT,
    ADMIN_REVIEW_QUEUE_MAX_PAGE_SIZE,
    ADMIN_REVIEW_QUEUE_PAGE_SIZE,
    ADMIN_SESSION_COOKIE_NAME,
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
    TALLINN_TZ,
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
from app.models.models import (
    DailyFeed,
    Event,
    EventReport,
    EventSource,
    Organizer,
    RawEvent,
    Source,
)
from app.publish import publish_pending
from app.ranking.score import build_daily_feeds
from app.rate_limit import client_key, limiter
from app.routers.utils import (
    cancel_event_and_resolve_reports,
    canonical_event_filter,
    log_admin_action,
    ndjson_line,
    require_configured_secret,
    resolve_open_reports,
    run_admin_job,
    run_in_session,
    select_events_with_classification,
    send_report_resolution_emails,
    serialize_event,
    stream_admin_job,
    validate_report_reason,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/admin")
# auto_error=False: a request carrying the admin session cookie instead of a
# Basic header must not be auto-rejected before _require_admin gets a chance
# to check the cookie — see _require_admin below.
_security = HTTPBasic(auto_error=False)

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


def check_admin_lockout(key: str) -> float:
    """Raise 429 if `key` is currently locked out; otherwise return
    time.monotonic() for the caller to reuse (avoids a second clock read).
    Shared by _require_admin (Basic auth) and routers/admin_auth.py's form
    login — ticket #154 requires both auth surfaces to share one lockout
    counter rather than each getting its own damper."""
    now = time.monotonic()
    _count, locked_until = _admin_auth_failures.get(key, (0, 0.0))
    if now < locked_until:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=ERROR_ADMIN_LOCKOUT,
        )
    return now


def record_admin_auth_failure(key: str, now: float, username: str) -> None:
    """Bump the consecutive-failure count for `key`, locking it out once
    ADMIN_AUTH_MAX_FAILURES is reached. Shared with routers/admin_auth.py —
    see check_admin_lockout."""
    count, _locked = _admin_auth_failures.get(key, (0, 0.0))
    failures = count + 1
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
        username,
        failures,
        extra={"event": LOG_EVENT_AUTH_FAILED},
    )


def clear_admin_auth_failure(key: str) -> None:
    """Reset `key`'s failure count on a successful login. Shared with
    routers/admin_auth.py — see check_admin_lockout."""
    _admin_auth_failures.pop(key, None)


def admin_username_disabled() -> bool:
    """True when ADMIN_USERNAME was never overridden from its well-known
    default outside development — fail closed like the password check,
    since a well-known username halves the credential pair an attacker
    needs to brute-force. Shared with routers/admin_auth.py."""
    return (
        settings.ADMIN_USERNAME == ADMIN_USERNAME_DEFAULT
        and settings.APP_ENV != APP_ENV_DEVELOPMENT
    )


def admin_credentials_ok(username: str, password: str) -> bool:
    """Constant-time check of a username/password attempt against the
    configured ADMIN_USERNAME/ADMIN_PASSWORD. Shared with
    routers/admin_auth.py — caller is responsible for the
    require_configured_secret/admin_username_disabled gates around this."""
    username_ok = secrets.compare_digest(
        username.encode(), settings.ADMIN_USERNAME.encode()
    )
    password_ok = secrets.compare_digest(
        password.encode(), settings.ADMIN_PASSWORD.encode()
    )
    return username_ok and password_ok


def _valid_admin_session(admin_session: str) -> bool:
    try:
        verify_admin_session_token(admin_session)
        return True
    except (SignatureExpired, BadSignature):
        return False


def _require_admin(
    request: Request,
    credentials: HTTPBasicCredentials | None = Depends(_security),
    admin_session: str | None = Cookie(default=None, alias=ADMIN_SESSION_COOKIE_NAME),
) -> None:
    """Accept EITHER a valid admin console session cookie (issued by
    POST /admin/auth/login) OR HTTP Basic (curl / existing integrations) —
    see docs/backend-ops.md's Admin Endpoints section. An invalid/expired
    cookie falls through to requiring Basic rather than rejecting outright,
    so a stale browser cookie doesn't lock a curl caller out of the same
    request path."""
    if admin_session is not None and _valid_admin_session(admin_session):
        return

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_ADMIN_INCORRECT_CREDENTIALS,
            headers={"WWW-Authenticate": "Basic"},
        )

    key = client_key(request)
    now = check_admin_lockout(key)

    password = settings.ADMIN_PASSWORD
    if not require_configured_secret(
        password,
        feature="Admin endpoints",
        setting_name="ADMIN_PASSWORD",
        app_env=settings.APP_ENV,
        allow_insecure_dev=settings.ALLOW_INSECURE_DEV,
    ):
        return
    if admin_username_disabled():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ERROR_ADMIN_DISABLED,
        )
    if not admin_credentials_ok(credentials.username, credentials.password):
        record_admin_auth_failure(key, now, credentials.username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=ERROR_ADMIN_INCORRECT_CREDENTIALS,
            headers={"WWW-Authenticate": "Basic"},
        )
    clear_admin_auth_failure(key)


def _ndjson_response(gen: AsyncIterator[bytes]) -> StreamingResponse:
    """Shared streamed-envelope response wrapper (issue #159) — every job
    trigger endpoint streams NDJSON with caching disabled unconditionally."""
    return StreamingResponse(
        gen, media_type="application/x-ndjson", headers={"Cache-Control": "no-store"}
    )


@router.post("/ingest", dependencies=[Depends(_require_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_ingest_all(request: Request) -> StreamingResponse:
    """Trigger ingestion for all enabled sources."""

    async def _run() -> dict:
        return {"results": await ingest_all_enabled()}

    return _ndjson_response(
        stream_admin_job("Ingestion", "ingest", ADMIN_ACTION_INGEST, "all", _run())
    )


@router.post("/ingest/{slug}", dependencies=[Depends(_require_admin)])
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


@router.post("/dedup", dependencies=[Depends(_require_admin)])
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
        "venue": e.venue_name,
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


class _ResolutionBody(BaseModel):
    resolution_note: str


def _validated_resolution_note(body: _ResolutionBody) -> str:
    note = body.resolution_note.strip()
    if not note:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=ERROR_RESOLUTION_NOTE_REQUIRED,
        )
    return note


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
    "/submissions/{event_id}/retract", dependencies=[Depends(_require_admin)]
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
            await db.commit()
            await send_report_resolution_emails(
                db, event, resolved, REPORT_AUTO_RESOLVE_NOTE
            )
            return {"id": event.id, "status": event.status, "note": note}

    result = await run_admin_job("Retract submission", _run())
    log_admin_action(ADMIN_ACTION_RETRACT_SUBMISSION, event_id, result)
    return result


@router.post(
    "/submissions/{event_id}/approve", dependencies=[Depends(_require_admin)]
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
                if organizer is not None:
                    organizer.verified = True
            # organizer.verified flipping True can unlock this organizer's
            # whole backlog, not just this event — leave event_ids unscoped.
            # Diagnostic breakdown is unused by this endpoint's response.
            await publish_pending(db, diagnostics=False)
            await db.commit()
            return {"id": event.id, "needs_review": event.needs_review, "note": note}

    result = await run_admin_job("Approve submission", _run())
    log_admin_action(ADMIN_ACTION_APPROVE_SUBMISSION, event_id, result)
    return result


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


def _serialize_event_detail(event: Event) -> dict:
    cl = event.classification
    return {
        "id": event.id,
        "slug": event.slug,
        "title_orig": event.title_orig,
        "description_orig": event.description_orig,
        "important_info": event.important_info,
        "price_hint": event.price_hint,
        "starts_at": event.starts_at.isoformat(),
        "ends_at": event.ends_at.isoformat() if event.ends_at else None,
        "venue_name": event.venue_name,
        "venue_address": event.venue_address,
        "lat": event.lat,
        "lng": event.lng,
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
    }


@router.get("/events/{event_id}", dependencies=[Depends(_require_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_get_event(event_id: int, request: Request) -> dict:
    """Full-detail inspector payload for one event, any status (issue #157,
    part of #153). Curated projection, not a raw ORM dump — mirrors
    _serialize_dedup_groups' style. Dedup siblings and reports are fetched
    inline (cheap, already-indexed lookups), not separate round-trips.

    Feed-membership uses the `@>` (array-contains) operator, not `= ANY()` —
    the only one of the two the built-in GIN array_ops opclass can accelerate
    (see docs/research/2026-08-25-admin-console-feed-membership.md). Shipped
    with no new index initially per that research's recommendation.
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
                    select(Event).where(
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

    result = await run_admin_job("Resolve reports", _run())
    log_admin_action(ADMIN_ACTION_RESOLVE_REPORTS, event_id, result)
    return result


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

    result = await run_admin_job("Takedown reported event", _run())
    log_admin_action(ADMIN_ACTION_TAKEDOWN_REPORTED_EVENT, event_id, result)
    return result


@router.post("/classify", dependencies=[Depends(_require_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_classify(request: Request) -> StreamingResponse:
    """Trigger LLM classification, draining the backlog until it clears or the cap is hit."""
    return _ndjson_response(
        stream_admin_job(
            "Classification",
            "classify",
            ADMIN_ACTION_CLASSIFY,
            "classify",
            classify_pending_drain_now(),
        )
    )


@router.post("/publish", dependencies=[Depends(_require_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_publish(request: Request) -> StreamingResponse:
    """Promote qualifying classified events to published (one bulk UPDATE)."""
    return _ndjson_response(
        stream_admin_job(
            "Publish", "publish", ADMIN_ACTION_PUBLISH, "publish", publish_pending_job()
        )
    )


@router.post("/geocode", dependencies=[Depends(_require_admin)])
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


@router.post("/refetch", dependencies=[Depends(_require_admin)])
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


@router.post("/sync-organizers", dependencies=[Depends(_require_admin)])
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


@router.post("/cleanup", dependencies=[Depends(_require_admin)])
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
    return _ndjson_response(
        stream_admin_job(
            "Cleanup",
            "cleanup",
            ADMIN_ACTION_CLEANUP,
            "cleanup",
            run_in_session(
                lambda db: cleanup_stale_data(db, dry_run=dry_run), commit=not dry_run
            ),
        )
    )


@router.post("/build-feeds", dependencies=[Depends(_require_admin)])
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


@router.post("/send-digests", dependencies=[Depends(_require_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_send_digests(
    request: Request,
    dry_run: bool = Query(True, description="When true (default), counts would-send but skips actual email delivery"),
) -> StreamingResponse:
    """Trigger daily digest send. Defaults to dry-run — pass ?dry_run=false to actually send."""
    return _ndjson_response(
        stream_admin_job(
            "Digest send",
            "send_digests",
            ADMIN_ACTION_SEND_DIGESTS,
            "send_digests",
            run_in_session(lambda db: send_daily_digests(db, dry_run=dry_run), commit=False),
        )
    )


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

    log_admin_action(ADMIN_ACTION_PIPELINE_RUN, "pipeline", {"ok": ok, "stages": stages})
    await queue.put(None)


async def _stream_pipeline_run(dry_run: bool) -> AsyncIterator[bytes]:
    """Streams _run_pipeline_stages' output. Runs the stages as an
    independent task rather than a direct `await` in this generator's own
    frame — a client disconnect cancels this generator (Starlette's
    StreamingResponse races `listen_for_disconnect` against the body on
    uvicorn's pinned ASGI spec_version "2.3" — see docs/research/2026-08-23-
    admin-console-timeout-ceilings.md finding 5 / issue #159), and a direct
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


@router.post("/pipeline/run", dependencies=[Depends(_require_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_pipeline_run(
    request: Request,
    dry_run: bool = Query(True, description="When true (default), digest stage counts would-send but skips actual email delivery"),
) -> StreamingResponse:
    """Run all seven pipeline stages in dependency order, streamed as NDJSON
    (one line per completed stage — issue #159)."""
    return _ndjson_response(_stream_pipeline_run(dry_run))


@router.get("/counts", dependencies=[Depends(_require_admin)])
@limiter.shared_limit(RATE_LIMIT_ADMIN, scope="admin")
async def admin_counts(request: Request) -> dict:
    """Open-reports + pending-submissions counts for the admin console landing
    screen (issue #154). Mirrors the filters admin_list_reports/
    admin_list_submissions use for their own totals, so the landing tiles
    match what those (later-ticket) screens will show."""
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
                    Event.needs_review.is_(True),
                    Event.status != EVENT_STATUS_CANCELLED,
                )
            )
        ) or 0

    return {
        "open_reports": open_reports,
        "pending_submissions": pending_submissions,
    }


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
