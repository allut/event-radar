"""Cross-cutting constants: timezone, time units, locales, slugs, frontend paths, generic SQL/regex helpers."""

from zoneinfo import ZoneInfo

from app._generated.shared_constants import VALID_LOCALES

TALLINN_TZ_NAME = "Europe/Tallinn"
TALLINN_TZ = ZoneInfo(TALLINN_TZ_NAME)

# Application environment — value of settings.APP_ENV that enables dev-only
# behaviour (unprotected admin endpoints, SQL echo).
# NB: app.config imports this module for the APP_ENV default, so app.constants must
# never import app.config — doing so would create a circular import.
APP_ENV_DEVELOPMENT = "development"

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400
MS_PER_SECOND = 1000

SLUG_TITLE_MAX_LEN = 60
# Stand-in title part when transliteration leaves nothing (e.g. a title of
# only symbols), so a slug never starts with "-".
SLUG_EMPTY_TITLE_FALLBACK = "event"
SLUG_HASH_HEX_LEN = 8

# BeautifulSoup's built-in parser name — used everywhere we parse scraped/stored HTML.
HTML_PARSER = "html.parser"

# Frontend redirect targets for the callback (no JSON response — this is a
# top-level browser navigation back from Google).
ORGANIZER_LOGIN_PATH = "/organizer/login"
ORGANIZER_DASHBOARD_PATH = "/organizer/dashboard"
LOGIN_PATH = "/login"
HOME_PATH = "/"
ONBOARDING_PATH = "/onboarding"
# Frontend paths linked from transactional emails (app/email/report_notify.py,
# report_reporter.py, digest.py) — built with settings.FRONTEND_URL as a prefix,
# plus the recipient's locale prefix (app/email/links.py) for the
# user-facing ones.
EVENTS_PATH = "/events"
SETTINGS_PATH = "/settings"
ADMIN_REPORTS_PATH = "/admin/reports"
UNSUBSCRIBE_PATH = "/unsubscribe"
ADS_OFF_PATH = "/email-consent-off"

# Named locale codes for the fixed et/en/ru vocabulary (VALID_LOCALES above) —
# used where code refers to one specific locale rather than iterating the set.
LOCALE_ET = "et"
# Locales whose frontend URLs carry a `/en`/`/ru` path prefix — Estonian is the
# bare (unprefixed) URL locale. Backend mirror of the frontend's
# LOCALE_URL_PREFIX_CODES (frontend/src/constants/core.ts); used by
# app/email/links.py to point email links at the recipient's locale (#499).
LOCALE_URL_PREFIX_CODES: frozenset[str] = frozenset(VALID_LOCALES) - {LOCALE_ET}

# Max values per ``IN (...)`` list: SQLAlchemy expands one bind param per value,
# and Postgres caps a statement at ~32k params.
SQL_IN_CHUNK_SIZE = 1000

# Largest Postgres BIGINT (signed 64-bit). Upper bound for an id query param,
# so an out-of-range id is a 422 instead of an overflowing bind (a 500).
SQL_BIGINT_MAX = 2**63 - 1

# app/ingestion/adapter.py::_make_slug — collapses any non a-z0-9 run to "-".
SLUG_SANITIZE_RE = r"[^a-z0-9]+"

# app/ingestion/adapter.py::_make_slug — lowercase Russian Cyrillic -> Latin,
# applied after NFKD marks are dropped. Soft/hard signs map to "".
SLUG_CYRILLIC_TO_LATIN = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}  # fmt: skip

# routers/settings.py
ERROR_NO_UPDATE_FIELDS = "Provide at least one field to update."

MAILTO_PREFIX = "mailto:"

SLUG_DATE_FORMAT = "%Y%m%d"

# Postgres regex fragments for the suspect-venue-name SQL twin
SQL_REGEX_DIGIT = r"[0-9]"
SQL_REGEX_WORD_BOUNDARY = r"\y"
