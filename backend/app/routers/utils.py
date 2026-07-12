"""Shared serialization helpers for event routers."""

import logging
import re
from collections.abc import Awaitable
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from itsdangerous import BadSignature, SignatureExpired
from sqlalchemy import ColumnElement, Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.tokens import verify_session_token
from app.constants import (
    APP_ENV_DEVELOPMENT,
    DEFAULT_USER_LOCALE,
    EMAIL_MASK_VISIBLE_CHARS,
    EVENT_STATUS_PUBLISHED,
    PREFERRED_TASTE_MIN_WEIGHT,
)
from app.models.models import Event, User

log = logging.getLogger(__name__)


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
            detail=f"{name} failed; see server logs",
        )


def require_configured_secret(
    secret: str | None, *, feature: str, setting_name: str, app_env: str
) -> bool:
    """Fail-closed gate shared by every secret-protected surface (admin auth,
    inbound webhook, /internal/tick).

    Returns True when the secret is configured — the caller must then verify
    it. When unset: 503 outside development; in development, log a warning and
    return False (caller skips verification). Callers pass their own module's
    ``settings`` values so tests that patch the caller's settings keep working.
    """
    if secret:
        return True
    if app_env != APP_ENV_DEVELOPMENT:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{feature} disabled: {setting_name} not configured",
        )
    log.warning(
        "%s not set; %s unprotected (development mode)", setting_name, feature
    )
    return False


def mask_db_url(url: str) -> str:
    """Redact the password in a DB URL for safe logging (``user:pass@host`` ->
    ``user:***@host``). Shared by the maintenance scripts in ``backend/scripts``."""
    return re.sub(r":[^@/]+@", ":***@", url)


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


def parse_bearer_user(authorization: str | None) -> tuple[int, int] | None:
    """(user_id, token_version) from an ``Authorization: Bearer`` header, or
    None when the header is missing/malformed or the token is expired/invalid."""
    if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
        return None
    try:
        return verify_session_token(authorization[len("Bearer ") :])
    except (SignatureExpired, BadSignature):
        return None


async def get_optional_user_locale(
    authorization: str | None,
    db: AsyncSession,
) -> str:
    """Resolve user locale from a Bearer token if present; else DEFAULT_USER_LOCALE."""
    parsed = parse_bearer_user(authorization)
    if parsed is None:
        return DEFAULT_USER_LOCALE
    user = await db.get(User, parsed[0])
    return user.locale if user else DEFAULT_USER_LOCALE


def select_events_with_classification() -> Select[tuple[Event]]:
    """Base SELECT for Event with classification eager-loaded. Callers add their own .where()."""
    return select(Event).options(selectinload(Event.classification))


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


def resolve_why_go(cl, locale: str) -> list[str]:
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


def serialize_event(event: Event, locale: str = DEFAULT_USER_LOCALE) -> dict:
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
    }
