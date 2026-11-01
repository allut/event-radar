"""Event and user response serializers, plus the per-user signal loaders behind them."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app._generated.shared_constants import (
    DEFAULT_USER_LOCALE,
    VALID_LOCALES,
)
from app.constants.ranking import (
    PREFERENCE_SIGNALS,
    PREFERRED_TASTE_MIN_WEIGHT,
)
from app.constants.reports import (
    REPORT_STATUS_OPEN,
)
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
from app.models.events import Event, EventReport
from app.models.feeds import UserEventFeedback
from app.models.users import User

log = logging.getLogger(__name__)


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
