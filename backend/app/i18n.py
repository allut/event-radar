"""Backend localization.

Mirrors ``frontend/src/i18n.ts``: a single ``TRANSLATIONS[locale][key]`` table
and ``t()`` / ``ti()`` helpers with ``locale → en → key`` fallback. Domain
strings (email subjects, digest labels, day/month names) live in
``shared/i18n/*.json`` as the single source of truth.

For per-event ``why_go`` bullets (read from DB JSONB), use
``app.routers.utils.resolve_why_go`` — that lookup is not static text.
"""

from __future__ import annotations

from app._generated.i18n_data import DAY_NAMES, MONTH_NAMES, TRANSLATIONS
from app._generated.shared_constants import DEFAULT_USER_LOCALE, VALID_LOCALES

__all__ = ["TRANSLATIONS", "DAY_NAMES", "MONTH_NAMES", "t", "ti", "day_name", "month_name"]


def resolve_locale(locale: str) -> str:
    """``locale`` if supported, else ``DEFAULT_USER_LOCALE`` — the locale an
    email is actually rendered in (also used by app/email/links.py)."""
    return locale if locale in VALID_LOCALES else DEFAULT_USER_LOCALE


def t(key: str, locale: str) -> str:
    """Return the string for ``key`` in ``locale``, falling back to en, then the key itself.

    Uses explicit ``is not None`` so an empty-string override (``""``) is honored
    instead of being treated as a miss.
    """
    loc = resolve_locale(locale)
    val = TRANSLATIONS[loc].get(key)
    if val is not None:
        return val
    val = TRANSLATIONS[DEFAULT_USER_LOCALE].get(key)
    if val is not None:
        return val
    return key


def ti(key: str, locale: str, **vars: object) -> str:
    """``t()`` + ``{name}`` placeholder substitution (str-formatted via ``.format``)."""
    return t(key, locale).format(**vars)


def day_name(weekday: int, locale: str) -> str:
    """``weekday`` follows ``date.weekday()`` (0=Mon..6=Sun)."""
    return DAY_NAMES[resolve_locale(locale)][weekday]


def month_name(month: int, locale: str) -> str:
    """``month`` is the 1-indexed calendar month (1=Jan..12=Dec)."""
    return MONTH_NAMES[resolve_locale(locale)][month]
