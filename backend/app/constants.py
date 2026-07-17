import http
from typing import Any
from zoneinfo import ZoneInfo

from app._generated.shared_constants import (
    BROWSE_PAGE_SIZE,
    DEFAULT_CURRENCY,
    DEFAULT_USER_CITY,
    DEFAULT_USER_LOCALE,
    HTML_SANITIZE_ALLOWED_ATTRS,
    HTML_SANITIZE_ALLOWED_TAGS,
    PERSONA_PRIMARY_WEIGHT,
    PERSONA_SECONDARY_WEIGHT,
    SAFE_URL_SCHEMES,
    VALID_CATEGORIES,
    VALID_LOCALES,
    VALID_SIGNALS,
    VALID_VIBES,
)

__all__ = [
    "BROWSE_PAGE_SIZE",
    "DEFAULT_CURRENCY",
    "DEFAULT_USER_CITY",
    "DEFAULT_USER_LOCALE",
    "HTML_SANITIZE_ALLOWED_ATTRS",
    "HTML_SANITIZE_ALLOWED_TAGS",
    "PERSONA_PRIMARY_WEIGHT",
    "PERSONA_SECONDARY_WEIGHT",
    "SAFE_URL_SCHEMES",
    "VALID_CATEGORIES",
    "VALID_LOCALES",
    "VALID_SIGNALS",
    "VALID_VIBES",
]

TALLINN_TZ_NAME = "Europe/Tallinn"
TALLINN_TZ = ZoneInfo(TALLINN_TZ_NAME)

# Application environment — value of settings.APP_ENV that enables dev-only
# behaviour (unprotected admin endpoints, SQL echo, unauthenticated /internal/tick).
# NB: app.config imports this module for the APP_ENV default, so constants.py must
# never import app.config — doing so would create a circular import.
APP_ENV_DEVELOPMENT = "development"

# Default value of settings.ADMIN_USERNAME. In production, _require_admin fails
# closed if this hasn't been overridden — a guessable, well-known Basic-auth
# username removes half of the credential pair an attacker needs to brute-force.
ADMIN_USERNAME_DEFAULT = "admin"

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400

# Recycle pooled DB connections older than this many seconds. Set below Neon's
# free-tier idle/auto-suspend window (~5 min) so we never hand out a connection
# the server has already dropped. Works together with pool_pre_ping.
DB_POOL_RECYCLE_SECONDS = 280

HTTP_TIMEOUT_SECONDS: float = 30.0
HTTP_USER_AGENT = "EventRadarBot/1.0 (+https://eventradar.ee)"
HTTP_RETRY_MAX_ATTEMPTS = 5  # bumped from 3 so backoff can outlast a short 429 penalty window
HTTP_RETRY_WAIT_MULTIPLIER = 1
HTTP_RETRY_WAIT_MIN = 2
HTTP_RETRY_WAIT_MAX = 30
HTTP_RETRY_AFTER_MAX_SECONDS: float = 60.0  # cap on an honored Retry-After header
HTTP_RETRY_JITTER_MAX: float = 1.0  # max random jitter added to the non-429 backoff wait
HTTP_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset(
    {
        http.HTTPStatus.TOO_MANY_REQUESTS,  # 429
        http.HTTPStatus.BAD_GATEWAY,  # 502
        http.HTTPStatus.SERVICE_UNAVAILABLE,  # 503
        http.HTTPStatus.GATEWAY_TIMEOUT,  # 504
    }
)

SLUG_TITLE_MAX_LEN = 60
SLUG_HASH_HEX_LEN = 8
INGESTION_ERROR_MAX_LEN = 500
PRICE_HINT_MAX_CHARS = 300  # cap on Event.price_hint, kept short for the LLM prompt

# SSRF guard (backend-only, not needed by the frontend): hostnames a source's
# event.url is allowed to carry. event.url is untrusted — it comes from
# parsed third-party page/API content — and is later fetched server-side by
# both the per-source detail-page crawl and the daily refetch job
# (app/ingestion/refetch.py), so it must be pinned to known-good hosts rather
# than trusted at face value. Suffix-matched (see host_is_allowed) so a
# legitimate subdomain (e.g. "en.fienta.com") still passes.
ALLOWED_SOURCE_HOSTS: frozenset[str] = frozenset(
    {
        "fienta.com",
        "www.piletilevi.ee",
        "kumu.ekm.ee",
        "concert.ee",
        "tallinn.fotografiska.com",
        "kultuurikatel.ee",
        "nominatim.openstreetmap.org",
    }
)

# Inbound-mail sender allowlist (domain part of the "from" header, lowercased).
# The Svix signature on POST /webhooks/inbound-mail only proves the request came
# from Resend, not who sent the underlying email — anyone able to email the
# configured inbound address could otherwise inject arbitrary content into the
# newsletter-extraction LLM prompt. Empty by default: no newsletter adapter is
# registered yet (app/ingestion/registry.py), so extraction is a no-op regardless;
# populate with trusted sender domains before wiring up the newsletter adapter.
NEWSLETTER_SENDER_ALLOWED_DOMAINS: frozenset[str] = frozenset()

# SAFE_URL_SCHEMES, HTML_SANITIZE_ALLOWED_TAGS, HTML_SANITIZE_ALLOWED_ATTRS imported
# from app._generated.shared_constants (shared/app-config.json → generate_shared.py).
# Schemes accepted for ingested event url/image_url — anything else (javascript:,
# data:, vbscript:, etc.) is dropped at ingest time to prevent stored XSS via
# untrusted source content rendered into <a href>/<img src>.
# HTML allowlist for description / important_info fields; nh3 passes plain text safely.
# Block-level wrappers that carry no allowlisted tag of their own. Some sources
# (e.g. Piletilevi) encode every line as a bare <div>; nh3 strips disallowed tags
# without inserting any separator, collapsing block boundaries into run-on text.
# sanitize_html converts these to <br> before sanitizing so line structure survives.
HTML_BLOCK_TAGS_TO_BREAK: frozenset[str] = frozenset({"div"})
# Cap runs of consecutive <br> (from nested/empty wrapper divs) at this many.
HTML_SANITIZE_MAX_CONSECUTIVE_BR = 2

# Line/block-boundary tags within HTML_SANITIZE_ALLOWED_TAGS. A text node
# touching one of these on a side has its whitespace stripped on that side
# (post-collapse) so lines don't visibly start/end with a stray space under
# the frontend's white-space: pre-wrap. Excludes inline tags (a, b, em, i,
# span, strong, u) — a word-boundary space like "text <a>link</a> more" must
# survive.
HTML_BLOCK_BOUNDARY_TAGS: frozenset[str] = frozenset(
    {"br", "p", "h3", "h4", "li", "ul", "ol", "blockquote"}
)

# Word-boundary keyword prefilter for sexually-explicit listings (en/et/ru), checked
# at ingest time against title+description+venue. Kept tight and phrase-based to
# avoid false positives ("sex" -> "Sussex", "strip" -> "comic strip"). Not exhaustive
# — Layer 2 (LLM "explicit" classification flag) catches what this misses.
EXPLICIT_KEYWORDS: frozenset[str] = frozenset(
    {
        # en
        "porn",
        "pornography",
        "pornographic",
        "xxx",
        "striptease",
        "strip club",
        "stripper",
        "lap dance",
        "sex show",
        "sex party",
        "sex shop",
        "brothel",
        "swinger",
        # kink/BDSM (en) — unambiguous terms only. Bare "kink"/"kinky" and
        # "fetish"/"fetiš" were tried and dropped: they false-positived on a
        # dance-theater piece referencing "fetish dance scene" and a
        # nonsexual cuddle-party event whose host bio mentions "kink coach".
        # Layer-1 flags skip the LLM call entirely (see classifier.py), so
        # there is no Layer-2 backstop for a Layer-1 false positive — a
        # flagged-here event never gets reviewed again. Ambiguous kink
        # references are left to Layer 2 (LLM), which now explicitly covers
        # them (see LLM_CLASSIFY_PROMPT_TEMPLATE).
        "bdsm",
        "femdom",
        "dominatrix",
        "fisting",
        "strap-on",
        "strapon",
        "shibari",
        "bondage",
        "sissification",
        "sissy play",
        "play party",
        "playparty",
        "orgy",
        "gangbang",
        "anal sex",
        "anal play",
        # et
        "porno",
        "striptiis",
        "stripiklubi",
        "sekspood",
        "seksshow",
        "intiimteenused",
        "intiim teenused",
        "bordell",
        "swinger",
        "anaalseks",
        "dominatriks",
        # ru
        "порно",
        "стриптиз",
        "стрипклуб",
        "сексшоп",
        "секс-шоп",
        "сексшоу",
        "секс-шоу",
        "интим-услуги",
        "интим услуги",
        "бордель",
        "свингер",
        "бдсм",
        "доминатрикс",
        "анальный секс",
    }
)

# Word-boundary keyword prefilter for non-event listings (gift cards, vouchers,
# merchandise, donations, webinars), checked at ingest time against the TITLE only —
# descriptions routinely mention "gift cards available" as a payment option, which
# would be a false positive. Kept tight and phrase-based (same philosophy as
# EXPLICIT_KEYWORDS); Layer 2 (LLM "non_event" classification flag) catches what
# this misses (e.g. books/merch with no keyword in the title).
NON_EVENT_TITLE_KEYWORDS: frozenset[str] = frozenset(
    {
        # et
        "kinkekaart",
        "kinkekaardid",
        "kinkepilet",
        "annetus",
        # en
        "gift card",
        "giftcard",
        "gift voucher",
        "voucher",
        "donate",
        "donation",
        # ru
        "подарочная карта",
        "подарочные карточки",
        "подарочная карточка",
        "подарочный сертификат",
        "подарочный билет",
        "вебинар",
        "вебинара",
        "вебинаров",
        "вебинары",
        # webinars (et/en)
        "webinar",
        "veebinar",
        "veebiseminar",
    }
)

# Word-boundary keywords matched against venue_name to flag online-only listings
# (webinars, course recordings, online clubs) as non-events — the product surfaces
# in-person Tallinn events only. "mamaonline" catches "MamaOnline"/"mamaonline.eu";
# "онлайн" catches "Онлайн, https://…" venue strings.
NON_EVENT_VENUE_KEYWORDS: frozenset[str] = frozenset(
    {
        "online",
        "онлайн",
        "veebis",
        "mamaonline",
    }
)

# Locales fetched for native-language title/description at ingest time.
# Fienta exposes en/et/ru; HTML listing sources expose only en/et.
# Seconds to sleep between consecutive locale-variant detail fetches in HTML listing
# adapters — paces requests without a full rate limiter (HTML sources have no API quota).
HTML_LISTING_LOCALE_FETCH_DELAY_SECONDS: float = 0.5
LOCALIZED_TEXT_FIENTA_LOCALES: frozenset[str] = frozenset({"en", "et", "ru"})
LOCALIZED_TEXT_HTML_LOCALES: frozenset[str] = frozenset({"en", "et"})
# hreflang value used by Fienta for Russian (some pages use "ru", site also
# uses "ru-RU"; we normalise to "ru" after lower-casing).
LOCALIZED_TEXT_HREFLANG_NORMALIZE: dict[str, str] = {"ru-ru": "ru", "et-ee": "et", "en-gb": "en", "en-us": "en"}
# Maximum chars kept from a localized title/description to avoid DB bloat.
LOCALIZED_TEXT_MAX_TITLE_CHARS = 500
LOCALIZED_TEXT_MAX_DESC_CHARS = 5000

ORGANIZER_MIN_EVENTS_FOR_AUTO_ADD = 3
ORGANIZER_NAME_MAX_LEN = 200
FIENTA_ORGANIZER_SCAN_LIMIT = 1000
FIENTA_ORGANIZER_CHECK_LIMIT = (
    5  # max events fetched when probing a single organizer for staleness
)
# An organizer that has returned 0 events on every weekly probe for this many
# days is retired: dropped from organizer_ids into retired_organizer_ids, no
# longer polled by hourly ingest or the weekly probe. A revival (auto-discovery
# sees it again with enough events) rejoins organizer_ids.
STALE_ORGANIZER_RETIRE_DAYS = 30
FIENTA_CITY_FILTER = "Tallinn"
FIENTA_MAX_PAGES = 50  # safety ceiling per organizer — prevents runaway pagination
# Concurrency cap for detail-page fan-out. The shared AsyncRateLimiter (below)
# now paces every request, so this is a secondary guard rather than the primary
# defense against bursts — lowered to match the ~8-request trip point observed
# in production logs before the limiter existed.
DETAIL_FETCH_CONCURRENCY: int = 3
# Min seconds between consecutive Fienta requests (listing + detail), shared via
# one AsyncRateLimiter per fetch_raw() run. ~3 req/s — conservative vs the ~7 req/s
# burst that triggered a 429 cascade in production.
FIENTA_MIN_REQUEST_INTERVAL_SECONDS: float = 0.34
# Bounding box for Estonia (lat_min, lat_max, lng_min, lng_max).
# Used to reject geo coords from detail pages that are clearly wrong (>~80 km off).
ESTONIA_BBOX: tuple[float, float, float, float] = (57.5, 59.7, 21.5, 28.2)
# Generous greater-Tallinn/Harju bounding box: rejects Pärnu/Tartu (~58.3 lat)
# and all foreign coords while keeping suburban Tallinn venues.
TALLINN_REGION_BBOX: tuple[float, float, float, float] = (59.2, 59.7, 24.3, 25.3)

SOURCE_STATUS_OK = "ok"
SOURCE_STATUS_ERROR = "error"

EVENT_STATUS_DRAFT = "draft"
EVENT_STATUS_CLASSIFIED = "classified"
EVENT_STATUS_PUBLISHED = "published"
EVENT_STATUS_CANCELLED = "cancelled"

# Deduplication
DEDUP_LOOKBACK_DAYS = 30  # only re-cluster events that started within this window
TITLE_RATIO_THRESHOLD = 70  # rapidfuzz token_set_ratio threshold for title match
TITLE_RATIO_VENUE_BYPASS_THRESHOLD = 85  # near-exact title; on the LLM path, bypass
# the venue gate at/above this so cross-source dupes with differently-spelled venues
# (incl. cross-language spellings, e.g. "Estonia kontserdisaal" vs "Estonia Concert
# Hall") still reach the LLM tiebreaker (rule-only path stays strict)
VENUE_RATIO_THRESHOLD = 70  # rapidfuzz token_set_ratio threshold for venue match
TIME_WINDOW_HOURS = 12  # max |Δstart| in hours for two events to be dedup candidates
# cluster_events()'s unfiltered fallback (no candidate_pair_ids) is an O(N^2) Python
# enumeration — both production callers always pass pre-filtered pairs, so this path is
# test-only scaffolding today. Hard-cap it so a future caller invoking it on a large
# unfiltered event list fails loudly instead of silently degrading to quadratic time;
# well above any legitimate test's event count.
DEDUP_UNFILTERED_FALLBACK_MAX_EVENTS = 500

# Resend email delivery
RESEND_SEND_URL = "https://api.resend.com/emails"
RESEND_TIMEOUT_SECONDS: float = 10.0
RESEND_ERROR_SNIPPET_LEN = 200
# Email i18n strings (subjects, labels, templates) live in shared/i18n/*.json.
DIGEST_SEND_HOUR = 7  # 07:00 Europe/Tallinn, one hour after build_daily_feeds
DIGEST_MAX_WHY_GO_BULLETS = 3
# Concurrency cap when fanning out digest sends — bounded by Resend free-tier
# rate (10 req/s). Eight in-flight sends leaves headroom for occasional retries.
DIGEST_SEND_CONCURRENCY: int = 8

# Admin endpoint pagination
ADMIN_DEDUP_GROUPS_PAGE_SIZE: int = 50
ADMIN_DEDUP_GROUPS_MAX_PAGE_SIZE: int = 500

# Per-IP rate limits (slowapi / limits syntax: "<count>/<period>"). These guard
# auth + webhook endpoints against enumeration, quota-exhaustion, and email-bombing
# attacks that the per-email cooldown (request-link) doesn't cover — see main.py::limiter.
RATE_LIMIT_AUTH_REQUEST_LINK = "10/minute"
RATE_LIMIT_AUTH_VERIFY = "30/minute"
RATE_LIMIT_WEBHOOK_INBOUND_MAIL = "60/minute"

# Resend inbound-mail webhook signature verification (Svix scheme; see
# https://resend.com/docs/dashboard/webhooks/verify-webhooks-requests and
# https://docs.svix.com/receiving/verifying-payloads/how-manual). Verifying
# over the raw body via these headers replaces the old ?secret= query-string
# check, which leaked the shared secret into proxy/access logs.
SVIX_ID_HEADER = "svix-id"
SVIX_TIMESTAMP_HEADER = "svix-timestamp"
SVIX_SIGNATURE_HEADER = "svix-signature"
SVIX_SECRET_PREFIX = "whsec_"
# Reject a signature whose svix-timestamp is further than this from "now" (either
# direction), blocking replay of an old, legitimately-signed request. Matches
# Svix's own recommended default tolerance.
WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS = 300
# Public read endpoint — generous enough for normal browsing while throttling
# ID-enumeration / scraping abuse (GET /events/{id} takes no auth).
RATE_LIMIT_EVENTS_DETAIL = "120/minute"
# Admin Basic-auth surface — per-endpoint cap; with 11 admin routes an attacker
# cycling all endpoints could attempt up to ~110/minute, so this is a speed-bump
# rather than a hard brute-force ceiling. Pair with a strong ADMIN_PASSWORD.
RATE_LIMIT_ADMIN = "10/minute"
# Authenticated feedback writes — generous cap; prevents cache-rebuild DoS
# (every signal wipes all user_event_scores rows for that user).
RATE_LIMIT_FEEDBACK = "60/minute"
# Authenticated state-changing writes (onboarding persona, settings GET/PATCH) —
# damps self-inflicted DB write spam from a valid session token.
RATE_LIMIT_AUTHENTICATED_WRITE = "30/minute"
# Tighter cap for logout-all: bumps session_token_version, revoking every
# issued session token (including the caller's own) — a higher-value target
# than ordinary writes.
RATE_LIMIT_LOGOUT_ALL = "10/minute"
# Authenticated /explore browsing — mirrors RATE_LIMIT_EVENTS_DETAIL; live filter
# changes can fire a request per keystroke/chip-toggle, so this stays generous.
RATE_LIMIT_BROWSE = "120/minute"
# Public, unauthenticated landing-page showcase (GET /public/showcase). No auth,
# so throttle scraping abuse; generous enough for real visitors loading the page.
RATE_LIMIT_PUBLIC = "60/minute"
# How many events the landing-page showcase returns — a fixed, small teaser grid
# (top-quality upcoming events), so no pagination is needed.
SHOWCASE_EVENT_COUNT = 6

# Auth tokens
AUTH_MAGIC_SALT = "magic-link-v1"
AUTH_SESSION_SALT = "session-v1"

# Per-email magic-link resend cooldown (routers/auth.py::_recent_unused_link_exists) —
# prevents Resend quota exhaustion from rapid repeat requests for the same address.
MAGIC_LINK_RESEND_COOLDOWN_SECONDS = 120

# PII masking — number of leading local-part characters kept visible by mask_email()
# (routers/utils.py) so log lines stay correlatable without persisting raw addresses.
EMAIL_MASK_VISIBLE_CHARS = 2

# Ranking / scoring
DAILY_5_COUNT = 5
DAILY_5_MAX_PER_CATEGORY = 2
DAILY_5_BACKFILL_MAX_PER_CATEGORY = 3  # relaxed per-category cap during backfill;
# Tier-1 MMR keeps DAILY_5_MAX_PER_CATEGORY (2). Exceeded only by the final
# uncapped sweep, so the feed still reaches DAILY_5_COUNT when events are scarce.
DAILY_5_LOOKAHEAD_DAYS = 14
# How many past days' feeds to scan for a recurring-series repeat before allowing
# that series back into a user's Daily 5 pool — keeps a multi-day series (one
# canonical event per day) from being re-picked night after night.
DAILY5_SERIES_COOLDOWN_DAYS = 3
RECENCY_DECAY_DAYS = 21
FEEDBACK_DECAY_BASE: float = 0.9  # per-day decay on feedback signal
FEEDBACK_INDIRECT_WEIGHT: float = 0.5  # weight of category-matched indirect signal
SCORE_HARD_EXCLUDE: float = (
    -2.0
)  # sentinel: outside [-1,1] clamp, cannot be a valid score
NEUTRAL_SCORE: float = 0.5  # neutral midpoint returned when a signal's data is unknown
SCORE_WEIGHT_AFFINITY: float = 0.45
SCORE_WEIGHT_RECENCY: float = 0.20
SCORE_WEIGHT_FEEDBACK: float = 0.20
SCORE_WEIGHT_QUALITY: float = 0.10
SCORE_WEIGHT_LOCALITY: float = 0.05
# _time_slots_for_event() memoization cap (ranking/score.py) — bounds an lru_cache keyed
# on distinct starts_at values so repeated calls across users scoring the same event
# don't redo the astimezone conversion. Comfortably above the number of distinct
# starts_at values in one DAILY_5_LOOKAHEAD_DAYS candidate window.
TIME_SLOTS_CACHE_MAXSIZE = 4096

# GET /explore (app/routers/browse.py) — event discovery / search page.
# BROWSE_PAGE_SIZE itself is cross-stack (shared/app-config.json), imported above.
BROWSE_MAX_PAGE_SIZE: int = 60
# Candidate cap for the Python-scored path (Path B: for_you=True OR sort=relevance —
# so also date/price/quality sort *under* for_you=True, not just relevance). Sorted
# soonest-first before capping, so the cap policy is a deliberate soonest-bias, not
# an arbitrary truncation: a date sort still yields globally-correct soonest-first
# results, but price/quality sort under for_you=True is only a true sort within the
# soonest BROWSE_RELEVANCE_MAX_CANDIDATES matches, not a global one — an accepted
# Path-B approximation at MVP scale (`total` in the response reflects at most this
# many rows when the cap is hit; see browse.py docstring).
BROWSE_RELEVANCE_MAX_CANDIDATES: int = 300
# For-you soft-filter: events below this persona_affinity() score ([0, 1], see
# ranking/score.py) are hidden from the For-you pool. Tuned below NEUTRAL_SCORE (0.5)
# so an event with no strong signal either way still surfaces; only a
# below-neutral (poor) match is filtered out.
BROWSE_FORYOU_MIN_AFFINITY: float = 0.4
BROWSE_SORT_RELEVANCE = "relevance"
BROWSE_SORT_DATE = "date"
BROWSE_SORT_PRICE = "price"
BROWSE_SORT_QUALITY = "quality"
VALID_BROWSE_SORTS: frozenset[str] = frozenset(
    {BROWSE_SORT_RELEVANCE, BROWSE_SORT_DATE, BROWSE_SORT_PRICE, BROWSE_SORT_QUALITY}
)
# Sorts expressible as pure SQL ORDER BY — reachable via Path A (_browse_sql_path)
# when for_you=False. relevance always needs Python scoring (persona affinity),
# so it's deliberately excluded.
BROWSE_SQL_SORTS: frozenset[str] = frozenset(
    {BROWSE_SORT_DATE, BROWSE_SORT_PRICE, BROWSE_SORT_QUALITY}
)
# Sentinel for "no comparable value" in a Python sort key (e.g. missing quality_score),
# so unranked rows always sort last regardless of ascending/descending direction.
BROWSE_NEG_INF = float("-inf")
# /users/me preferred_categories/preferred_vibes (serialize_user) — a persona
# affinity_vector entry counts as "in the user's taste" once its weight clears this
# bar. Used by the frontend to decide the For-you⇄All-events auto-flip.
PREFERRED_TASTE_MIN_WEIGHT: float = 0.5

# Publish gate — classified events with quality_score below this stay
# 'classified' and never reach a feed. Tunable later from real data.
PUBLISH_MIN_QUALITY_SCORE: float = 0.4

# Tallinn centre bounding box (~5 km radius) used for locality bonus
TALLINN_CENTER_LAT: float = 59.437
TALLINN_CENTER_LNG: float = 24.745
TALLINN_LAT_DELTA: float = 0.05
TALLINN_LNG_DELTA: float = 0.10

# Feedback signals
SIGNAL_LIKE = "like"
SIGNAL_DISLIKE = "dislike"
SIGNAL_BOOKMARK = "bookmark"
# Explicit preference signals — current-state (one row per user/event), enforced by
# the partial unique index in migration 0019. "view"/"click_external" (the rest of
# VALID_SIGNALS) are passive analytics signals that stay append-only/multi-row and
# must never share that index — see feedback.py::record_feedback.
PREFERENCE_SIGNALS: frozenset[str] = frozenset(
    {SIGNAL_LIKE, SIGNAL_DISLIKE, SIGNAL_BOOKMARK}
)
# Guard: if shared/app-config.json signals ever diverge from these sentinels, fail fast.
assert SIGNAL_LIKE in VALID_SIGNALS, f"{SIGNAL_LIKE!r} missing from VALID_SIGNALS in shared/app-config.json"
assert SIGNAL_DISLIKE in VALID_SIGNALS, f"{SIGNAL_DISLIKE!r} missing from VALID_SIGNALS in shared/app-config.json"
assert SIGNAL_BOOKMARK in VALID_SIGNALS, f"{SIGNAL_BOOKMARK!r} missing from VALID_SIGNALS in shared/app-config.json"
assert PREFERENCE_SIGNALS <= VALID_SIGNALS, "PREFERENCE_SIGNALS must be a subset of VALID_SIGNALS"
# SQL predicate for the migration-0019 partial unique index over preference
# signals. Derived from PREFERENCE_SIGNALS so the upsert's index_where can never
# drift from the set of signals it covers. sorted() makes it deterministic;
# element order is irrelevant to Postgres ON CONFLICT arbiter selection, which
# matches by predicate implication, so this stays equivalent to migration 0019.
PREFERENCE_SIGNALS_SQL_PREDICATE = "signal IN ({})".format(
    ", ".join(f"'{s}'" for s in sorted(PREFERENCE_SIGNALS))
)

# Time-of-day / day-of-week slots derived from event.starts_at (Europe/Tallinn).
# An event can match multiple slots simultaneously (e.g. Saturday evening → weekend + evening).
# late_night: 22:00–05:59  |  evening: 18:00–21:59  |  daytime: 10:00–17:59  |  morning: 06:00–09:59
# weekend: Sat/Sun  |  weekday: Mon–Fri
TIME_SLOT_LATE_NIGHT = "late_night"
TIME_SLOT_EVENING = "evening"
TIME_SLOT_DAYTIME = "daytime"
TIME_SLOT_MORNING = "morning"
TIME_SLOT_WEEKEND = "weekend"
TIME_SLOT_WEEKDAY = "weekday"
WEEKEND_START_WEEKDAY = 5  # Monday=0 … Saturday=5, Sunday=6

VALID_TIMES: frozenset[str] = frozenset(
    {
        TIME_SLOT_LATE_NIGHT,
        TIME_SLOT_EVENING,
        TIME_SLOT_DAYTIME,
        TIME_SLOT_MORNING,
        TIME_SLOT_WEEKEND,
        TIME_SLOT_WEEKDAY,
    }
)
TIME_LATE_NIGHT_START = 22
TIME_EVENING_START = 18
TIME_DAYTIME_START = 10
TIME_MORNING_START = 6

# LLM
LLM_MAX_PROMPT_CHARS = 1200  # cap on event text passed to classification prompt
IMPORTANT_INFO_MAX_CHARS = 1200  # cap on Piletilevi "important info" text in the prompt
PRICE_CONTEXT_MAX_CHARS = 700  # cap on the price-lines digest passed to the prompt
LLM_MAX_TOKENS = 400  # max completion tokens per LLM call
LLM_REASONING_MAX_TOKENS = 600  # ceiling (project hard cap); leaves room for reasoning + answer
LLM_DEDUP_CONFIDENCE_THRESHOLD: float = (
    0.7  # minimum confidence to accept LLM same=true verdict
)
LLM_CLASSIFY_BATCH_SIZE = 30  # max events processed per classify_pending run
LLM_REQUEST_TIMEOUT_SECONDS: float = 30.0

LLM_DEDUP_TITLE_MAX_LEN = 200
LLM_DEDUP_VENUE_MAX_LEN = 100
# llm_calls.task label for the dedup tiebreaker LLM call — shared by the fresh-call
# site and the cache-prefetch query so they can never drift out of sync.
LLM_TASK_DEDUP = "dedup"
# Bounds fresh (cache-miss) network calls per pass — bounds DB session lifetime
# against slow providers (Cerebras fallback ~1 req/min). Cache hits are cheap
# indexed lookups and are NOT counted against this cap; see llm_tiebreaker.py.
LLM_DEDUP_MAX_FRESH_LLM_CALLS_PER_PASS = 100
# Chunk size for the bulk llm_calls prefetch IN-list, to bound query size.
LLM_DEDUP_HASH_QUERY_CHUNK_SIZE = 500

# Backlog drain: when a periodic LLM job (dedup / classify) finishes a pass with
# work still undone, re-run it on this short interval instead of waiting for the
# next 6h cycle. Bounded by a pass cap so a provider outage can't spin forever.
LLM_BACKLOG_RETRY_SECONDS = 900  # 15 min between drain passes
LLM_BACKLOG_MAX_DRAIN_PASSES = 12  # ceiling; then defer to the next 6h cycle

# Dedup summary fields that are a snapshot of corpus state recomputed on every
# pass (total events considered, candidate pairs, group counts) rather than
# work done during that pass — summing them across passes would inflate them
# by roughly a factor of `passes`. _aggregate_summaries (jobs.py) reports the
# last pass's value for these instead of summing.
AGGREGATE_LAST_VALUE_FIELDS = frozenset(
    {"total", "candidate_pairs", "grouped", "groups"}
)

LLM_CLASSIFY_WHY_GO_MAX_BULLETS = 3
LLM_CLASSIFY_LANGUAGE_CODE_MAX_LEN = 5
CURRENCY_CODE_MAX_LEN = 3  # mirrors Event.currency String(3)
LLM_CLASSIFY_VENUE_FALLBACK = "unknown"
LLM_CLASSIFY_DESC_FALLBACK = "(no description)"
LLM_CLASSIFY_PRICE_HINT_FALLBACK = "not stated"
LLM_CLASSIFY_IMPORTANT_INFO_FALLBACK = "(none)"
LLM_CLASSIFY_PRICE_CONTEXT_FALLBACK = "(none)"
LLM_CLASSIFY_EXPLICIT_DEFAULT = False
LLM_CLASSIFY_NON_EVENT_DEFAULT = False
LLM_CLASSIFY_IN_TARGET_CITY_DEFAULT = True
LLM_CLASSIFY_HAS_FREE_TIER_DEFAULT = False
# Tolerance (EUR) for matching an LLM-reported price against amounts literally
# present in price_hint/price_context — guards against float round-trip noise
# while still rejecting a genuinely invented number.
LLM_CLASSIFY_PRICE_MATCH_TOLERANCE = 0.01
# llm_calls.task label for the classification LLM call.
LLM_TASK_CLASSIFY = "classify"

# Venue address extraction — LLM pass that mines street addresses out of venue_name
# into venue_address so the event becomes geocodable.
LLM_TASK_VENUE_EXTRACT = "venue_extract"
# et/en direction markers that flag a venue_name as likely containing an address or
# being a pure direction phrase rather than a real venue name.
VENUE_NAME_DIRECTION_KEYWORDS: frozenset[str] = frozenset(
    {
        "algus",
        "kõrval",
        "asuv",
        "ees",
        "vastas",
        "juures",
        "taga",
        "meeting point",
        "in front of",
        "next to",
        "near",
    }
)
# A venue_name longer than this is treated as suspect (direction phrases run long).
VENUE_NAME_SUSPECT_MAX_LEN = 40
# Fresh (cache-miss) LLM call budget per geocode run for venue extraction.
VENUE_EXTRACT_MAX_FRESH_LLM_CALLS_PER_RUN = 50
# Max chars of venue_name fed into the extraction prompt.
VENUE_NAME_PROMPT_MAX_CHARS = 200


# Newsletter inbound email extraction
LLM_TASK_NEWSLETTER = "newsletter_extract"
SOURCE_SLUG_NEWSLETTER = "newsletter_inbound"
NEWSLETTER_SUBJECT_MAX_LEN = 200
NEWSLETTER_BODY_MAX_LEN = 1500


LLM_PROVIDERS: list[dict[str, Any]] = [
    {
        "name": "groq",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "key_attr": "GROQ_API_KEY",
    },
    {
        "name": "cerebras",
        "base_url": "https://api.cerebras.ai/v1",
        "model": "gpt-oss-120b",
        "key_attr": "CEREBRAS_API_KEY",
        # gpt-oss-120b is a reasoning model: reasoning tokens precede the answer
        # and count against max_tokens, so it gets a larger cap and lower effort.
        "max_tokens": LLM_REASONING_MAX_TOKENS,
        "params": {"reasoning_effort": "low"},
    },
    {
        "name": "mistral",
        "base_url": "https://api.mistral.ai/v1",
        "model": "mistral-small-latest",
        "key_attr": "MISTRAL_API_KEY",
    },
]

# Source slugs — single source of truth; imported by registry.py and seeds.py
SOURCE_SLUG_FIENTA = "fienta"
SOURCE_SLUG_TELLISKIVI = "telliskivi"
SOURCE_SLUG_KULTUURIKATEL = "kultuurikatel"
SOURCE_SLUG_FOTOGRAFISKA = "fotografiska"
SOURCE_SLUG_KUMU = "kumu"
SOURCE_SLUG_ESTONIA_CONCERT_HALL = "estonia_concert_hall"
SOURCE_SLUG_PILETILEVI = "piletilevi"

# Source kinds
SOURCE_KIND_API = "api"
SOURCE_KIND_HTML_SCRAPE = "html_scrape"
SOURCE_KIND_INBOUND_EMAIL = "inbound_email"

HTML_LISTING_MAX_DETAIL_FETCHES = (
    300  # cap per ingestion run on capped-detail sources (piletilevi) — headroom
    # above observed 206-220 new-card runs, which truncated detail fetches at 200
)

# Geocoding (Nominatim) — used to backfill lat/lng for events that have an address
# but no coordinates (currently: Fienta). Usage policy requires a descriptive
# User-Agent with contact info and a max of 1 request/second.
NOMINATIM_BASE_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = "EventRadarBot/1.0 (+https://eventradar.ee; aleksei.lutkov@gmail.com)"
GEOCODE_REQUEST_DELAY_SECONDS: float = 1.0
GEOCODE_MAX_PER_RUN = 200  # ~3.5 min/run at 1 req/s, safely under the 6h cron cadence
# Commit mid-loop at this wall-clock interval to keep the held DB connection warm
# under Neon's ~5-min idle auto-suspend and persist progress incrementally.
GEOCODE_COMMIT_INTERVAL_SECONDS: float = 120.0
# An address that fails to geocode (no Nominatim match, or a match outside
# TALLINN_REGION_BBOX) is not re-queried on every run; it is retried after this
# window, mirroring REFETCH_MIN_INTERVAL_DAYS's cooldown shape. A transient HTTP
# failure does NOT start this cooldown — only a definitive no-match/bbox-reject does.
GEOCODE_RETRY_INTERVAL_DAYS = 7
# Decimal places to round (lat, lng) to when counting *distinct* donor coords in the
# sibling-copy ambiguity guard. 6 ≈ 0.1 m — collapses sub-meter float-representation
# differences (e.g. 59.43793509999999 vs 59.4379351) that would otherwise read as two
# separate venues. Used for the distinct-count only; a real unrounded donor coord is
# still written to the event.
GEOCODE_COORD_QUANT_DECIMALS = 6

# Address normalization for geocoding — Estonian street-type words to REMOVE
# entirely before querying Nominatim. OSM stores these street types by bare name,
# so the type word (full or abbreviated) is exactly what makes the match fail —
# e.g. "Telliskivi tänav 60a"/"Telliskivi tn 60a" miss, "Telliskivi 60a" hits.
# Deliberately EXCLUDED:
#   - "plats"/"väljak"/"allee" — for squares/alleys the type word is part of the
#     OSM name, so stripping it would hurt.
#   - "tee" — many Tallinn streets carry "tee" as an inseparable part of their OSM
#     name (Mustamäe tee, E. Vilde tee, Järvevana tee). Stripping it would collapse
#     "Mustamäe tee 25" → "Mustamäe 25", which Nominatim resolves to the Mustamäe
#     *district* centroid — silently wrong coordinates, worse than a clean no-match.
ESTONIAN_STREET_TYPE_WORDS: frozenset[str] = frozenset(
    {
        "tänav",
        "tn",
        "maantee",
        "mnt",
        "puiestee",
        "pst",
        "põik",
        "street",
    }
)

# Leading personal-name initial stripped before geocoding (e.g. "A. Weizenbergi"
# → "Weizenbergi", "L.Koidula" → "Koidula") — Nominatim misses the initialled form.
GEOCODE_INITIAL_RE = r"^\s*[A-ZÄÖÜÕ]\.\s*"

# Suffix that should be stripped from building numbers before geocoding
# e.g. "60a/9", "60a/ 9", "60a / 9" → "60a"
GEOCODE_UNIT_SUFFIX_RE = r"(\s*/\s*\d+[a-z]?)"

# Floor / extra-info fragments stripped before geocoding (e.g. ", II korrus")
GEOCODE_FLOOR_RE = r",?\s+[IVX]+\s+korrus\b.*"

# Comma-delimited secondary-unit fragments (English) stripped before geocoding,
# e.g. ", building A", ", 3rd floor" — Nominatim has no node for these.
GEOCODE_SECONDARY_UNIT_RE = r",\s*[^,]*\b(?:building|floor)\b[^,]*"

# Trailing Estonian county markers stripped before geocoding. Covers the spaced
# "Harju maakond", the one-word "Harjumaakond", "Harjumaa", and the bare/English
# "Harju" / "Harju County" forms seen in the geocode logs.
GEOCODE_COUNTY_RE = (
    r",\s*[\w-]+\s+maakond\b.*"
    r"|,\s*[\w-]+maakond\b.*"
    r"|,\s*Harjumaa\b.*"
    r"|,\s*Harju\b.*"
)

# Country suffix appended to Nominatim query to anchor results
GEOCODE_COUNTRY_SUFFIX = ", Estonia"

# Parenthetical segment stripped from a venue_name before sibling venue matching,
# e.g. "Sõltumatu Tantsu Lava (STL)" → "Sõltumatu Tantsu Lava". Compiled in geocode.py.
VENUE_NAME_PARENS_RE = r"\([^)]*\)"

# Canonical venue names that are not physical/geocodable locations. Skipped on both
# the target and donor side of sibling venue copy so virtual events ("Online",
# "MamaOnline") never inherit a junk donor's coords — compared against the canonical
# form (canonical_venue_name). Extend with future virtual labels.
NON_GEOCODABLE_VENUE_NAMES = frozenset({"online"})

# Sibling venue-copy match threshold (rapidfuzz fuzz.ratio over canonical names).
# Distinct from the dedup VENUE_RATIO_THRESHOLD (70): canonicalization strips the
# parts that differ between a venue and its sibling, so intended matches score 98-100
# (typo variants ~93). A symmetric ratio at 90 keeps those while rejecting the
# token-subset false-positives a token_set_ratio would score 100 (e.g. a comma-split
# "soprus" vs an unrelated "Kino Soprus").
VENUE_SIBLING_RATIO_THRESHOLD = 90

# Detail-refetch sync (refetch.py) — a daily job that re-fetches every future
# event's detail page and reconciles venue/address/coords/price against the source.
# Generic schema.org JSON-LD, so it no-ops on pages without an Event block.
# Sized above the full future-event set (~700 today) so one daily run covers
# everything; doubles as a safety valve. At REFETCH_REQUEST_DELAY_SECONDS that is
# ~12 min/run, fine for a 04:30 cron.
REFETCH_MAX_PER_RUN = 1000
REFETCH_REQUEST_DELAY_SECONDS: float = 1.0
# Flat daily throttle: an event re-synced within this window is not due again.
# Guards mainly against manual POST /admin/refetch re-runs; the cron fires once daily.
REFETCH_MIN_INTERVAL_DAYS = 1
# Absolute tolerance (currency units) when comparing a stored price against the
# detail-page price — sub-cent float noise must read as "unchanged", not a change.
REFETCH_PRICE_TOLERANCE = 0.005
# Mid-loop commit cadence — see GEOCODE_COMMIT_INTERVAL_SECONDS for the rationale.
REFETCH_COMMIT_INTERVAL_SECONDS: float = 120.0
# An external_id fetched but rejected by normalize() (e.g. non-Tallinn) is not
# re-fetched/re-saved on every run; it is retried once after this window so a
# transient rejection still self-heals. Pure backend scalar — not cross-stack.
INGEST_REJECT_RECHECK_DAYS = 7
# venue_name values treated as empty/placeholder, so a real detail name replaces
# them. Matched case-insensitively. Deliberately excludes "online"/"MamaOnline" —
# those are real (online) venue names, not placeholders (NON_GEOCODABLE_VENUE_NAMES
# governs their *address* handling, not name replacement).
REFETCH_PLACEHOLDER_VENUE_NAMES: frozenset[str] = frozenset(
    {"tbd", "tba", "---", "n/a", "unknown"}
)
# Mirrors Event.venue_name String(255) — truncation length for a detail-page
# venue name before it is written back to the column.
VENUE_NAME_MAX_LEN = 255

# Booking/service/agent fee keywords — amounts that follow these must NOT be read
# as ticket prices. Piletilevi glues fee disclaimers into important_info
# ("agenditasu 3,20 €", "teenustasu 1.40€/ pilet"), causing the LLM to latch onto
# the fee as price_min. strip_fee_amounts() in ingestion/pricing.py uses these at
# prompt-build time to remove the fee clause before the LLM sees the text.
PRICE_FEE_KEYWORDS: frozenset[str] = frozenset(
    {
        "teenustasu",
        "teenindustasu",
        "agenditasu",
        "käsitlustasu",
        "broneerimistasu",
        "service fee",
        "booking fee",
        "handling fee",
        "agent fee",
        "transaction fee",
    }
)
# Strips a fee keyword + the amount immediately following it (within a short
# lookahead window) so the real ticket price that may trail in the same run
# ("agenditasu 3,20 € Pilet 45 €") survives the substitution.
# Built from PRICE_FEE_KEYWORDS at module load in ingestion/pricing.py.
PRICE_FEE_CLAUSE_RE = (
    r"(?:{keywords})[^\d€]{{0,25}}?\d+(?:[.,]\d+)?\s*(?:€|eur(?:\b|/))"
)

# Parses a Fienta listing price_from_string: "From 9.50 EUR" / "12 EUR" — a number
# (int or decimal, "." or "," separator) followed by any 3-letter currency code.
PRICE_FROM_STRING_RE = r"(?:from\s+)?(\d+(?:[.,]\d+)?)\s*([A-Za-z]{3})"

# Free-tier keywords across et/en/ru — a "0" reported by the LLM is only trusted
# when one of these literally appears in the text; otherwise it's treated as an
# invented number (llm/classifier.py::_validate_llm_prices).
FREE_TIER_KEYWORDS: frozenset[str] = frozenset({"free", "tasuta", "бесплатно"})

# Matches a EUR amount in either order: "€16", "16 €", "16€", "EUR 16", "16 EUR".
# \bEUR\b guards against incidental substrings ("European", "16EURO", "EUR-zone")
# being mistaken for the currency code. Used to deterministically widen the
# classifier's [price_min, price_max] envelope against the literal amounts in a
# multi-tier price_hint.
CURRENCY_AMOUNT_RE = (
    r"(?:€|\bEUR\b)\s*(\d+(?:[.,]\d{1,2})?)|(\d+(?:[.,]\d{1,2})?)\s*(?:€|\bEUR\b)"
)

# CORS — restricted to the methods/headers the SPA actually sends (see
# frontend/src/api/client.ts and routers/*.py route decorators). Credentials are
# never used (auth is a Bearer header, not a cookie), so allow_credentials=False.
CORS_ALLOWED_METHODS: list[str] = ["GET", "POST", "PATCH"]
CORS_ALLOWED_HEADERS: list[str] = ["Authorization", "Content-Type"]

# Logging — configure_logging() in app.logging_config wires these into the root
# logger. Format/date strings render UTC ISO 8601 timestamps on every line (app,
# uvicorn, and SQL echo alike).
LOG_LEVEL_DEFAULT = "INFO"
LOG_FORMAT_TEXT = "%(asctime)s.%(msecs)03dZ %(levelname)-8s %(name)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"
LOG_DIR_NAME = "logs"
LOG_FILE_NAME = "app.log"
LOG_FILE_MAX_BYTES = 5 * 1024 * 1024  # 5 MB per file
LOG_FILE_BACKUP_COUNT = 5  # ~25 MB total dev history
LOG_SHIP_TIMEOUT_SECONDS = 5.0
LOG_SHIP_QUEUE_MAXSIZE = 10_000  # bounded; drop-newest if shipping stalls
# Loggers configured by frameworks/libraries before configure_logging() runs —
# stripped of their own handlers and re-pointed at the root logger so every
# line (app, uvicorn, SQL echo) shares the same timestamped format.
LOG_FRAMEWORK_LOGGER_NAMES: tuple[str, ...] = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "sqlalchemy.engine",
)

# Security response headers — applied to every response by SecurityHeadersMiddleware
# (app.main). This is a pure JSON API with no first-party HTML/script surface, so the
# CSP can be maximally restrictive; frame-ancestors/X-Frame-Options block clickjacking.
SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # Pure JSON API, nothing should ever be cached by an intermediary — most
    # importantly, GET /auth/verify returns a bearer session_token in the body.
    "Cache-Control": "no-store",
}
# HSTS is only safe to send over HTTPS — Render terminates TLS in front of the app,
# so this is gated to production (see app.main) to avoid breaking local http://localhost.
HSTS_HEADER_NAME = "Strict-Transport-Security"
HSTS_MAX_AGE_SECONDS = 31536000  # 1 year, matches HSTS preload-list minimum
HSTS_HEADER_VALUE = f"max-age={HSTS_MAX_AGE_SECONDS}; includeSubDomains"

# Data retention — app/cleanup.py::cleanup_stale_data(), weekly Sun 03:30 EET.
# These prune satellite/audit tables only; `events` rows are never deleted.
MAGIC_LINK_RETENTION_DAYS = 7  # expired/used auth_magic_links rows
LLM_CALLS_RETENTION_DAYS = 90  # also the dedup/classification cache window
# Trade-off: a one-off forensic/backfill script reading raw_events.payload
# cannot recover a row pruned past this window — any future script needing
# raw payloads must run within 90 days of ingest, or this constant must be
# raised first.
RAW_EVENTS_RETENTION_DAYS = 90
INGESTION_RUNS_RETENTION_DAYS = 90
RAW_INBOUND_EMAILS_RETENTION_DAYS = 90
DAILY_FEEDS_RETENTION_DAYS = 30
USER_EVENT_SCORES_RETENTION_DAYS = 30  # keyed on the underlying event's end date
