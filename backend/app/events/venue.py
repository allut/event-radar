"""Venue resolution for events: a venue-linked event leaves ``venue_name``/
``venue_address``/lat/lng NULL (#176), so every reader resolves them through
these helpers instead of reading the columns."""

from app.constants import DEFAULT_USER_LOCALE, LOCALE_EN, LOCALE_RU
from app.models.models import Event, Venue


def _linked_venue(event: Event) -> Venue | None:
    """Return the joined Venue when the event is venue-linked, else None."""
    return event.venue if event.venue_id is not None else None


def _pick_locale(locale: str, base: str | None, en: str | None, ru: str | None) -> str | None:
    """Per-locale value with fallback to the base (Estonian) value."""
    if locale == LOCALE_EN:
        return en or base
    if locale == LOCALE_RU:
        return ru or base
    return base


def resolve_venue_name(event: Event, locale: str = DEFAULT_USER_LOCALE) -> str | None:
    """Prefer the linked Venue's per-locale name over Event.venue_name.

    venue_name/venue_address are left NULL at write time whenever venue_id
    is set (#176) — the join is the sole venue source going forward. Falls
    back to the legacy free-typed column when venue_id is None."""
    venue = _linked_venue(event)
    if venue is not None:
        return _pick_locale(locale, venue.name, venue.name_en, venue.name_ru)
    return event.venue_name


def resolve_venue_address(event: Event) -> str | None:
    """Prefer the linked Venue's address over Event.venue_address. Address
    is not localized (street names don't translate) — see resolve_venue_name
    for the venue_id/write-time-NULL rationale."""
    venue = _linked_venue(event)
    if venue is not None:
        return venue.address
    return event.venue_address


def resolve_venue_coords(event: Event) -> tuple[float | None, float | None]:
    """Prefer the linked Venue's own geocode over Event.lat/lng.

    A venue-linked event's own lat/lng never gets backfilled by the
    geocoding job (its partial index keys off venue_address IS NOT NULL,
    which is NULL for a linked event) — the Venue's own geocode cooldown
    (docs/data-model.md) is the only source of coordinates once linked.
    Requires both lat AND lng to be present before preferring the venue's
    pair — a half-geocoded venue (one of the two still NULL) falls back to
    the event's own (possibly also-NULL, but never mismatched) pair rather
    than surfacing a broken half-populated coordinate."""
    venue = _linked_venue(event)
    if venue is not None and venue.lat is not None and venue.lng is not None:
        return venue.lat, venue.lng
    return event.lat, event.lng
