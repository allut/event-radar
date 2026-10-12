"""Localized-text resolvers for events: locale -> en -> original fallback."""

from app._generated.shared_constants import DEFAULT_USER_LOCALE
from app.models.models import Event, EventClassification


# FAQ #languages describes this behaviour — update the copy (all locales) if it changes
def resolve_title(event: Event, locale: str) -> str:
    """Return localized title with locale → en → title_orig fallback."""
    loc = event.title_localized
    if loc:
        result = loc.get(locale) or loc.get(DEFAULT_USER_LOCALE)
        if result:
            return result
    return event.title_orig


# FAQ #languages describes this behaviour — update the copy (all locales) if it changes
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
