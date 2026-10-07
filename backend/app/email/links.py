"""Locale-prefixed frontend links for outbound email (#499).

The pages an email link opens (AuthVerify, OrganizerVerify, Unsubscribe, …)
take their language from the URL alone — the `/en`/`/ru` prefix, else
Estonian — so every link must carry the locale the email was rendered in.
Backend counterpart of ``localizedPath`` in frontend/src/lib/urlLocale.ts.
"""

from app.config import settings
from app.constants import HOME_PATH, LOCALE_URL_PREFIX_CODES
from app.i18n import resolve_locale


def localized_path(path: str, locale: str) -> str:
    """Bare frontend ``path`` for ``locale``: Estonian stays bare, en/ru get a
    ``/en``/``/ru`` prefix. An unsupported locale resolves the way ``t()``
    does (to ``DEFAULT_USER_LOCALE``), so the link matches the language the
    email body rendered in. ``path`` must be a bare, locale-free route path —
    append any query string afterwards."""
    loc = resolve_locale(locale)
    if loc not in LOCALE_URL_PREFIX_CODES:
        return path
    return f"/{loc}" if path == HOME_PATH else f"/{loc}{path}"


def frontend_url(path: str, locale: str, base: str | None = None) -> str:
    """Absolute link to ``path`` in ``locale``, on ``base`` (defaults to
    ``settings.FRONTEND_URL``)."""
    return f"{base or settings.FRONTEND_URL}{localized_path(path, locale)}"
