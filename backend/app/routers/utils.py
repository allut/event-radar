"""Shared serialization helpers for event routers."""

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, Response, status
from itsdangerous import BadSignature, SignatureExpired
from pydantic import BaseModel, EmailStr
from sqlalchemy import ColumnElement, Select, and_, delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, selectinload

from app.auth.tokens import verify_session_token
from app.constants import (
    APP_ENV_DEVELOPMENT,
    DEFAULT_USER_LOCALE,
    EMAIL_MASK_VISIBLE_CHARS,
    ERROR_ADMIN_JOB_ALREADY_RUNNING,
    ERROR_ADMIN_JOB_FAILED,
    ERROR_FEATURE_DISABLED,
    ERROR_INVALID_REPORT_REASON,
    EVENT_STATUS_CANCELLED,
    EVENT_STATUS_PUBLISHED,
    LOG_EVENT_ADMIN_ACTION,
    LOG_EVENT_EMAIL_SEND_FAILED,
    MASK_DB_URL_PASSWORD_RE,
    MAGIC_LINK_RESEND_COOLDOWN_SECONDS,
    PREFERENCE_SIGNALS,
    PREFERRED_TASTE_MIN_WEIGHT,
    REPORT_STATUS_OPEN,
    REPORT_STATUS_RESOLVED,
    SESSION_COOKIE_HTTPONLY,
    SESSION_COOKIE_SAMESITE,
    SESSION_COOKIE_SECURE,
    VALID_LOCALES,
    VALID_REPORT_REASONS,
)
from app.db import AsyncSessionLocal
from app.email.report_reporter import send_report_outcome_email
from app.models.models import (
    Event,
    EventClassification,
    EventReport,
    Persona,
    User,
    UserEventFeedback,
    UserEventScore,
    UserPersona,
)

log = logging.getLogger(__name__)


class RequestLinkBody(BaseModel):
    """Shared magic-link request body — consumer (routers/auth.py) and
    organizer (routers/organizer_auth.py) tracks use the identical shape."""

    email: EmailStr
    locale: str | None = None


class VerifyTokenBody(BaseModel):
    """Shared /verify request body — the magic-link token moves from a query
    parameter to the body so it stops landing in server access logs (Vercel
    edge, Render). Identical shape for both auth tracks, mirroring
    RequestLinkBody."""

    token: str


def set_session_cookie(
    response: Response, *, name: str, token: str, path: str, ttl_seconds: int
) -> None:
    """Set a hardened session cookie — shared by the consumer, organizer, and
    admin /verify|/login endpoints. Secure is unconditional (never gated on
    APP_ENV): see docs/adr/0001-session-tokens-in-httponly-cookies.md."""
    response.set_cookie(
        key=name,
        value=token,
        max_age=ttl_seconds,
        path=path,
        secure=SESSION_COOKIE_SECURE,
        httponly=SESSION_COOKIE_HTTPONLY,
        samesite=SESSION_COOKIE_SAMESITE,
    )


def clear_session_cookie(response: Response, *, name: str, path: str) -> None:
    """Expire a session cookie (sign-out and logout-all). Attributes must
    match set_session_cookie's for the browser to actually replace/clear the
    cookie rather than setting a second, distinct one."""
    response.delete_cookie(
        key=name,
        path=path,
        secure=SESSION_COOKIE_SECURE,
        httponly=SESSION_COOKIE_HTTPONLY,
        samesite=SESSION_COOKIE_SAMESITE,
    )


async def run_in_session(
    func: Callable[[AsyncSession], Awaitable[dict]], *, commit: bool
) -> dict:
    """Run a session-scoped job: open a session, run ``func(db)``, commit when
    asked, roll back and re-raise on failure.

    Shared by every scheduler/admin entry point that needs its own session
    (app/main.py's scheduled jobs and app/routers/admin.py's manual triggers).
    """
    async with AsyncSessionLocal() as db:
        try:
            result = await func(db)
            if commit:
                await db.commit()
            return result
        except Exception:
            await db.rollback()
            raise


async def recent_unused_link_exists(
    db: AsyncSession,
    model: type[Any],
    fk_column: InstrumentedAttribute[Any],
    fk_value: int,
    ttl_seconds: int,
) -> bool:
    """Per-account magic-link resend cooldown, shared by the consumer
    (routers/auth.py) and organizer (routers/organizer_auth.py) auth tracks.

    True if an unused link (identified by ``fk_column == fk_value`` on
    ``model``, which must carry ``used_at``/``expires_at`` columns like
    AuthMagicLink/OrganizerMagicLink) was issued within
    MAGIC_LINK_RESEND_COOLDOWN_SECONDS of now.

    A link created T seconds ago has expires_at = now + (ttl_seconds - T), so
    expires_at > now + ttl_seconds - cooldown <-> T < cooldown. Prevents
    Resend quota exhaustion from rapid repeats; IP-level throttling is the
    separate @limiter.limit decorator on the request-link endpoint.
    """
    recent_cutoff = datetime.now(timezone.utc) + timedelta(
        seconds=ttl_seconds - MAGIC_LINK_RESEND_COOLDOWN_SECONDS
    )
    already_sent = await db.scalar(
        select(model)
        .where(
            fk_column == fk_value,
            model.used_at.is_(None),
            model.expires_at > recent_cutoff,
        )
        .limit(1)
    )
    return already_sent is not None


_RUNNING_ADMIN_JOBS: set[str] = set()


def acquire_admin_job_lock(key: str) -> None:
    """Single-flight guard for the expensive/destructive triggers (issue
    #160): pipeline/run, cleanup, full ingest, send_digests, classify. Raises
    409 if *key* is already running instead of letting a retry click start a
    second concurrent run. In-memory only — fine given this app's
    single-process topology (see CLAUDE.md's Architecture section)."""
    if key in _RUNNING_ADMIN_JOBS:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ERROR_ADMIN_JOB_ALREADY_RUNNING.format(name=key),
        )
    _RUNNING_ADMIN_JOBS.add(key)


def release_admin_job_lock(key: str) -> None:
    _RUNNING_ADMIN_JOBS.discard(key)


async def run_admin_job(name: str, coro: Awaitable[dict]) -> dict:
    """Await an admin-triggered job, converting any failure into a generic 500.

    Shared by every /admin/* trigger endpoint: the full traceback goes to the
    server log; the response detail stays generic so internals never leak.
    """
    try:
        return await coro
    except HTTPException:
        raise
    except Exception:
        log.exception("admin %s failed", name)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=ERROR_ADMIN_JOB_FAILED.format(name=name),
        )


def ndjson_line(stage: str, status_: str, result: Any, error: str | None) -> bytes:
    """One line of the shared streamed-job envelope (issue #159) — every
    /admin/* job trigger streams this shape, one line per stage."""
    return (
        json.dumps({"stage": stage, "status": status_, "result": result, "error": error})
        + "\n"
    ).encode()


async def stream_admin_job(
    name: str,
    stage: str,
    action: str,
    target: int | str,
    coro: Awaitable[dict],
    lock_key: str | None = None,
) -> AsyncIterator[bytes]:
    """Streaming sibling of run_admin_job: runs *coro* and yields a single
    NDJSON envelope line instead of returning a dict. A failure becomes a
    status="error" line rather than an HTTP 500 — once the stream has
    started, headers are already sent, so the generic-failure behavior
    (server log gets the traceback, client gets a generic message, no
    internals leak) has to travel inside the body instead of the status
    code.

    *coro* runs as an independent task, not a direct `await` in this
    generator's own frame. A client disconnect makes Starlette cancel this
    generator (StreamingResponse races `listen_for_disconnect` against the
    body on uvicorn's pinned ASGI spec_version "2.3", cancelling whichever
    task is streaming — see docs/research/2026-08-23-admin-console-timeout-
    ceilings.md finding 5 / issue #159); a direct `await coro` would let
    that cancellation propagate straight into the job and cut it off
    mid-write. Awaiting `queue.get()` instead means the generator's own
    cancellation never touches the task, so the job always runs to
    completion regardless of whether anyone is still listening."""
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def _runner() -> None:
        try:
            result = await coro
            log_admin_action(action, target, result)
            await queue.put(ndjson_line(stage, "ok", result, None))
        except HTTPException as exc:
            detail = str(exc.detail)
            log_admin_action(action, target, {"error": detail})
            await queue.put(ndjson_line(stage, "error", None, detail))
        except Exception:
            log.exception("admin %s failed", name)
            detail = ERROR_ADMIN_JOB_FAILED.format(name=name)
            log_admin_action(action, target, {"error": detail})
            await queue.put(ndjson_line(stage, "error", None, detail))
        finally:
            if lock_key is not None:
                release_admin_job_lock(lock_key)
            await queue.put(None)

    asyncio.ensure_future(_runner())
    while True:
        line = await queue.get()
        if line is None:
            return
        yield line


def log_admin_action(action: str, target: int | str, result: dict) -> None:
    """Passive "did I already do this" record on the shared Axiom pipe — no
    DB table, one admin always the actor (see the admin-console spec's
    Audit logging section). Call after a mutating /admin/* action succeeds."""
    log.info(
        "admin action: %s",
        action,
        extra={
            "event": LOG_EVENT_ADMIN_ACTION,
            "action": action,
            "target": target,
            "result": result,
        },
    )


def require_configured_secret(
    secret: str | None,
    *,
    feature: str,
    setting_name: str,
    app_env: str,
    allow_insecure_dev: bool = False,
) -> bool:
    """Fail-closed gate shared by every secret-protected surface (admin auth,
    inbound webhook, /internal/tick).

    Returns True when the secret is configured — the caller must then verify
    it. When unset: 503 unless BOTH ``app_env == development`` AND
    ``allow_insecure_dev`` are true, in which case a warning is logged and
    False is returned (caller skips verification). Requiring the second,
    explicit opt-in (settings.ALLOW_INSECURE_DEV) means a dev-shaped APP_ENV
    alone — e.g. a misconfigured or never-overridden env var on a real
    deployment — can never silently open the admin surface, the inbound
    webhook, or /internal/tick. Callers pass their own module's ``settings``
    values so tests that patch the caller's settings keep working.
    """
    if secret:
        return True
    if not (app_env == APP_ENV_DEVELOPMENT and allow_insecure_dev):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ERROR_FEATURE_DISABLED.format(
                feature=feature, setting_name=setting_name
            ),
        )
    log.warning(
        "%s not set; %s unprotected (development mode, ALLOW_INSECURE_DEV=true)",
        setting_name,
        feature,
    )
    return False


async def invalidate_user_scores(db: AsyncSession, user_id: int) -> None:
    """Delete ALL cached ranking scores for a user.

    A change to the user's personas or feedback shifts the affinity /
    indirect-feedback terms across every co-categorical event, so per-row
    invalidation would leave neighbours stale. Callers must invalidate before
    rebuilding the feed.
    """
    await db.execute(delete(UserEventScore).where(UserEventScore.user_id == user_id))


def mask_db_url(url: str) -> str:
    """Redact the password in a DB URL for safe logging (``user:pass@host`` ->
    ``user:***@host``). Shared by the maintenance scripts in ``backend/scripts``."""
    return re.sub(MASK_DB_URL_PASSWORD_RE, ":***@", url)


def normalized_title(title: str) -> str:
    """Canonical title key: lowercase + collapse all internal whitespace.

    Shared by dedup same-day bucketing (``apply_same_day_title_unions``) and the
    feed-level series identity (``event_series_key``) so both agree on what
    counts as "the same title".
    """
    return " ".join(title.lower().split())


def event_series_key(title_orig: str, venue_name: str | None) -> tuple[str, str]:
    """Identity of an ongoing series, independent of ``starts_at``.

    Deliberately broader than the dedup same-day title bucket (which is per-day
    and feeds dedup) and independent of ``dedup_group_id`` (multi-day series are
    intentionally not dedup-grouped). Used by the Daily 5 builder to cool down a
    series already surfaced within the recent cooldown window.

    Both halves go through ``normalized_title`` (lowercase + collapse internal
    whitespace) so the same series still matches across minor venue-string drift
    between ingest/refetch passes. Match is exact on the normalized key — venue
    respellings beyond whitespace/case (a parenthetical suffix, a translation)
    are an accepted limitation, since the cooldown is a soft feed-diversity
    filter, not a correctness gate.
    """
    return (normalized_title(title_orig), normalized_title(venue_name or ""))


def persona_weight_tuple(
    user_persona: UserPersona, persona: Persona | None = None
) -> tuple[float, dict]:
    """(weight, affinity_vector) shape consumed by ``ranking/score.py::persona_affinity``.

    Shared by the single-user load in browse.py and the bulk multi-user load in
    ranking/score.py::build_daily_feeds, which query ``UserPersona`` differently
    (single vs. ``user_id.in_(...)``) but must agree on this row->tuple mapping.
    ``persona`` covers routers/settings.py's ``(UserPersona, Persona)``-tuple
    join query, which loads the row directly rather than via the
    ``UserPersona.persona`` relationship; omit it when that relationship is
    already eager-loaded (browse.py/score.py both ``selectinload`` it).
    """
    return (
        user_persona.weight,
        (persona if persona is not None else user_persona.persona).affinity_vector,
    )


def canonical_event_filter() -> ColumnElement[bool]:
    """Event is dedup-canonical: ungrouped, or the representative of its group.

    Shared by any query that must not surface a duplicate a second time —
    ``classify_pending`` only classifies canonical drafts, ``admin_stats``
    counts canonical events, and the Daily 5 candidate query excludes
    non-canonical duplicates that were somehow already published (dedup
    normally runs before classify/publish, so this is a defense-in-depth
    backstop, not the primary suppression mechanism).
    """
    return or_(Event.dedup_group_id.is_(None), Event.dedup_group_id == Event.id)


def public_event_filter() -> ColumnElement[bool]:
    """Event is publicly visible: published, and neither explicit nor a non-event.

    Shared by any endpoint that accepts a caller-supplied event_id and must not
    leak the existence of a draft/hidden/explicit/non-event row via a 200-vs-404
    timing or status-code oracle (e.g. GET /events/{id}, POST /feedback).
    """
    return and_(
        Event.status == EVENT_STATUS_PUBLISHED,
        Event.is_explicit.is_(False),
        Event.is_non_event.is_(False),
    )


def event_not_ended_filter(now: datetime, entity: Any = Event) -> ColumnElement[bool]:
    """Event is live (publishable / feed-eligible) until it ends.

    Uses ``ends_at`` when present, else falls back to ``starts_at``. A past
    ``starts_at`` with a future ``ends_at`` (multi-day runs, ongoing
    exhibitions) stays live — only a genuinely-over event fails this.

    ``entity`` accepts ``Event`` (default) or an ``aliased(Event)`` so
    self-join clauses reuse this definition instead of re-deriving it.
    """
    return or_(
        entity.ends_at >= now,
        and_(entity.ends_at.is_(None), entity.starts_at >= now),
    )


def event_ended_filter(now: datetime, entity: Any = Event) -> ColumnElement[bool]:
    """Event has ended — the NULL-safe complement of ``event_not_ended_filter``.

    ``~event_not_ended_filter(now)`` is NOT equivalent: when ``ends_at IS
    NULL`` and ``starts_at < now``, ``event_not_ended_filter`` evaluates to
    SQL NULL (three-valued logic on ``ends_at >= now``), and ``NOT NULL`` is
    also NULL — which a WHERE clause treats as non-matching. That silently
    excludes exactly the ended, no-``ends_at`` events callers usually mean to
    catch (e.g. bulk-cancelling stale drafts), so build the negation
    explicitly instead of negating the nullable expression.
    """
    return or_(
        entity.ends_at < now,
        and_(entity.ends_at.is_(None), entity.starts_at < now),
    )


def mask_email(email: str) -> str:
    """Mask an email for log output — keep the first few local-part characters and
    the full domain so entries stay correlatable without persisting raw PII in
    cleartext logs (e.g. 'aleksei.lutkov@gmail.com' -> 'al***@gmail.com')."""
    local, sep, domain = email.partition("@")
    if not sep:
        return "***"
    return f"{local[:EMAIL_MASK_VISIBLE_CHARS]}***@{domain}"


def compute_preferred_taxonomy(
    user_persona_weights: list[tuple[float, dict]],
) -> tuple[list[str], list[str]]:
    """(preferred_categories, preferred_vibes) — the union, across every persona
    the user has, of category/vibe tags whose affinity_vector weight clears
    ``PREFERRED_TASTE_MIN_WEIGHT``.

    Drives the /explore For-you⇄All-events auto-flip (frontend): selecting a
    facet outside this "in taste" set switches the user out of For-you mode.
    Sorted for a deterministic response.
    """
    categories: set[str] = set()
    vibes: set[str] = set()
    for _weight, vector in user_persona_weights:
        cat_map: dict[str, float] = vector.get("categories", {})
        vibe_map: dict[str, float] = vector.get("vibes", {})
        categories.update(
            c for c, w in cat_map.items() if w >= PREFERRED_TASTE_MIN_WEIGHT
        )
        vibes.update(v for v, w in vibe_map.items() if w >= PREFERRED_TASTE_MIN_WEIGHT)
    return sorted(categories), sorted(vibes)


def serialize_user(user: User, **extras) -> dict:
    """Return canonical user envelope. Extra keys (e.g. has_personas, personas) via kwargs."""
    return {
        "id": user.id,
        "email": user.email,
        "locale": user.locale,
        "home_city": user.home_city,
        "created_at": user.created_at.isoformat(),
        **extras,
    }


def parse_session_cookie_user(session: str | None) -> tuple[int, int] | None:
    """(user_id, token_version) from the session cookie value, or None when
    the cookie is absent or the token is expired/invalid."""
    if not isinstance(session, str):
        return None
    try:
        return verify_session_token(session)
    except (SignatureExpired, BadSignature):
        return None


def select_events_with_classification() -> Select[tuple[Event]]:
    """Base SELECT for Event with classification eager-loaded. Callers add their own .where()."""
    return select(Event).options(selectinload(Event.classification))


def resolve_locale_param(locale: str | None, fallback: str) -> str:
    """Validate an optional ?locale= param, falling back when absent/invalid."""
    return locale if locale in VALID_LOCALES else fallback


def resolve_title(event: Event, locale: str) -> str:
    """Return localized title with locale → en → title_orig fallback."""
    loc = event.title_localized
    if loc:
        result = loc.get(locale) or loc.get(DEFAULT_USER_LOCALE)
        if result:
            return result
    return event.title_orig


def resolve_description(event: Event, locale: str) -> str | None:
    """Return localized description with locale → en → description_orig fallback."""
    loc = event.description_localized
    if loc:
        result = loc.get(locale) or loc.get(DEFAULT_USER_LOCALE)
        if result:
            return result
    return event.description_orig


def resolve_important_info(event: Event, locale: str) -> str | None:
    """Return localized important_info with locale → en → plain fallback."""
    loc = event.important_info_localized
    if loc:
        result = loc.get(locale) or loc.get(DEFAULT_USER_LOCALE)
        if result:
            return result
    return event.important_info


def resolve_why_go(cl: EventClassification | None, locale: str) -> list[str]:
    """Return localized why_go bullets for a classification, with locale → en → raw fallback."""
    if cl is None:
        return []
    if cl.why_go_localized:
        return (
            cl.why_go_localized.get(locale)
            or cl.why_go_localized.get(DEFAULT_USER_LOCALE)
            or cl.why_go_bullets
            or []
        )
    return cl.why_go_bullets or []


def serialize_event(
    event: Event,
    locale: str = DEFAULT_USER_LOCALE,
    feedback_by_event: dict[int, str] | None = None,
    reported_event_ids: set[int] | None = None,
) -> dict:
    cl = event.classification
    why_go = resolve_why_go(cl, locale)
    return {
        "id": event.id,
        "slug": event.slug,
        "title": resolve_title(event, locale),
        "description": resolve_description(event, locale),
        "important_info": resolve_important_info(event, locale),
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
        "has_free_tier": event.has_free_tier,
        "categories": cl.categories if cl else [],
        "vibes": cl.vibes if cl else [],
        "why_go": why_go,
        "quality_score": cl.quality_score if cl else None,
        "language": cl.language_detected if cl else None,
        "my_signal": feedback_by_event.get(event.id) if feedback_by_event else None,
        "reported": event.id in reported_event_ids if reported_event_ids else False,
    }


async def load_user_signals(
    db: AsyncSession, user_id: int, event_ids: list[int]
) -> dict[int, str]:
    """(event_id -> signal) for the given user's current *preference* signal
    (like/dislike/bookmark) on these events.

    One query, no N+1 — shared by feed/browse/events/saved read paths so each
    hydrates ``serialize_event``'s ``my_signal`` field from a single bulk fetch.
    Deliberately restricted to ``PREFERENCE_SIGNALS``: "view"/"click_external"
    are passive analytics signals that can have multiple rows per (user,
    event) (see feedback.py::record_feedback), so an unfiltered query here
    could non-deterministically surface one of those instead of the user's
    actual bookmark/like/dislike — and "click_external" isn't even a valid
    frontend ``Signal``.
    """
    if not event_ids:
        return {}
    rows = (
        await db.execute(
            select(UserEventFeedback.event_id, UserEventFeedback.signal).where(
                UserEventFeedback.user_id == user_id,
                UserEventFeedback.event_id.in_(event_ids),
                UserEventFeedback.signal.in_(PREFERENCE_SIGNALS),
            )
        )
    ).all()
    return {row.event_id: row.signal for row in rows}


async def load_user_reported_events(
    db: AsyncSession, user_id: int, event_ids: list[int]
) -> set[int]:
    """Event IDs among ``event_ids`` the given user currently has an *open*
    report on — feeds ``serialize_event``'s ``reported`` field.

    Restricted to ``REPORT_STATUS_OPEN`` (not any status): a resolved report
    must not render as "Reported" in the frontend menu, since a resolved
    report is deliberately re-reportable (see event_reports upsert/reopen
    semantics in routers/reports.py).
    """
    if not event_ids:
        return set()
    rows = (
        await db.execute(
            select(EventReport.event_id).where(
                EventReport.user_id == user_id,
                EventReport.event_id.in_(event_ids),
                EventReport.status == REPORT_STATUS_OPEN,
            )
        )
    ).all()
    return {row.event_id for row in rows}


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
    resolved_at = datetime.now(timezone.utc)
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
    for report in reports:
        reporter = users_by_id.get(report.user_id)
        if reporter is None:
            continue
        try:
            await send_report_outcome_email(
                reporter.email, event, resolution_note, reporter.locale
            )
        except Exception:
            log.error(
                "Failed to send report outcome email (report_id=%s, event_id=%s)",
                report.id,
                event.id,
                exc_info=True,
                extra={"event": LOG_EVENT_EMAIL_SEND_FAILED},
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


def validate_report_reason(reason: str) -> None:
    """Shared by POST /reports and GET /admin/reports's ``reason`` filter —
    a single source of truth for the taxonomy check and its error message."""
    if reason not in VALID_REPORT_REASONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_INVALID_REPORT_REASON.format(reasons=sorted(VALID_REPORT_REASONS)),
        )
