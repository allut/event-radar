"""Backend localization.

Mirrors ``frontend/src/i18n.ts``: a single ``TRANSLATIONS[locale][key]`` table
and ``t()`` / ``ti()`` helpers with ``locale → en → key`` fallback. Domain
strings (email subjects, digest labels, day/month names) live here as the
single source of truth for backend-rendered text.

For per-event ``why_go`` bullets (read from DB JSONB), use
``app.routers.utils.resolve_why_go`` — that lookup is not static text.
"""
from __future__ import annotations

from app.constants import DEFAULT_USER_LOCALE, VALID_LOCALES


# ---------------------------------------------------------------------------
# Flat string translations
# ---------------------------------------------------------------------------

TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        # ── Magic-link email ────────────────────────────────────────────
        "email.magic_link.subject": "Your Event Radar sign-in link",
        "email.magic_link.body": (
            "<p>Click the link below to sign in to Event Radar. "
            "This link expires in {ttl_minutes} minutes.</p>"
            '<p><a href="{verify_url}">Sign in to Event Radar</a></p>'
            "<p>If you didn't request this, ignore this email.</p>"
        ),
        # ── Daily 5 digest email ────────────────────────────────────────
        "digest.subject_template": "Your Daily 5 — {date}",
        "digest.subject_label": "Your Daily 5",
        "digest.price_free": "Free",
        "digest.price_from": "From €{amount}",
        "digest.unsubscribe": "Unsubscribe",
        "digest.no_events": "No events today.",
    },
    "et": {
        "email.magic_link.subject": "Sinu Event Radar sisselogimislink",
        "email.magic_link.body": (
            "<p>Klõpsa alloleval lingil Event Radarisse sisselogimiseks. "
            "Link aegub {ttl_minutes} minuti pärast.</p>"
            '<p><a href="{verify_url}">Logi sisse Event Radarisse</a></p>'
            "<p>Kui sa seda ei palunud, ignoreeri seda kirja.</p>"
        ),
        "digest.subject_template": "Sinu Päevane Viisik — {date}",
        "digest.subject_label": "Sinu Päevane Viisik",
        "digest.price_free": "Tasuta",
        "digest.price_from": "Alates €{amount}",
        "digest.unsubscribe": "Tühista tellimus",
        "digest.no_events": "Täna pole üritusi.",
    },
    "ru": {
        "email.magic_link.subject": "Ваша ссылка для входа в Event Radar",
        "email.magic_link.body": (
            "<p>Нажмите на ссылку ниже, чтобы войти в Event Radar. "
            "Ссылка действительна {ttl_minutes} минут.</p>"
            '<p><a href="{verify_url}">Войти в Event Radar</a></p>'
            "<p>Если вы не запрашивали это, проигнорируйте письмо.</p>"
        ),
        "digest.subject_template": "Ваша Пятёрка дня — {date}",
        "digest.subject_label": "Ваша Пятёрка дня",
        "digest.price_free": "Бесплатно",
        "digest.price_from": "От €{amount}",
        "digest.unsubscribe": "Отписаться",
        "digest.no_events": "Сегодня нет событий.",
    },
}


# ---------------------------------------------------------------------------
# Date name tables (indexed lookups, not key→string)
# ---------------------------------------------------------------------------

# MONTH_NAMES use a leading "" so index == calendar month (1..12).
MONTH_NAMES: dict[str, list[str]] = {
    "en": ["", "January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"],
    "et": ["", "jaanuar", "veebruar", "märts", "aprill", "mai", "juuni",
           "juuli", "august", "september", "oktoober", "november", "detsember"],
    "ru": ["", "января", "февраля", "марта", "апреля", "мая", "июня",
           "июля", "августа", "сентября", "октября", "ноября", "декабря"],
}

# DAY_NAMES indexed 0..6 with 0 = Monday (matches date.weekday()).
DAY_NAMES: dict[str, list[str]] = {
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "et": ["esmaspäev", "teisipäev", "kolmapäev", "neljapäev", "reede", "laupäev", "pühapäev"],
    "ru": ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"],
}


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------


def _resolve_locale(locale: str) -> str:
    return locale if locale in VALID_LOCALES else DEFAULT_USER_LOCALE


def t(key: str, locale: str) -> str:
    """Return the string for ``key`` in ``locale``, falling back to en, then the key itself.

    Uses explicit ``is not None`` so an empty-string override (``""``) is honored
    instead of being treated as a miss.
    """
    loc = _resolve_locale(locale)
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
    return DAY_NAMES[_resolve_locale(locale)][weekday]


def month_name(month: int, locale: str) -> str:
    """``month`` is the 1-indexed calendar month (1=Jan..12=Dec)."""
    return MONTH_NAMES[_resolve_locale(locale)][month]
