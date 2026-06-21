"""Shared serialization helpers for event routers."""

from itsdangerous import BadSignature, SignatureExpired
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth.tokens import verify_session_token
from app.constants import DEFAULT_USER_LOCALE, EMAIL_MASK_VISIBLE_CHARS
from app.models.models import Event, User


def mask_email(email: str) -> str:
    """Mask an email for log output — keep the first few local-part characters and
    the full domain so entries stay correlatable without persisting raw PII in
    cleartext logs (e.g. 'aleksei.lutkov@gmail.com' -> 'al***@gmail.com')."""
    local, sep, domain = email.partition("@")
    if not sep:
        return "***"
    return f"{local[:EMAIL_MASK_VISIBLE_CHARS]}***@{domain}"


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


async def get_optional_user_locale(
    authorization: str | None,
    db: AsyncSession,
) -> str:
    """Resolve user locale from a Bearer token if present; else DEFAULT_USER_LOCALE."""
    if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
        return DEFAULT_USER_LOCALE
    try:
        user_id, _version = verify_session_token(authorization[len("Bearer ") :])
    except (SignatureExpired, BadSignature):
        return DEFAULT_USER_LOCALE
    user = await db.get(User, user_id)
    return user.locale if user else DEFAULT_USER_LOCALE


def select_events_with_classification() -> Select[tuple[Event]]:
    """Base SELECT for Event with classification eager-loaded. Callers add their own .where()."""
    return select(Event).options(selectinload(Event.classification))


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
        "title": event.title_orig,
        "description": event.description_orig,
        "important_info": event.important_info,
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
        "categories": cl.categories if cl else [],
        "vibes": cl.vibes if cl else [],
        "why_go": why_go,
        "quality_score": cl.quality_score if cl else None,
        "language": cl.language_detected if cl else None,
    }
