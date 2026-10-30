"""Shared serialization helpers for event routers."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import HTTPException, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.auth.tokens import oauth_state_ttl_seconds
from app.config import settings
from app._generated.shared_constants import (
    DEFAULT_USER_LOCALE,
    GOOGLE_SIGNIN_RESULT_QUERY_PARAM,
    LOCALE_EN,
    LOCALE_RU,
    OAUTH_ERROR_QUERY_PARAM,
    ORGANIZER_MAX_CATEGORIES,
    PROMOTION_ERROR_REQUEST_DAILY_LIMIT,
    VALID_CATEGORIES,
    VALID_LOCALES,
)
from app.constants.admin import ERROR_ADMIN_JOB_ALREADY_RUNNING, ERROR_ADMIN_JOB_FAILED
from app.constants.auth import (
    IDENTITY_PROVIDER_GOOGLE,
    MAGIC_LINK_RESEND_COOLDOWN_SECONDS,
    OAUTH_STATE_COOKIE_SAMESITE,
    SESSION_COOKIE_HTTPONLY,
    SESSION_COOKIE_SAMESITE,
    SESSION_COOKIE_SECURE,
    UNVERIFIED_ACCOUNT_DAILY_BUDGET,
)
from app.constants.claims import (
    CLAIM_DNS_TXT_RECORD_LABEL,
    CLAIM_DNS_VERIFICATION_MECHANISMS,
    ERROR_CLAIM_EDIT_CATEGORIES_CAP,
)
from app.constants.core import LOCALE_ET, TALLINN_TZ
from app.constants.events import (
    EVENT_STATUS_CANCELLED,
    EVENT_STATUS_CLASSIFIED,
    EVENT_STATUS_PUBLISHED,
    PRICE_MAX_VALUE,
)
from app.constants.log_events import (
    LOG_EVENT_ADMIN_ACTION,
    LOG_EVENT_UNVERIFIED_ACCOUNT_BUDGET_EXCEEDED,
)
from app.constants.organizer import (
    ERROR_IMAGE_HOST_NOT_ALLOWED,
    ERROR_VENUE_NOT_FOUND,
)
from app.constants.ranking import (
    PREFERENCE_SIGNALS,
    PREFERRED_TASTE_MIN_WEIGHT,
)
from app.constants.promotions import PROMOTION_CONFLICT_ERROR_CODES
from app.constants.reports import (
    ERROR_INVALID_REPORT_REASON,
    REPORT_STATUS_OPEN,
    VALID_REPORT_REASONS,
)
from app.constants.security import (
    ORGANIZER_HTML_SANITIZE_ALLOWED_ATTRS,
    ORGANIZER_HTML_SANITIZE_ALLOWED_TAGS,
)
from app.auth.utils import mask_email
from app.events.queries import event_not_ended_filter
from app.events.localize import (
    resolve_description,
    resolve_important_info,
    resolve_title,
    resolve_why_go,
)
from app.events.venue import (
    resolve_venue_address,
    resolve_venue_coords,
    resolve_venue_name,
)
from app.ingestion.content_filters import content_flags, localized_text_values
from app.ingestion.http_client import own_cloudinary_url
from app.ingestion.pricing import normalize_currency
from app.ingestion.sanitize import sanitize_html
from app.promotions.grant import PromotionRefused
from app.models.models import (
    AdminAction,
    Event,
    EventClassification,
    EventReport,
    Organizer,
    OrganizerIdentity,
    User,
    UserEventFeedback,
    UserIdentity,
    Venue,
)

log = logging.getLogger(__name__)


class RequestLinkBody(BaseModel):
    """Shared magic-link request body — consumer (routers/auth.py) and
    organizer (routers/organizer_auth.py) tracks use the identical shape."""

    email: EmailStr
    locale: str | None = None


PriceField = Annotated[float, Field(ge=0, lt=PRICE_MAX_VALUE, allow_inf_nan=False)]
"""Every request-body price_* field. events.price_* are Numeric(10,2), so an
unbounded float (or JSON's Infinity) overflows into a DataError 500 — the same
bound ingest enforces through parse_bounded_price (OWASP audit M-6)."""


class VerifyTokenBody(BaseModel):
    """Shared /verify request body — the magic-link token moves from a query
    parameter to the body so it stops landing in server access logs (Cloudflare
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


def build_google_redirect_uri(callback_path: str) -> str:
    """Browser-facing Google OAuth callback URL — must match what's
    registered with Google and what the state cookie is scoped to. Shared by
    both auth tracks (auth.py's GOOGLE_CALLBACK_PUBLIC_PATH, organizer_auth.py's
    ORGANIZER_GOOGLE_CALLBACK_PUBLIC_PATH)."""
    return f"{settings.FRONTEND_URL}{callback_path}"


def set_oauth_state_cookie(
    response: Response, token: str, *, cookie_name: str, cookie_path: str
) -> None:
    """Set the PKCE state cookie for a Google OAuth start — shared by both
    auth tracks, each passing its own track-scoped cookie name/path."""
    response.set_cookie(
        key=cookie_name,
        value=token,
        max_age=oauth_state_ttl_seconds(),
        path=cookie_path,
        secure=SESSION_COOKIE_SECURE,
        httponly=SESSION_COOKIE_HTTPONLY,
        samesite=OAUTH_STATE_COOKIE_SAMESITE,
    )


def clear_oauth_state_cookie(
    response: Response, *, cookie_name: str, cookie_path: str
) -> None:
    """Expire the PKCE state cookie (single-use). Attributes must match
    set_oauth_state_cookie's for the browser to actually clear it."""
    response.delete_cookie(
        key=cookie_name,
        path=cookie_path,
        secure=SESSION_COOKIE_SECURE,
        httponly=SESSION_COOKIE_HTTPONLY,
        samesite=OAUTH_STATE_COOKIE_SAMESITE,
    )


def append_google_signin_result(url: str, track: str) -> str:
    """Tag a Google OAuth callback's success redirect with which auth track
    signed in, so the frontend can write that track's signed-in localStorage
    hint before the router's first render — a server-side redirect runs no
    app JS between cookie-set and the route guard, unlike the magic-link
    verify routes where the hint is set in-page. See
    frontend/src/lib/googleSignInLanding.ts."""
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{GOOGLE_SIGNIN_RESULT_QUERY_PARAM}={track}"


def build_oauth_error_redirect(
    error_code: str, *, login_path: str, cookie_name: str, cookie_path: str
) -> RedirectResponse:
    """Every Google OAuth callback failure path lands here: a 302 back to the
    track's login page carrying an error code, never a 500 — the state
    cookie (single-use) is cleared regardless of outcome."""
    response = RedirectResponse(
        f"{settings.FRONTEND_URL}{login_path}?{OAUTH_ERROR_QUERY_PARAM}={error_code}",
        status_code=status.HTTP_302_FOUND,
    )
    clear_oauth_state_cookie(response, cookie_name=cookie_name, cookie_path=cookie_path)
    return response


async def recent_unused_link_exists(
    db: AsyncSession,
    model: type[Any],
    fk_column: InstrumentedAttribute[Any],
    fk_value: int,
    ttl_seconds: int,
    *,
    extra_predicate: ColumnElement[bool] | None = None,
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

    ``extra_predicate`` narrows the match beyond the fk — e.g. Google
    sign-in's confirmation-link cooldown (organizer_auth.py) must only
    suppress a resend against another *pending-confirmation* link for the
    same sub, not against an unrelated plain sign-in link the organizer
    happens to have unused, which would silently skip sending the
    confirmation email while the caller still reports it as sent.
    """
    recent_cutoff = datetime.now(timezone.utc) + timedelta(
        seconds=ttl_seconds - MAGIC_LINK_RESEND_COOLDOWN_SECONDS
    )
    conditions = [
        fk_column == fk_value,
        model.used_at.is_(None),
        model.expires_at > recent_cutoff,
    ]
    if extra_predicate is not None:
        conditions.append(extra_predicate)
    already_sent = await db.scalar(select(model).where(*conditions).limit(1))
    return already_sent is not None


_RUNNING_ADMIN_JOBS: set[str] = set()


def acquire_admin_job_lock(key: str) -> None:
    """Single-flight guard for the expensive/destructive triggers (issue
    #160): pipeline/run, cleanup, full ingest, send_digests, classify. Raises
    409 if *key* is already running instead of letting a retry click start a
    second concurrent run. In-memory only — fine given this app's
    single-process topology (see CLAUDE.md "Architecture")."""
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
    task is streaming — issue #159); a direct `await coro` would let
    that cancellation propagate straight into the job and cut it off
    mid-write. Awaiting `queue.get()` instead means the generator's own
    cancellation never touches the task, so the job always runs to
    completion regardless of whether anyone is still listening."""
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    async def _runner() -> None:
        try:
            result = await coro
            log_admin_action(None, action, target, result)()
            await queue.put(ndjson_line(stage, "ok", result, None))
        except HTTPException as exc:
            detail = str(exc.detail)
            log_admin_action(None, action, target, {"error": detail})()
            await queue.put(ndjson_line(stage, "error", None, detail))
        except Exception:
            log.exception("admin %s failed", name)
            detail = ERROR_ADMIN_JOB_FAILED.format(name=name)
            log_admin_action(None, action, target, {"error": detail})()
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


def log_admin_action(
    db: AsyncSession | None, action: str, target: int | str, result: dict
) -> Callable[[], None]:
    """Adds a durable AdminAction row to *db* (when given) and returns a
    zero-arg closure that emits the structured Axiom log line — the caller
    must invoke that closure only after its own `await db.commit()`
    succeeds, so the Axiom line never claims a mutation that a rolled-back
    transaction actually discarded. The row rides the caller's own open
    transaction (added, not committed here) so it lands atomically with the
    mutation it records, and survives an outage of the LOG_SHIP_URL log
    drain. Call from inside the same `_run()` closure as the mutation, pass
    *db* (and call the returned closure right after `await db.commit()`)
    for the takedown/retract/approve/resolve/pipeline-run actions the
    report feature's legal obligations bear on (see the admin-console
    spec's Audit logging section) — pass None for every other admin job
    (no transaction to ride), which keeps the pre-existing log-only
    behavior; those callers may invoke the closure immediately."""

    def _emit() -> None:
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

    if db is not None:
        db.add(AdminAction(action=action, target=str(target), result=result))
    return _emit








async def is_identity_linked(
    db: AsyncSession,
    identity_model: type[UserIdentity] | type[OrganizerIdentity],
    owner_col: InstrumentedAttribute,
    owner_id: int,
) -> bool:
    """True if ``owner_id`` has a linked Google identity row.

    Shared by settings.py (UserIdentity, UserIdentity.user_id) and
    organizer_profile.py (OrganizerIdentity, OrganizerIdentity.organizer_id) —
    both tracks' google_linked flag is otherwise the same query against a
    different identity table/owner column.
    """
    result = await db.execute(
        select(identity_model.id).where(
            owner_col == owner_id,
            identity_model.provider == IDENTITY_PROVIDER_GOOGLE,
        )
    )
    return result.scalars().first() is not None


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






def resolve_locale_param(locale: str | None, fallback: str) -> str:
    """Validate an optional ?locale= param, falling back when absent/invalid."""
    return locale if locale in VALID_LOCALES else fallback








async def replace_organizer_categories(
    db: AsyncSession, event_id: int, categories: list[str]
) -> None:
    """Set an event's classification categories to exactly the organizer's picks.

    Used for an organizer's own submissions (create + edit): their set is
    authoritative, so LLM-derived categories are dropped rather than merged —
    keeping them would inflate persona affinity, which sums weights over every
    category (`_affinity_for_vector`). If no classification row exists yet
    (e.g. classify_event's LLM call failed), a bare one is created so the pick
    isn't silently dropped."""
    classification = await db.scalar(
        select(EventClassification).where(EventClassification.event_id == event_id)
    )
    if classification is None:
        db.add(EventClassification(event_id=event_id, categories=categories))
        return
    classification.categories = categories


async def prepend_organizer_categories(
    db: AsyncSession,
    event_id: int,
    categories: list[str],
    max_total: int | None = None,
) -> None:
    """Prepend organizer-chosen categories onto an event's classification.

    Used by claim edits (#416's prepend-only rule): the claimed event's
    existing categories are never removed. The picks lead the list in the
    order given (those already present are skipped), existing categories
    follow; a bare classification row is created if none exists yet.

    `max_total` caps the resulting list: if adding the genuinely new picks
    would exceed it, 422 and nothing is changed. Existing categories are
    never trimmed, so an event already over the cap simply can't gain more."""
    classification = await db.scalar(
        select(EventClassification).where(EventClassification.event_id == event_id)
    )
    existing = classification.categories if classification is not None else []
    new = [c for c in categories if c not in existing]
    if max_total is not None and new and len(existing) + len(new) > max_total:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_CLAIM_EDIT_CATEGORIES_CAP,
        )
    if classification is None:
        db.add(EventClassification(event_id=event_id, categories=categories))
        return
    if new:
        classification.categories = [*new, *existing]




def serialize_event(
    event: Event,
    locale: str = DEFAULT_USER_LOCALE,
    feedback_by_event: dict[int, str] | None = None,
    reported_event_ids: set[int] | None = None,
) -> dict:
    # Shared by every listing surface (feed/explore/saved) as well as the
    # single-event page — never add claim_status/listed_by here. Both are
    # public-event-page-only (ranking-neutrality boundary, #419) and are
    # bolted onto this dict's return value solely in routers/events.py.
    cl = event.classification
    why_go = resolve_why_go(cl, locale)
    lat, lng = resolve_venue_coords(event)
    return {
        "id": event.id,
        "slug": event.slug,
        "title": resolve_title(event, locale),
        "description": resolve_description(event, locale),
        "important_info": resolve_important_info(event, locale),
        "starts_at": event.starts_at.isoformat(),
        "ends_at": event.ends_at.isoformat() if event.ends_at else None,
        "venue_name": resolve_venue_name(event, locale),
        "venue_address": resolve_venue_address(event),
        "lat": lat,
        "lng": lng,
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




def validate_tz_aware(v: datetime | None) -> datetime | None:
    """Shared by organizer_events.py's SubmitEventBody/PatchEventBody
    starts_at/ends_at validators."""
    if v is not None and v.tzinfo is None:
        raise ValueError("must be timezone-aware")
    return v


def validate_categories(v: list[str] | None) -> list[str] | None:
    """Shared by organizer_events.py's SubmitEventBody/PatchEventBody and
    organizer_claim_edits.py's ClaimEditBody `categories` validators. Dedupes
    (order kept) before applying the ORGANIZER_MAX_CATEGORIES cap."""
    if v is None:
        return None
    for c in v:
        if c not in VALID_CATEGORIES:
            raise ValueError(f"invalid category: {c!r}")
    deduped = list(dict.fromkeys(v))
    if len(deduped) > ORGANIZER_MAX_CATEGORIES:
        raise ValueError(f"at most {ORGANIZER_MAX_CATEGORIES} categories")
    return deduped


def fold_legacy_category(data: Any) -> Any:
    """`mode="before"` model-validator body: fold the deprecated single
    `category` key into `categories`. Frontend (Cloudflare) and backend
    (Render) deploy separately, so an old frontend may still send `category`;
    without this it would be silently dropped as an unknown field. An explicit
    `categories` wins. Remove in a follow-up once no old frontend is live."""
    if isinstance(data, dict) and "category" in data:
        data = dict(data)
        legacy = data.pop("category")
        if "categories" not in data and legacy is not None:
            data["categories"] = [legacy]
    return data


def validate_price_ordering(
    price_min: float | None, price_max: float | None
) -> None:
    """Shared by organizer_events.py's SubmitEventBody/PatchEventBody and
    organizer_venues.py's VenueBody/VenuePatchBody `price_min > price_max`
    ordering check."""
    if price_min is not None and price_max is not None and price_min > price_max:
        raise ValueError("price_min must not be greater than price_max")


def validate_time_ordering(starts_at: datetime | None, ends_at: datetime | None) -> None:
    """Shared by organizer_events.py's SubmitEventBody/PatchEventBody and
    organizer_claim_edits.py's PatchClaimEventBody `ends_at < starts_at`
    ordering check. Both-present only — a patch touching just one of the pair
    can't be checked against the other without a DB round-trip."""
    if starts_at is not None and ends_at is not None and ends_at < starts_at:
        raise ValueError("ends_at must not be before starts_at")


def organizer_sanitize(text: str | None) -> str | None:
    """sanitize_html at the organizer-submission boundary (#267) — the
    narrower Tiptap-tracking allowlist, not the shared ingestion one. Shared
    by organizer_events.py and organizer_claim_edits.py."""
    return sanitize_html(
        text,
        tags=ORGANIZER_HTML_SANITIZE_ALLOWED_TAGS,
        attrs=ORGANIZER_HTML_SANITIZE_ALLOWED_ATTRS,
    )


def localized_dict(
    et: str | None, en: str | None, ru: str | None
) -> dict[str, str] | None:
    """Build a {locale: value} JSONB dict from locale-suffixed request fields,
    dropping absent locales. et is required upstream (see title validation)."""
    out = {
        loc: val
        for loc, val in ((LOCALE_ET, et), (LOCALE_EN, en), (LOCALE_RU, ru))
        if val is not None and val.strip()
    }
    return out or None


def merged_localized(
    existing: dict[str, str] | None,
    orig: str | None,
    body: BaseModel,
    fields_set: set[str],
    base: str,
    *,
    sanitize: Callable[[str | None], str | None] | None = None,
) -> dict[str, str] | None:
    """Rebuild a ``*_localized`` column for a PATCH: a locale present in
    ``fields_set`` (``{base}_en`` / ``{base}_ru`` on ``body``) takes the
    request value (optionally passed through ``sanitize``); an absent one
    keeps its ``existing`` value. ``orig`` is the et/original text."""
    existing = existing or {}
    values = []
    for loc in (LOCALE_EN, LOCALE_RU):
        field = f"{base}_{loc}"
        if field in fields_set:
            value = getattr(body, field)
            values.append(sanitize(value) if sanitize is not None else value)
        else:
            values.append(existing.get(loc))
    return localized_dict(orig, *values)


def apply_price_edit(event: Event, body: Any, fields_set: set[str]) -> None:
    """Apply a PATCH's price_min/price_max/currency to ``event`` and
    re-normalize ``currency``: coerces a raw value and fills the default only
    when the event now carries a price, so a price-only PATCH doesn't leave
    currency NULL and an un-coerced value never lands on the String(3)
    column. Shared by organizer_events.py and organizer_claim_edits.py."""
    if "price_min" in fields_set:
        event.price_min = body.price_min
    if "price_max" in fields_set:
        event.price_max = body.price_max
    has_price = event.price_min is not None or event.price_max is not None
    raw_currency = body.currency if "currency" in fields_set else event.currency
    event.currency = normalize_currency(raw_currency, has_price)


def apply_moderation_flags(
    event: Event, venue_name: str | None, *extra_explicit_texts: str | None
) -> bool:
    """Recheck an organizer-edited event against the explicit/non-event
    keyword filters and set the flags. ``venue_name`` must be the resolved
    venue name (never the raw column, NULL for a venue-linked event); extra
    texts (e.g. ``important_info``) join the explicit scan. Returns True when
    either flag was newly set, so the caller can pull a published event back
    to classified."""
    # Every user-visible text, not just the Estonian originals: EN/RU readers
    # and the digest are served the *_localized values (OWASP audit M-5).
    extras = [
        *(t for t in extra_explicit_texts if t),
        event.important_info,
        *localized_text_values(
            event.title_localized,
            event.description_localized,
            event.important_info_localized,
        ),
    ]
    is_explicit, is_non_event = content_flags(
        event.title_orig, event.description_orig, venue_name, None, extras
    )
    flagged = False
    if is_explicit and not event.is_explicit:
        event.is_explicit = True
        flagged = True
    if is_non_event and not event.is_non_event:
        event.is_non_event = True
        flagged = True
    return flagged


async def remoderate_venue_linked_events(db: AsyncSession, venue: Venue) -> None:
    """A saved venue's name/address is resolved onto every event linked to it
    at read time (``resolve_venue_name()``), so renaming the venue changes the
    text shown on already-published events without passing the submit path's
    explicit/non-event checks (OWASP audit #5). Rescan every live linked event
    against the venue's new names, pull a newly flagged published event back to
    classified, and queue them all for post-hoc admin review like any other
    organizer edit. One query regardless of how many events link the venue.
    The caller commits."""
    events = (
        await db.scalars(
            select(Event).where(
                Event.venue_id == venue.id,
                Event.status != EVENT_STATUS_CANCELLED,
                event_not_ended_filter(datetime.now(TALLINN_TZ)),
            )
        )
    ).all()
    for event in events:
        event.needs_review = True
        if (
            apply_moderation_flags(
                event, venue.name, venue.name_en, venue.name_ru, event.important_info
            )
            and event.status == EVENT_STATUS_PUBLISHED
        ):
            event.status = EVENT_STATUS_CLASSIFIED


def validate_report_reason(reason: str) -> None:
    """Shared by POST /reports and GET /admin/reports's ``reason`` filter —
    a single source of truth for the taxonomy check and its error message."""
    if reason not in VALID_REPORT_REASONS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=ERROR_INVALID_REPORT_REASON.format(reasons=sorted(VALID_REPORT_REASONS)),
        )


async def own_venue_or_404(db: AsyncSession, venue_id: int, organizer_id: int) -> Venue:
    """Shared by organizer_events.py and organizer_venues.py — 404-not-403
    ownership check for a saved Venue, mirroring organizer_events.py's own
    ``_own_event_or_404`` convention."""
    venue = await db.scalar(
        select(Venue).where(
            Venue.id == venue_id,
            Venue.organizer_id == organizer_id,
            Venue.deleted_at.is_(None),
        )
    )
    if venue is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=ERROR_VENUE_NOT_FOUND
        )
    return venue


# {"YYYY-MM-DD": count} — in-memory, single-process, like the admin lockout
# dict (routers/admin.py) — resets on deploy/restart, which just means one
# lost day of budget tracking, not a security regression.
_unverified_account_creation_counts: dict[str, int] = {}
_unverified_account_budget_alerted: set[str] = set()


async def get_or_create_organizer(
    db: AsyncSession, email: str, requested_locale: str | None
) -> Organizer:
    """Look up (or insert) the organizer for a magic-link request — shared by
    organizer_auth.py's own sign-in link and organizer_claims.py's claim-
    intent link (#413), which both need the identical unverified-row-creation
    trade-off (mitigated by RATE_LIMIT_AUTH_REQUEST_LINK + recent_unused_link_exists).
    Mirrors auth.py::_get_or_create_user."""
    organizer = await db.scalar(select(Organizer).where(Organizer.email == email))
    if organizer is None:
        organizer = Organizer(email=email, locale=requested_locale or DEFAULT_USER_LOCALE)
        db.add(organizer)
        await db.flush()
        log.info(
            "organizer auth: new unverified organizer row created email=%s",
            mask_email(email),
        )
        record_unverified_account_creation()
    return organizer


def record_unverified_account_creation() -> None:
    """Bump the global (not per-IP) daily count of new unverified User/
    Organizer rows created via the magic-link request endpoints
    (auth.py::_get_or_create_user, organizer_auth.py::_get_or_create_organizer).

    The per-email cooldown (RATE_LIMIT_AUTH_REQUEST_LINK) only throttles
    repeats to the *same* address; a burst of distinct first-contact
    addresses can still mail-bomb via this service's Resend domain. Rather
    than hard-blocking new signups (which would turn away real users during
    a legitimate burst), this logs one distinct, greppable warning the first
    time UNVERIFIED_ACCOUNT_DAILY_BUDGET is crossed for the day — an early
    signal an operator can alert on ahead of Resend's own sender-reputation/
    quota controls tripping (OWASP audit F10).
    """
    today = datetime.now(TALLINN_TZ).date().isoformat()
    count = _unverified_account_creation_counts.get(today, 0) + 1
    _unverified_account_creation_counts[today] = count
    if (
        count >= UNVERIFIED_ACCOUNT_DAILY_BUDGET
        and today not in _unverified_account_budget_alerted
    ):
        _unverified_account_budget_alerted.add(today)
        log.warning(
            "auth: unverified-account creation budget exceeded (%d today)",
            count,
            extra={"event": LOG_EVENT_UNVERIFIED_ACCOUNT_BUDGET_EXCEEDED},
        )
    # Bound growth: only today's entry is ever needed going forward — a
    # process left running for weeks would otherwise accumulate one stale
    # key per day forever.
    for stale_day in [d for d in _unverified_account_creation_counts if d != today]:
        del _unverified_account_creation_counts[stale_day]
        _unverified_account_budget_alerted.discard(stale_day)


def claim_dns_record_name(mechanism: str | None, domain: str | None) -> str | None:
    """The TXT record name a DNS-TXT/Piletilevi-promoter claim's organizer is
    told to add (#412/#413) — shared by the organizer-facing pending screen
    (organizer_claims.py) and the admin claims queue (admin.py, #420) so the
    two never disagree on the record name shown for the same claim."""
    if mechanism in CLAIM_DNS_VERIFICATION_MECHANISMS and domain:
        return f"{CLAIM_DNS_TXT_RECORD_LABEL}.{domain}"
    return None


def check_image_host(image_url: str | None) -> str | None:
    """Reject an organizer-submission or claim-edit image_url that isn't one of OUR signed
    Cloudinary uploads (``own_cloudinary_url``) and return its re-serialized
    form (None for empty). Parser-differential spellings (``\\``, userinfo,
    ports) are refused up front by ``safe_render_url`` and the stored value is
    its re-serialized form (OWASP audit M-1)."""
    if not image_url:
        return None
    safe = own_cloudinary_url(image_url)
    if safe is not None:
        return safe
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ERROR_IMAGE_HOST_NOT_ALLOWED,
    )


def promotion_refusal(refused: PromotionRefused) -> HTTPException:
    """409 when the state of things forbids the command, 429 for the daily
    request ceiling, 422 for bad input; `detail.errors` lists every rule
    broken."""
    codes = [v.code for v in refused.violations]
    if any(c in PROMOTION_CONFLICT_ERROR_CODES for c in codes):
        code = status.HTTP_409_CONFLICT
    elif PROMOTION_ERROR_REQUEST_DAILY_LIMIT in codes:
        code = status.HTTP_429_TOO_MANY_REQUESTS
    else:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
    return HTTPException(
        status_code=code,
        detail={
            "code": refused.violations[0].code,
            "message": refused.violations[0].message,
            "errors": [v.as_dict() for v in refused.violations],
        },
    )
