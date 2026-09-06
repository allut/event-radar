import http
import logging
from typing import Any, Literal
from zoneinfo import ZoneInfo

from app._generated.shared_constants import (
    APP_VERSION,
    BROWSE_PAGE_SIZE,
    DEFAULT_CURRENCY,
    DEFAULT_USER_CITY,
    DEFAULT_USER_LOCALE,
    HTML_SANITIZE_ALLOWED_ATTRS,
    HTML_SANITIZE_ALLOWED_TAGS,
    IMAGE_UPLOAD_ALLOWED_MIME,
    MAGIC_LINK_TTL_MINUTES as _MAGIC_LINK_TTL_MINUTES_SHARED,
    PERSONA_MAX_SELECTABLE,
    PERSONA_PRIMARY_WEIGHT,
    PERSONA_SECONDARY_WEIGHT,
    PERSONA_TERTIARY_WEIGHT,
    SAFE_URL_SCHEMES,
    SESSION_TTL_DAYS as _SESSION_TTL_DAYS_SHARED,
    VALID_CATEGORIES,
    VALID_LOCALES,
    VALID_SIGNALS,
    VALID_VIBES,
)

__all__ = [
    "APP_VERSION",
    "BROWSE_PAGE_SIZE",
    "DEFAULT_CURRENCY",
    "DEFAULT_USER_CITY",
    "DEFAULT_USER_LOCALE",
    "HTML_SANITIZE_ALLOWED_ATTRS",
    "HTML_SANITIZE_ALLOWED_TAGS",
    "IMAGE_UPLOAD_ALLOWED_MIME",
    "PERSONA_MAX_SELECTABLE",
    "PERSONA_PRIMARY_WEIGHT",
    "PERSONA_RANK_WEIGHTS",
    "PERSONA_SECONDARY_WEIGHT",
    "PERSONA_TERTIARY_WEIGHT",
    "SAFE_URL_SCHEMES",
    "VALID_CATEGORIES",
    "VALID_LOCALES",
    "VALID_SIGNALS",
    "VALID_THEME_PREFERENCES",
    "VALID_VIBES",
]

# Weight assigned to a persona by its rank (index) in the onboarding selection —
# index 0 (first pick) leads the feed, subsequent picks mix in at a lower weight.
PERSONA_RANK_WEIGHTS: tuple[float, ...] = (
    PERSONA_PRIMARY_WEIGHT,
    PERSONA_SECONDARY_WEIGHT,
    PERSONA_TERTIARY_WEIGHT,
)
# Guard: onboarding.py indexes PERSONA_RANK_WEIGHTS[i] for i up to PERSONA_MAX_SELECTABLE - 1.
# If persona_max_selectable is ever raised in shared/app-config.json without adding a
# matching weight here, that indexing would raise an uncaught IndexError instead of a
# clean validation error — fail fast at import time instead.
assert len(PERSONA_RANK_WEIGHTS) == PERSONA_MAX_SELECTABLE, (
    "PERSONA_RANK_WEIGHTS must have exactly PERSONA_MAX_SELECTABLE entries"
)

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

# Minimum SECRET_KEY length Settings will accept (OWASP audit F7) — 32 bytes
# is what `python -c "import secrets; print(secrets.token_hex(32))"` (the
# documented generation command) produces as a hex string. render.yaml's
# generateValue:true already clears this bar; the floor exists so a hand-set
# dev/self-hosted key can't start the app with something trivially guessable.
SECRET_KEY_MIN_LEN = 32
# The literal placeholder shipped in .env.example — rejected outright so a
# copy-paste-without-editing mistake fails at startup instead of signing
# every token with a value visible in the public repo.
SECRET_KEY_PLACEHOLDER_PREFIX = "change-me-"

# Hostnames treated as "local" by the dev/prod-DB startup sanity check
# (app/main.py's lifespan) — a DATABASE_URL host outside this set while
# APP_ENV=development suggests a misconfigured env var pointed at a real
# database, logged at ERROR rather than silently proceeding. "db" is the
# Postgres service name in .devcontainer/docker-compose.yml.
DEV_DB_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "db"})

# Paths exempt from HostCheckMiddleware's Host-header validation (app/main.py).
# Render's health probe reaches this process over the private network, so its
# Host header is the instance's rotating internal address, not BACKEND_URL's
# hostname — allowlisting it isn't viable since Starlette's allowed_hosts has
# no CIDR support. Only /health: /internal/tick arrives through the public
# proxy with a correct Host and stays guarded.
HOST_CHECK_EXEMPT_PATHS: frozenset[str] = frozenset({"/health"})

# Starlette TrustedHostMiddleware's fixed rejection body — app/main.py's
# HostCheckMiddleware matches this to tell an actual Host-header reject apart
# from an ordinary downstream 400 (bad token, malformed body, ...) passing
# through the same wrapped `send`. A future Starlette wording change would
# just silently stop logging rejects, never start false-logging normal 400s
# — an acceptable degrade.
TRUSTED_HOST_REJECT_BODY = b"Invalid host header"

# ASGI scope/message "type" values (app/main.py's raw ASGI middleware classes —
# HostCheckMiddleware, MaxBodySizeMiddleware, CsrfOriginCheckMiddleware). Fixed by
# the ASGI spec, not application data, but still named here rather than repeated
# as bare string literals in conditionals.
ASGI_SCOPE_TYPE_HTTP = "http"
ASGI_MESSAGE_TYPE_REQUEST = "http.request"
ASGI_MESSAGE_TYPE_RESPONSE_START = "http.response.start"
ASGI_MESSAGE_TYPE_RESPONSE_BODY = "http.response.body"

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400

# ingestion/http_client.py::host_guard_hook pins redirects to this port (in
# addition to hostname + scheme) — every ingestion source is fetched over
# https, so a redirect to a non-standard port on an otherwise-allowlisted
# host is rejected rather than silently followed (OWASP audit F14).
HTTPS_DEFAULT_PORT = 443

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
# TTL for resolves_to_private_ip()'s host->verdict cache (http_client.py). One
# ingest run fetches many events from the same 1-4 hostnames — each uncached
# call is a thread hand-off plus a real DNS round trip. Short enough that a
# DNS-rebinding attack against an allowlisted host is still caught well within
# one scheduled run's lifetime; the check was already documented as
# TOCTOU-racy against httpx's own re-resolution (see resolves_to_private_ip's
# docstring), so this doesn't weaken that existing trade-off.
DNS_RESOLVE_CACHE_TTL_SECONDS: float = 300.0

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

# Organizer-submission boundary allowlist (routers/organizer_events.py) — narrower
# than the shared ingestion allowlist above, and backend-only (not generated into
# shared/): it tracks the Tiptap toolbar's exact extension list (bold/italic/
# underline/bulletList/orderedList/link/heading 3-4/blockquote, no color/span), so
# the frontend never needs this set independently.
ORGANIZER_HTML_SANITIZE_ALLOWED_TAGS: frozenset[str] = frozenset(
    {"p", "br", "strong", "em", "u", "ul", "ol", "li", "a", "h3", "h4", "blockquote"}
)
ORGANIZER_HTML_SANITIZE_ALLOWED_ATTRS: dict[str, set[str]] = {"a": {"href"}}

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

EVENT_CANCELLATION_REASON_ORGANIZER_RETRACT = "organizer_retract"
EVENT_CANCELLATION_REASON_ADMIN_RETRACT = "admin_retract"
EVENT_CANCELLATION_REASON_REPORT_TAKEDOWN = "report_takedown"
VALID_EVENT_CANCELLATION_REASONS = frozenset(
    {
        EVENT_CANCELLATION_REASON_ORGANIZER_RETRACT,
        EVENT_CANCELLATION_REASON_ADMIN_RETRACT,
        EVENT_CANCELLATION_REASON_REPORT_TAKEDOWN,
    }
)

# Report-an-inappropriate-event feature (event_reports table).
REPORT_REASON_SPAM_OR_SCAM = "spam_or_scam"
REPORT_REASON_SEXUAL_OR_EXPLICIT = "sexual_or_explicit"
REPORT_REASON_NOT_AN_EVENT = "not_an_event"
REPORT_REASON_HATEFUL_OR_VIOLENT = "hateful_or_violent"
REPORT_REASON_MISLEADING_INFO = "misleading_info"
REPORT_REASON_EVENT_ENDED_OR_CANCELLED = "event_ended_or_cancelled"
REPORT_REASON_WRONG_LOCATION = "wrong_location"
REPORT_REASON_OTHER = "other"
VALID_REPORT_REASONS = frozenset(
    {
        REPORT_REASON_SPAM_OR_SCAM,
        REPORT_REASON_SEXUAL_OR_EXPLICIT,
        REPORT_REASON_NOT_AN_EVENT,
        REPORT_REASON_HATEFUL_OR_VIOLENT,
        REPORT_REASON_MISLEADING_INFO,
        REPORT_REASON_EVENT_ENDED_OR_CANCELLED,
        REPORT_REASON_WRONG_LOCATION,
        REPORT_REASON_OTHER,
    }
)
REPORT_STATUS_OPEN = "open"
REPORT_STATUS_RESOLVED = "resolved"
VALID_REPORT_STATUSES = frozenset({REPORT_STATUS_OPEN, REPORT_STATUS_RESOLVED})
REPORT_DETAIL_MAX_CHARS = 500

# Admin-authenticated but persisted to a Text column and emailed verbatim to
# every reporter (see app/email/report_reporter.py) — bounded so validation
# rejects an oversized note before it's stored/mailed rather than only being
# limited by the 10 MiB request-body ceiling (OWASP audit F16).
ADMIN_RESOLUTION_NOTE_MAX_CHARS = 2000

# System-generated resolution_note for the auto-resolve-on-cancellation cascade
# (utils.py::resolve_open_reports) — every path that cancels an event (admin
# retract, organizer retract, organizer self-delete, report takedown's own
# explicit note) reuses this so the reporter-outcome email (issue #127) has a
# consistent fallback message regardless of which door triggered it.
REPORT_AUTO_RESOLVE_NOTE = "auto-resolved: event cancelled"

# Admin report review-queue pagination (routers/admin.py GET /admin/reports) —
# mirrors ADMIN_REVIEW_QUEUE_PAGE_SIZE's sizing rationale.
ADMIN_REPORTS_QUEUE_PAGE_SIZE: int = 50
ADMIN_REPORTS_QUEUE_MAX_PAGE_SIZE: int = 500

# Event inspector (routers/admin.py GET /admin/events/{id}, issue #157) caps
# how many raw_events rows it inlines — unlike the paginated queues above,
# this is a fixed ceiling (not offset/limit query params) since it's one
# sub-list within a single-event payload, not its own listing endpoint. Each
# row carries a full verbatim JSONB payload, so this bounds response size
# for an event with a long refetch/dedup-merge history.
ADMIN_EVENT_INSPECTOR_RAW_EVENTS_LIMIT: int = 20

# Deduplication
DEDUP_LOOKBACK_DAYS = 30  # only re-cluster events that started within this window
# Upper bound on load_dedup_candidate_events — without it, an event scheduled
# arbitrarily far in the future is loaded as a full ORM object on every dedup
# pass (events rows are never deleted, so nothing else bounds this). Set well
# above any real event's lead time; a future event beyond this window simply
# isn't dedup-clustered until it comes within range on a later run.
DEDUP_LOOKAHEAD_DAYS = 400
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
# candidate_pair_ids_in_window()'s SQL pair count is roughly N x d (d = events
# sharing a +/-TIME_WINDOW_HOURS neighbourhood) — quadratic in same-window
# listing density rather than in the lookback/lookahead window. Not a hard cap
# (the pass still runs), just a visibility threshold: crossing it logs a
# warning so a density spike shows up instead of silently growing pass time.
DEDUP_CANDIDATE_PAIR_WARN_THRESHOLD = 20000
# Hard cap for the same query — worst case (many events sharing one starts_at)
# is quadratic in same-window listing density with no LIMIT, materializing
# every pair into Python. Deterministic ORDER BY means a truncated tail is
# picked up on the next pass as the head clusters collapse. Kept above the
# warn threshold so a warning always fires before truncation would.
DEDUP_CANDIDATE_PAIR_MAX = 50_000

# Resend email delivery
RESEND_SEND_URL = "https://api.resend.com/emails"
RESEND_TIMEOUT_SECONDS: float = 10.0
RESEND_ERROR_SNIPPET_LEN = 200
# Scheduler cadence (see CLAUDE.md Architecture for the full cron schedule)
ORGANIZER_SYNC_HOUR = 3  # weekly Sunday 03:00 Europe/Tallinn
ORGANIZER_SYNC_MINUTE = 0
CLEANUP_HOUR = 3  # weekly Sunday 03:30 Europe/Tallinn, after organizer sync
CLEANUP_MINUTE = 30
INGEST_INTERVAL_HOURS = 1
LLM_PASS_INTERVAL_HOURS = 6  # dedup/classify/publish/geocode
REFETCH_HOUR = 4  # daily 04:30 Europe/Tallinn, before the 06:00 feed build
REFETCH_MINUTE = 30
FEED_BUILD_HOUR = 6  # daily 06:00 Europe/Tallinn
FEED_BUILD_MINUTE = 0
# Users per page in build_daily_feeds (score.py) — bounds the per-page
# personas_by_user/fb_by_user/score_cache dicts and the event_rows x users
# scoring loop in RAM regardless of total registered-user count.
FEED_BUILD_USER_BATCH_SIZE = 500

# Email i18n strings (subjects, labels, templates) live in shared/i18n/*.json.
DIGEST_SEND_HOUR = 7  # 07:00 Europe/Tallinn, one hour after build_daily_feeds
DIGEST_MAX_WHY_GO_BULLETS = 3
# Concurrency cap when fanning out digest sends — bounded by Resend free-tier
# rate (10 req/s). Eight in-flight sends leaves headroom for occasional retries.
DIGEST_SEND_CONCURRENCY: int = 8
# send_daily_digests per-user outcome sentinels.
DIGEST_RESULT_SENT = "sent"
DIGEST_RESULT_SKIPPED = "skipped"

# Admin endpoint pagination
ADMIN_DEDUP_GROUPS_PAGE_SIZE: int = 50
ADMIN_DEDUP_GROUPS_MAX_PAGE_SIZE: int = 500

# Per-IP rate limits (slowapi / limits syntax: "<count>/<period>"). These guard
# auth + webhook endpoints against enumeration, quota-exhaustion, and email-bombing
# attacks that the per-email cooldown (request-link) doesn't cover — see main.py::limiter.
RATE_LIMIT_AUTH_REQUEST_LINK = "10/minute"
RATE_LIMIT_AUTH_VERIFY = "30/minute"
RATE_LIMIT_WEBHOOK_INBOUND_MAIL = "60/minute"
# Public digest unsubscribe/resubscribe (routers/unsubscribe.py) — no auth, token-verified.
RATE_LIMIT_UNSUBSCRIBE = "30/minute"
# Public contact form (routers/contact.py) — no auth; tight cap since each hit sends an email.
RATE_LIMIT_CONTACT = "3/minute"
# Organizer event submission/edit/image-upload (routers/organizer_events.py) —
# modeled on RATE_LIMIT_CONTACT: authenticated, but each hit runs a full
# inline classify+publish pass, so keep it tight per-IP; the DB-backed
# ORGANIZER_DAILY_SUBMISSION_CAP is the per-organizer ceiling.
RATE_LIMIT_SUBMIT = "10/minute"
# Authenticated organizer contact form (routers/organizer_contact.py) —
# modeled on RATE_LIMIT_CONTACT: session-gated, but each hit still sends an
# email, so keep the same tight per-IP cap.
RATE_LIMIT_ORGANIZER_CONTACT = "3/minute"

# Resend inbound-mail webhook signature verification (Svix scheme; see
# https://resend.com/docs/dashboard/webhooks/verify-webhooks-requests and
# https://docs.svix.com/receiving/verifying-payloads/how-manual). Verifying
# over the raw body via these headers replaces the old ?secret= query-string
# check, which leaked the shared secret into proxy/access logs.
SVIX_ID_HEADER = "svix-id"
SVIX_TIMESTAMP_HEADER = "svix-timestamp"
SVIX_SIGNATURE_HEADER = "svix-signature"
SVIX_SECRET_PREFIX = "whsec_"
# Bearer-token auth headers used by outbound email/LLM API clients.
AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer "
# BeautifulSoup's built-in parser name — used everywhere we parse scraped/stored HTML.
HTML_PARSER = "html.parser"
# Reject a signature whose svix-timestamp is further than this from "now" (either
# direction), blocking replay of an old, legitimately-signed request. Matches
# Svix's own recommended default tolerance.
WEBHOOK_TIMESTAMP_TOLERANCE_SECONDS = 300
# Public read endpoint — generous enough for normal browsing while throttling
# ID-enumeration / scraping abuse (GET /events/{id} takes no auth).
RATE_LIMIT_EVENTS_DETAIL = "120/minute"
# Admin Basic-auth surface — applied via limiter.shared_limit(..., scope="admin")
# so every /admin/* route shares ONE bucket per client, not one bucket each
# (a per-route @limiter.limit would let an attacker cycling all admin routes
# attempt far more than this per minute). Pair with a strong ADMIN_PASSWORD.
RATE_LIMIT_ADMIN = "10/minute"
# Consecutive-failure lockout on top of RATE_LIMIT_ADMIN (routers/admin.py::
# _require_admin) — a static username/password pair has no other brute-force
# damper. In-memory (single Render process, no Redis — matches the rest of
# this codebase's "no Celery/Redis" design), so it resets on deploy/restart;
# accepted since this pairs with, not replaces, a strong ADMIN_PASSWORD.
ADMIN_AUTH_MAX_FAILURES = 5
ADMIN_AUTH_LOCKOUT_SECONDS = 300
# Bounds _admin_auth_failures (routers/admin.py) the same way browse.py bounds
# _score_cache — an unbounded dict keyed by client_key() would grow forever
# under sustained scanning/brute-force traffic.
ADMIN_AUTH_FAILURES_MAX_ENTRIES = 4096
# Authenticated feedback writes — generous cap; prevents cache-rebuild DoS
# (every signal wipes all user_event_scores rows for that user).
RATE_LIMIT_FEEDBACK = "60/minute"
# POST /reports — content-moderation write, tighter than RATE_LIMIT_FEEDBACK
# since it creates a row an admin must triage (see LOG_EVENT_REPORT_SUBMITTED).
RATE_LIMIT_REPORT = "10/minute"
# Authenticated state-changing writes (onboarding persona, settings GET/PATCH) —
# damps self-inflicted DB write spam from a valid session token.
RATE_LIMIT_AUTHENTICATED_WRITE = "30/minute"
# Tighter cap for logout-all: bumps session_token_version, revoking every
# issued session token (including the caller's own) — a higher-value target
# than ordinary writes.
RATE_LIMIT_LOGOUT_ALL = "10/minute"
# Plain "sign out" (clears only the caller's own cookie, no session_token_version
# bump) — lower stakes than logout-all, so a more generous cap; shared by both
# the consumer and organizer logout endpoints, mirroring RATE_LIMIT_LOGOUT_ALL.
RATE_LIMIT_LOGOUT = "20/minute"
# POST /admin/auth/login — a password+TOTP brute-force surface distinct from
# RATE_LIMIT_ADMIN (which only gates already-authenticated /admin/* routes);
# ADMIN_AUTH_MAX_FAILURES lockout is the consecutive-failure damper on top.
RATE_LIMIT_ADMIN_LOGIN = "10/minute"
# Authenticated /explore browsing — mirrors RATE_LIMIT_EVENTS_DETAIL; live filter
# changes can fire a request per keystroke/chip-toggle, so this stays generous.
RATE_LIMIT_BROWSE = "120/minute"
# Public, unauthenticated landing-page showcase (GET /public/showcase). No auth,
# so throttle scraping abuse; generous enough for real visitors loading the page.
RATE_LIMIT_PUBLIC = "60/minute"
# /internal/tick (cron-job.org keepalive ping, app/main.py) hits 6x/hour by design;
# generous ceiling exists only to bound token brute-force / abuse, not real traffic.
RATE_LIMIT_INTERNAL_TICK = "30/minute"
# How many events the landing-page showcase returns — a fixed, small teaser grid
# (top-quality upcoming events), so no pagination is needed.
SHOWCASE_EVENT_COUNT = 6
# The landing showcase promises "what's on right now" — bound candidates to the
# coming week. If a thin week yields fewer than SHOWCASE_EVENT_COUNT events, the
# endpoint retries once at the wider window rather than rendering a stub grid.
SHOWCASE_WINDOW_DAYS = 7
SHOWCASE_FALLBACK_WINDOW_DAYS = 30
# GET /public/counts (wayfinder #188/#189) — hand-rolled process-local TTL cache,
# no new dependency (single-process/no-Redis architecture). Sized for real
# visitor traffic: Landing client-fetches this live via React Query on every
# real visit, not just at prerender-build time.
PUBLIC_COUNTS_CACHE_TTL_SECONDS = 900
# Same "this week, fall back if thin" pattern as the showcase grid — a real
# empty-tonight is a valid, non-error state, so the ticker widens rather than
# rendering nothing.
PUBLIC_COUNTS_TONIGHT_CAP = 20
PUBLIC_COUNTS_FALLBACK_WINDOW_DAYS = 7

# Auth tokens
AUTH_MAGIC_SALT = "magic-link-v1"
AUTH_SESSION_SALT = "session-v1"
# Session-cookie transport (issue #26 / docs/adr/0001). Path scoping is what
# keeps the higher-value organizer credential off ordinary consumer requests —
# both paths sit under the Vercel `/api` rewrite that makes the SPA same-origin
# with this API, so a browser only ever attaches SESSION_COOKIE_NAME under
# /api and ORGANIZER_SESSION_COOKIE_NAME under /api/organizer.
SESSION_COOKIE_NAME = "session"
SESSION_COOKIE_PATH = "/api"
ORGANIZER_SESSION_COOKIE_NAME = "organizer_session"
ORGANIZER_SESSION_COOKIE_PATH = "/api/organizer"
# Shared by routers/utils.py::set_session_cookie/clear_session_cookie — a single
# source of truth so the two functions can never drift apart (clear_session_cookie
# only actually clears the cookie in the browser if every attribute here matches
# what set_session_cookie used to set it).
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE: Literal["strict"] = "strict"
# Fallback "v" claim for session/organizer-session tokens minted before that
# claim existed (auth/tokens.py) — mirrors the session_token_version column's
# server_default/model default.
DEFAULT_SESSION_TOKEN_VERSION = 1
AUTH_UNSUBSCRIBE_SALT = "unsubscribe-v1"
# Organizer auth — distinct salts from the user stack above so a user's magic-link
# or session token can never verify as an organizer token (and vice versa), even
# though both use the same URLSafeTimedSerializer(settings.SECRET_KEY).
AUTH_ORGANIZER_MAGIC_SALT = "organizer-magic-v1"
AUTH_ORGANIZER_SESSION_SALT = "organizer-session-v1"
# Organizer TTLs mirror the user-facing defaults (no separate settings override —
# organizers are not expected to need a different cadence than consumers).
ORGANIZER_MAGIC_LINK_TTL_MINUTES = _MAGIC_LINK_TTL_MINUTES_SHARED
ORGANIZER_SESSION_TTL_DAYS = _SESSION_TTL_DAYS_SHARED

# Admin console auth (issue #154) — third auth track alongside the consumer and
# organizer ones above. No magic link (password + TOTP instead) and no admins
# table (a session just asserts "a valid login happened", nothing per-admin —
# see routers/admin_auth.py), so this token carries no id/version claim, only a
# distinct salt so it can never verify as a user/organizer token or vice versa.
AUTH_ADMIN_SESSION_SALT = "admin-session-v1"
ADMIN_SESSION_COOKIE_NAME = "admin_session"
# Scoped under /api/admin like the organizer cookie is scoped under
# /api/organizer — an admin route added outside /admin/* would silently 401.
ADMIN_SESSION_COOKIE_PATH = "/api/admin"
# 12h, shorter than the 2-day consumer/organizer TTL — a higher-value credential
# with no revocation mechanism beyond expiry (see docs/adr/0001).
ADMIN_SESSION_TTL_SECONDS = 12 * 60 * 60
# One 30s step of drift tolerance either side of "now" (pyotp's valid_window is a
# count of steps, not seconds; app/auth/totp.py) — accounts for clock skew between
# the admin's authenticator app and this server without materially widening the
# guess window.
ADMIN_TOTP_VALID_WINDOW = 1
# Per-organizer daily submission ceiling (routers/organizer_events.py), computed
# from Tallinn calendar-day start — an IP rate limit alone can't cap a single
# organizer account across multiple IPs.
ORGANIZER_DAILY_SUBMISSION_CAP = 20
# Same count-then-act soft ceiling as ORGANIZER_DAILY_SUBMISSION_CAP, but for
# POST /organizer/events/image — submissions alone don't bound Cloudinary
# free-tier upload quota, since an upload can happen without ever completing
# a submission (organizer_image_uploads, app/models/models.py).
ORGANIZER_DAILY_IMAGE_UPLOAD_CAP = 20
# Same count-then-act soft ceiling, but for POST /organizer/venues — venues
# are created independently of a submission, so neither existing cap bounds
# them (routers/organizer_venues.py).
ORGANIZER_DAILY_VENUE_CREATION_CAP = 20

# Field length caps for SubmitEventBody/PatchEventBody (routers/organizer_events.py).
# venue_name and currency mirror the Event column widths (models/models.py) so an
# over-length value 422s instead of raising asyncpg.StringDataRightTruncation; the
# Text-column fields (title/description/important_info) have no DB-enforced width,
# so these are abuse-prevention ceilings, not truncation-avoidance.
ORGANIZER_TITLE_MAX_LEN = 300
ORGANIZER_DESCRIPTION_MAX_LEN = 30000
ORGANIZER_IMPORTANT_INFO_MAX_LEN = 15000
ORGANIZER_VENUE_NAME_MAX_LEN = 255
ORGANIZER_VENUE_ADDRESS_MAX_LEN = 500
ORGANIZER_CURRENCY_MAX_LEN = 3
# Organizer.name (routers/organizer_profile.py, #175) — mirrors the Organizer
# column width (models/models.py).
ORGANIZER_NAME_MAX_LEN = 255

# Organizer image upload (routers/organizer_events.py -> Cloudinary signed upload).
# IMAGE_UPLOAD_ALLOWED_MIME itself comes from shared/app-config.json (imported
# above) — mirrors the frontend's ORGANIZER_IMAGE_ALLOWED_MIME so both stacks
# stay in sync via the generator instead of two hand-maintained literals.
IMAGE_UPLOAD_MAX_BYTES = 8 * 1024 * 1024  # 8 MiB
CLOUDINARY_UPLOAD_URL_TEMPLATE = (
    "https://api.cloudinary.com/v1_1/{cloud_name}/image/upload"
)
# Leading-byte signatures for the three formats IMAGE_UPLOAD_ALLOWED_MIME
# allows. WebP needs its own check (organizer_events.py::_sniff_image_mime)
# since RIFF is a generic container format — the fourCC at offset 8 is what
# actually says "WEBP".
IMAGE_MAGIC_BYTES: dict[bytes, str] = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG\r\n\x1a\n": "image/png",
}
IMAGE_EXTENSION_BY_MIME: dict[str, str] = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
}
# Hosts an organizer-submission event.image_url is allowed to point at — the
# signed Cloudinary upload endpoint (POST /organizer/events/image) always
# returns a res.cloudinary.com secure_url. Without this, an organizer could
# set image_url to an arbitrary https host; the digest embeds it as an <img>,
# turning it into a tracking pixel that leaks each recipient's IP/open-time to
# a third party the recipient never consented to. Scraped (non-organizer)
# sources are unaffected — this only gates SOURCE_KIND_USER_SUBMISSION.
ALLOWED_IMAGE_HOSTS = frozenset({"res.cloudinary.com"})

# Whole-request body ceiling (app.main.MaxBodySizeMiddleware) — above
# IMAGE_UPLOAD_MAX_BYTES (the largest legitimate body today) since multipart
# form overhead adds a little on top of the raw file. Nothing else in the
# stack caps request size: Starlette receives and spools the full body before
# any handler-level check (e.g. IMAGE_UPLOAD_MAX_BYTES) ever runs.
MAX_REQUEST_BODY_BYTES = 10 * 1024 * 1024  # 10 MiB

# Namespace prefix for organizer-submitted events' synthetic external_id
# (routers/organizer_events.py) — distinguishes user-submission rows from any
# other source's external ids in event_sources.
ORGANIZER_SUBMISSION_EXTERNAL_ID_PREFIX = "org:"

# Named locale codes for the fixed et/en/ru vocabulary (VALID_LOCALES above) —
# used where code refers to one specific locale rather than iterating the set.
LOCALE_ET = "et"
LOCALE_EN = "en"
LOCALE_RU = "ru"

# Server-side theme_preference column values (users/organizers) — mirrors
# VALID_LOCALES. The tri-state UI value "system" is never sent to or stored
# on this column; only "light"/"dark"/NULL are valid here.
VALID_THEME_PREFERENCES = {"light", "dark"}

# The one theme_preference value that keeps an email's dark styling unchanged —
# every other value (including None/"system") selects the light style set.
# See app/email/styles.py::get_email_styles.
THEME_PREFERENCE_DARK = "dark"

# Admin review-queue pagination (routers/admin.py GET /admin/submissions) — mirrors
# ADMIN_DEDUP_GROUPS_PAGE_SIZE's sizing rationale (small default page, generous cap).
ADMIN_REVIEW_QUEUE_PAGE_SIZE: int = 50
ADMIN_REVIEW_QUEUE_MAX_PAGE_SIZE: int = 500

# Per-email magic-link resend cooldown (routers/auth.py::_recent_unused_link_exists) —
# prevents Resend quota exhaustion from rapid repeat requests for the same address.
MAGIC_LINK_RESEND_COOLDOWN_SECONDS = 120

# One-click digest unsubscribe (routers/unsubscribe.py). A long TTL so a link in an
# old, unread inbox email still works; the endpoint is reversible (Undo/resubscribe)
# so a stale click carries low risk.
UNSUBSCRIBE_TOKEN_TTL_DAYS = 365

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
# Anonymous /explore scoring (#234): feedback_signal (0.20) is dropped — no
# event-level aggregate feedback signal exists anywhere in the codebase.
# persona_affinity keeps SCORE_WEIGHT_AFFINITY unchanged (it already returns
# NEUTRAL_SCORE with no persona). The freed 0.20 is redistributed by uniformly
# scaling the three remaining differentiating terms by 1/0.80 — a pure
# rescale that preserves their relative influence.
SCORE_WEIGHT_ANON_RECENCY: float = 0.25
SCORE_WEIGHT_ANON_QUALITY: float = 0.125
SCORE_WEIGHT_ANON_LOCALITY: float = 0.0625
# _time_slots_for_event() memoization cap (ranking/score.py) — bounds an lru_cache keyed
# on distinct starts_at values so repeated calls across users scoring the same event
# don't redo the astimezone conversion. Comfortably above the number of distinct
# starts_at values in one DAILY_5_LOOKAHEAD_DAYS candidate window.
TIME_SLOTS_CACHE_MAXSIZE = 4096

# Chunk size for the bulk pg_insert(...).on_conflict_do_update(...) upserts in
# build_daily_feeds (_persist_new_scores / _persist_daily_feeds). The Postgres
# wire protocol caps bind parameters at 32767 (int16); with 4 params/row and a
# realistic ~30 users x ~300 candidate events, a single unchunked statement can
# exceed that limit and raise at execute time. 1000 rows/chunk stays comfortably
# under the limit at either table's column count and mirrors the chunking
# already used for the LLM dedup hash IN-list (LLM_DEDUP_HASH_QUERY_CHUNK_SIZE).
SCORE_INSERT_CHUNK_SIZE = 1000

# GET /explore (app/routers/browse.py) — event discovery / search page.
# BROWSE_PAGE_SIZE itself is cross-stack (shared/app-config.json), imported above.
BROWSE_MAX_PAGE_SIZE: int = 60
# ?q= keyword search — _keyword_filter builds a %...% pattern against two
# trigram GIN indexes; an unbounded string is cheap to send and expensive to
# scan, and RATE_LIMIT_BROWSE alone doesn't bound the per-request cost.
BROWSE_QUERY_MAX_LEN: int = 200

# Shared pagination validation floors — every `limit`/`offset` Query() across
# admin.py/browse.py/feedback.py enforces the same lower bound; centralized so
# it can't drift per-endpoint.
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MIN_OFFSET: int = 0
# Ceiling on `offset` across every paginated list endpoint (browse.py, feedback.py,
# admin.py, organizer_events.py) — `ge=` alone leaves offset unbounded, so an
# offset like 5_000_000 makes Postgres walk and discard that many rows on every
# request at the endpoint's full rate limit. Every consumer is infinite scroll
# from offset=0 at BROWSE_PAGE_SIZE-ish increments, so 5_000 already covers far
# more depth than any legitimate session reaches while still bounding the
# LIMIT/OFFSET seq-scan-and-discard cost an authenticated caller can force.
PAGINATION_MAX_OFFSET: int = 5_000
# Candidate cap for the Python-scored path (Path B: for_you=True OR sort=relevance —
# so also date/price/quality sort *under* for_you=True, not just relevance). Sorted
# soonest-first before capping, so the cap policy is a deliberate soonest-bias, not
# an arbitrary truncation: a date sort still yields globally-correct soonest-first
# results, but price/quality sort under for_you=True is only a true sort within the
# soonest BROWSE_RELEVANCE_MAX_CANDIDATES matches, not a global one — an accepted
# Path-B approximation at MVP scale (`total` in the response reflects at most this
# many rows when the cap is hit; see browse.py docstring).
BROWSE_RELEVANCE_MAX_CANDIDATES: int = 300
# _browse_scored_path scores+sorts the full (capped) candidate pool on every
# call, then slices a page — so /explore's "Load more" infinite scroll pays
# O(candidates) again per page even though the ranked order didn't change.
# Memoizing the scored-and-sorted id list keyed by (user, filters, sort) turns
# an N-page read into one scoring pass. Short TTL bounds staleness (a like/
# dislike made mid-scroll takes up to this long to affect ranking); small
# max-entries bounds process memory — single Render process, no cross-process
# cache needed.
BROWSE_SCORE_CACHE_TTL_SECONDS: float = 30.0
BROWSE_SCORE_CACHE_MAX_ENTRIES: int = 512
# Fixed sentinel in place of a real user id for the anonymous-caller cache key
# (#234) — anonymous /explore traffic shares one cache entry per filter/sort
# combination rather than one per caller. Never collides with a real User.id
# (Postgres serial PKs start at 1).
BROWSE_ANON_CACHE_SENTINEL: int = 0
# How far back browse.py::_load_feedback_context looks for a user's like/dislike
# history when scoring /explore (Path B). user_event_feedback is preserved
# indefinitely by policy (see CLAUDE.md Data Retention), so an unbounded load
# grows with the user's lifetime activity on every /explore request. The
# FEEDBACK_DECAY_BASE (0.9) decay makes a signal this old numerically
# negligible (0.9^90 ~= 0.0000265) to score_event() anyway, so the cutoff drops
# no meaningfully-weighted signal.
FEEDBACK_HISTORY_LOOKBACK_DAYS = 90

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

# Ceiling applied to the LLM's quality_score for organizer-submitted events
# only (Event.submitted_by_organizer_id is not None), before it's persisted.
# Unlike is_explicit/is_non_event, quality_score has no deterministic keyword
# floor. PUBLISH_MIN_QUALITY_SCORE (0.4) is a low bar most real events already
# clear, so this ceiling isn't primarily a publish-gate defense — the actual
# steerable prize is ranking prominence: quality_score feeds the persona
# ranking formula (10% weight) and orders the public showcase/Explore
# `quality_score DESC`, so an organizer who controls the event text could
# otherwise push the model toward quality:1.0 to get outsized visibility
# regardless of the event's real quality. Capping below 1.0 bounds that
# upside while leaving normal submissions unaffected (OWASP audit F13).
ORGANIZER_SUBMISSION_QUALITY_SCORE_CEILING: float = 0.7

# Publish gate's reject-breakdown diagnostic only looks back this many days
# (by starts_at) — it answers "why did recent work get rejected", not an
# all-time audit total, so it doesn't pay the cost of scanning every
# permanently-failing event ever classified.
PUBLISH_DIAGNOSTICS_WINDOW_DAYS: int = 30

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
# Signals that actually feed ranking/score.py's like/dislike-based scoring
# (both ranking/score.py::_load_feedback_context-equivalent loads and
# browse.py::_load_feedback_context filter on signal IN (like, dislike)).
# bookmark is never read by the scorer and click_external/view are passive
# analytics — invalidating the score cache on those wastes the entire cache
# (every ticket click or bookmark otherwise wiped a user's cached scores,
# forcing build_daily_feeds to recompute from scratch). Only these two signals
# should trigger invalidate_user_scores; see feedback.py::record_feedback/
# delete_feedback.
SCORE_AFFECTING_SIGNALS: frozenset[str] = frozenset({SIGNAL_LIKE, SIGNAL_DISLIKE})
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

# Contact form (routers/contact.py)
CONTACT_NAME_MAX_LEN = 100
CONTACT_MESSAGE_MAX_LEN = 2000
CONTACT_FIELD_MIN_LEN = 1
# Always returned on success, even when the honeypot is tripped — a bot must
# get no signal that it was caught.
CONTACT_SUCCESS_DETAIL = "Message sent."


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
# Adapter-less source for direct organizer submission (routers/organizer_events.py) —
# no fetch_raw/normalize, so it carries no ADAPTER_REGISTRY entry (see registry.py)
# and ingest_all_enabled skips it, same as the newsletter source above.
SOURCE_SLUG_USER_SUBMISSION = "user_submission"

# Source kinds
SOURCE_KIND_API = "api"
SOURCE_KIND_HTML_SCRAPE = "html_scrape"
SOURCE_KIND_INBOUND_EMAIL = "inbound_email"
SOURCE_KIND_USER_SUBMISSION = "user_submission"

HTML_LISTING_MAX_DETAIL_FETCHES = (
    300  # cap per ingestion run on capped-detail sources (piletilevi) — headroom
    # above observed 206-220 new-card runs, which truncated detail fetches at 200
)

# Geocoding (Nominatim) — used to backfill lat/lng for events that have an address
# but no coordinates (currently: Fienta). Usage policy requires a descriptive
# User-Agent with contact info and a max of 1 request/second.
NOMINATIM_BASE_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = "EventRadarBot/1.0 (+https://eventradar.ee; aleksei.lutkov@gmail.com)"
# Static Nominatim search params; the "q" param is set per-call with the address.
NOMINATIM_QUERY_PARAMS: dict[str, str | int] = {"format": "json", "limit": 1}
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
# How far back a donor event can be and still seed the geocode cache / sibling
# copy pass. events rows are never deleted (see CLAUDE.md retention policy), so
# without this bound both donor queries would scan every event ever ingested,
# growing without limit. Venue coordinates don't change, so this trades a small
# amount of donor coverage (a venue whose only past event is older than this
# window won't donate until it recurs) for a bounded query.
GEOCODE_DONOR_LOOKBACK_DAYS = 180
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
# Wall-clock backstop, independent of REFETCH_MAX_PER_RUN: an event that
# triggers locale-variant fetches (fetch_locale_variants) pays its own
# REFETCH_REQUEST_DELAY_SECONDS per variant, so REFETCH_MAX_PER_RUN events
# don't bound run time the way the count alone suggests. Job starts 04:30,
# build_daily_feeds runs 06:00 — 40 min leaves real margin in that window.
# detail_refetched_at ordering means anything cut off here is picked up first
# next run, so this is self-limiting with no coverage loss.
REFETCH_MAX_RUN_SECONDS: float = 2400.0
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
# Lower bound on existing_external_ids' EventSource->Event join. Without it,
# every external_id ever stored for a source is loaded into a Python set on
# every hourly ingest run, growing monotonically since events rows are never
# deleted. A source's live listing never re-surfaces an external_id belonging
# to an event that started this long ago, so dropping it from the skip set
# costs nothing beyond the event_sources unique index + IntegrityError handler
# already guarding against a duplicate insert (see insert_normalized_event).
INGEST_SKIP_ID_LOOKBACK_DAYS = 180
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
# Fienta price_from_string free-tier tokens (see parse_price_from_string's grammar).
PRICE_FROM_STRING_FREE_TOKEN = "free"
PRICE_FROM_STRING_FREE_SUFFIX = ", free"

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
# frontend/src/api/client.ts and routers/*.py route decorators). allow_credentials
# stays False regardless (see main.py's CORSMiddleware call site) — the session
# cookie only ever travels same-origin through the Vercel `/api` rewrite, never
# via a credentialed cross-origin request.
CORS_ALLOWED_METHODS: list[str] = ["GET", "POST", "PATCH", "DELETE"]
CORS_ALLOWED_HEADERS: list[str] = ["Authorization", "Content-Type"]

# Single source for the dev-only origins in both config.CORS_ORIGINS' literal
# default and main.py's non-development CSRF-trust subtraction — the two must
# never drift, or a value dropped from one but not the other either breaks
# local dev or leaves a hardcoded localhost origin CSRF-trusted in production.
DEV_CORS_ORIGINS_DEFAULT: frozenset[str] = frozenset(
    {"http://localhost:5173", "http://localhost:4173"}
)

# CSRF — methods CsrfOriginCheckMiddleware (app/main.py) enforces the Origin
# check against. Deliberately includes PUT even though the API never routes
# it today (CORS_ALLOWED_METHODS above omits it) — this is a defense-in-depth
# check ahead of #24's cookie migration, not a mirror of what's currently wired up.
CSRF_UNSAFE_METHODS: frozenset[str] = frozenset({"POST", "PATCH", "DELETE", "PUT"})

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
SQLALCHEMY_ENGINE_LOGGER_NAME = "sqlalchemy.engine"
LOG_FRAMEWORK_LOGGER_NAMES: tuple[str, ...] = (
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    SQLALCHEMY_ENGINE_LOGGER_NAME,
)
# HTTP client loggers pinned to WARNING: their per-request INFO/DEBUG lines are
# noise, and — critically — shipping one would make the ship POST itself emit a
# log that gets shipped, a self-amplifying loop. WARNING severs it at any root level.
LOG_QUIET_LOGGER_NAMES: tuple[str, ...] = ("httpx", "httpcore")
# uvicorn.access paths never worth shipping to the log drain. Render's platform
# health check hits GET /health every few seconds; shipping each is pure noise.
# Suppressed on the shipping QueueHandler only — these lines still reach Render's
# own console logs. Extend this set to silence other high-frequency probe paths.
LOG_SHIP_SUPPRESS_ACCESS_PATHS: frozenset[str] = frozenset({"/health"})
# Standard LogRecord attribute names. JsonLogFormatter promotes every record
# attribute NOT in this set — i.e. anything a call site passed via `extra={...}` —
# to a top-level JSON key, so Axiom monitors can filter on structured fields
# (event/job/status/duration_ms) instead of regex-parsing the free-text message.
# Derived from a sample record so it tracks the running Python version (3.12 adds
# taskName); "message"/"asctime" are set during formatting, not on a fresh record.
LOG_RECORD_RESERVED_ATTRS: frozenset[str] = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime", "color_message"}
# "color_message" is uvicorn's own `extra=` on its startup/shutdown lines — kept
# reserved so it doesn't leak into the curated shipped schema (docs/observability.md).

# Structured log `event` field values (shipped as a first-class JSON key via
# `extra={"event": ...}`) — each keys an Axiom monitor. See docs/observability.md.
LOG_EVENT_JOB_RUN = "job_run"  # scheduled-job completion/failure telemetry
LOG_EVENT_RATE_LIMIT_BLOCK = "rate_limit_block"  # own per-IP 429 rejection
LOG_EVENT_LLM_DEGRADED = "llm_degraded"  # provider chain exhausted / backlog deferred
LOG_EVENT_AUTH_FAILED = "auth_failed"  # magic-link / admin / internal-tick auth reject
LOG_EVENT_WEBHOOK_REJECTED = "webhook_rejected"  # inbound-mail signature / body reject
LOG_EVENT_EMAIL_SEND_FAILED = "email_send_failed"  # Resend magic-link / digest failure
LOG_EVENT_CONTACT_HONEYPOT = "contact_honeypot_block"  # contact-form honeypot field tripped
LOG_EVENT_HOST_REJECTED = "host_rejected"  # HostCheckMiddleware Host-header reject
LOG_EVENT_REPORT_SUBMITTED = "report_submitted"  # POST /reports success
LOG_EVENT_ADMIN_ACTION = "admin_action"  # /admin/auth/* login/logout (issue #154)
# Global (not per-IP) daily unverified-account-creation budget crossed — see
# routers/utils.py::record_unverified_account_creation (OWASP audit F10).
LOG_EVENT_UNVERIFIED_ACCOUNT_BUDGET_EXCEEDED = "unverified_account_budget_exceeded"

# Daily cap (process-wide, not per-IP) on new unverified User/Organizer rows
# created via the magic-link request endpoints before an operator alert fires
# — an early signal ahead of Resend's own sender-reputation/quota controls
# (OWASP audit F10). Well above realistic organic signup volume for this
# single-city MVP; tune from real data once there's a baseline.
UNVERIFIED_ACCOUNT_DAILY_BUDGET = 200
# `action` field values for LOG_EVENT_ADMIN_ACTION (issue #155).
ADMIN_ACTION_RESOLVE_REPORTS = "resolve_reports"
ADMIN_ACTION_TAKEDOWN_REPORTED_EVENT = "takedown_reported_event"
ADMIN_ACTION_APPROVE_SUBMISSION = "approve_submission"
ADMIN_ACTION_RETRACT_SUBMISSION = "retract_submission"
# `action` field values for the /admin/pipeline job triggers (issue #159).
ADMIN_ACTION_INGEST = "ingest"
ADMIN_ACTION_INGEST_SOURCE = "ingest_source"
ADMIN_ACTION_DEDUP = "dedup"
ADMIN_ACTION_CLASSIFY = "classify"
ADMIN_ACTION_PUBLISH = "publish"
ADMIN_ACTION_GEOCODE = "geocode"
ADMIN_ACTION_REFETCH = "refetch"
ADMIN_ACTION_SYNC_ORGANIZERS = "sync_organizers"
ADMIN_ACTION_CLEANUP = "cleanup"
ADMIN_ACTION_BUILD_FEEDS = "build_feeds"
ADMIN_ACTION_SEND_DIGESTS = "send_digests"
ADMIN_ACTION_PIPELINE_RUN = "pipeline_run"
# `status` field values for LOG_EVENT_JOB_RUN.
LOG_STATUS_OK = "ok"
LOG_STATUS_ERROR = "error"

# Security response headers — applied to every response by SecurityHeadersMiddleware
# (app.main). This is a pure JSON API with no first-party HTML/script surface, so the
# CSP can be maximally restrictive; frame-ancestors/X-Frame-Options block clickjacking.
SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # Pure JSON API, nothing should ever be cached by an intermediary — most
    # importantly, POST /auth/verify sets the session cookie via Set-Cookie.
    "Cache-Control": "no-store",
    # Denies browser-feature access outright rather than leaving it at
    # browser defaults — this API never needs camera/mic/geolocation/payment,
    # and interest-cohort opts out of FLoC-style tracking.
    "Permissions-Policy": (
        "camera=(), microphone=(), geolocation=(), payment=(), interest-cohort=()"
    ),
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
# Unverified users/organizers — a row inserted on an unauthenticated
# POST .../request-link before the address is proven reachable (see CLAUDE.md
# Auth → Email verification gate). Retained this long in case a slow/late
# click on a still-valid link would otherwise orphan it, then pruned so an
# address nobody ever proved they own isn't retained indefinitely.
UNVERIFIED_ACCOUNT_RETENTION_DAYS = 30

# HTTP verbs used as literal method tags outside the httpx client calls
# themselves (e.g. ListingRequest.method) — the retrying http_get/http_post
# wrappers already encode the verb in their function name.
HTTP_METHOD_GET = "GET"
HTTP_METHOD_POST = "POST"

# Magic-link verify path defaults — app/auth/email.py::send_magic_link's
# verify_path parameter, and organizer_auth.py's override of it.
AUTH_VERIFY_PATH = "/auth/verify"
ORGANIZER_AUTH_VERIFY_PATH = "/organizer/verify"

# app/routers/utils.py::mask_db_url — redacts the password in a DB URL
# ("user:pass@host" -> "user:***@host") for safe logging.
MASK_DB_URL_PASSWORD_RE = r":[^@/]+@"

# app/ingestion/adapter.py::_make_slug — collapses any non a-z0-9 run to "-".
SLUG_SANITIZE_RE = r"[^a-z0-9]+"

# app/ingestion/content_filters.py::is_explicit_text — collapses whitespace
# runs (incl. literal newlines within a text node) before keyword matching,
# so a multi-word keyword still matches across them.
CONTENT_FILTER_WHITESPACE_COLLAPSE_RE = r"\s+"

# app/ingestion/sanitize.py — HTML post-processing regexes.
# _MULTI_BR_RE: collapses a run of more than HTML_SANITIZE_MAX_CONSECUTIVE_BR
# <br> tags; %d is filled in with HTML_SANITIZE_MAX_CONSECUTIVE_BR + 1.
HTML_MULTI_BR_TEMPLATE_RE = r"(?:<br\s*/?>\s*){%d,}"
# _EDGE_BR_RE: strips leading/trailing <br> runs left after block-tag conversion.
HTML_EDGE_BR_RE = r"^(?:\s*<br\s*/?>\s*)+|(?:\s*<br\s*/?>\s*)+$"
# _WHITESPACE_RUN_RE: collapses ASCII whitespace runs within text nodes
# (deliberately excludes U+00A0/nbsp — see sanitize.py's docstring).
HTML_WHITESPACE_RUN_RE = r"[ \t\n\r\f\v]+"
# Normalizes BeautifulSoup's self-closed "<br/>" serialization back to "<br>".
HTML_SELF_CLOSING_BR_RE = r"<br\s*/>"
# app/ingestion/sanitize.py::decode_cfemail — fast-path markers: skip parsing
# a description that carries neither form of Cloudflare's email obfuscation
# (most descriptions have none).
HTML_CF_EMAIL_MARKERS = ("__cf_email__", "email-protection")
USER_EVENT_SCORES_RETENTION_DAYS = 30  # keyed on the underlying event's end date

# APScheduler job ids (app/main.py::_register_scheduled_jobs) — also reasoned
# about in docs/backend-ops.md and /admin/pipeline/run, so a typo in one of
# the two call sites that share a string (the log label passed to _scheduled
# and the id= kwarg on scheduler.add_job) would silently misregister a job.
JOB_ID_SYNC_FIENTA_ORGANIZERS = "sync_fienta_organizers"
JOB_ID_CLEANUP_STALE_DATA = "cleanup_stale_data"
JOB_ID_INGEST_ALL_SOURCES = "ingest_all_sources"
JOB_ID_DEDUP_PASS = "dedup_pass"
JOB_ID_CLASSIFY_PENDING = "classify_pending"
JOB_ID_PUBLISH_PENDING = "publish_pending"
JOB_ID_GEOCODE_PENDING = "geocode_pending"
JOB_ID_REFETCH_EVENT_DETAILS = "refetch_event_details"
JOB_ID_BUILD_DAILY_FEEDS = "build_daily_feeds"
JOB_ID_SEND_DAILY_DIGESTS = "send_daily_digests"

# HTTP error `detail` strings (app/routers/*). English-only server strings,
# not i18n keys (contrast shared/i18n/*.json, the user-facing string source
# of truth) — these are internal API error text, not rendered UI copy.
# f"…{var}…" details stay as {placeholder} format templates here, .format()'d
# at the call site.

# Auth (routers/auth.py + routers/organizer_auth.py) — identical wording on
# both the user and organizer auth tracks; duplicated verbatim before this.
ERROR_MISSING_SESSION_COOKIE = "Missing session cookie"
ERROR_SESSION_INVALID = "Session token expired or invalid"
ERROR_SESSION_REVOKED = "Session revoked. Please sign in again."
ERROR_MAGIC_LINK_EXPIRED = "Sign-in link has expired. Please request a new one."
ERROR_MAGIC_LINK_INVALID = "Invalid sign-in link."
ERROR_MAGIC_LINK_CONSUMED = "Sign-in link already used, expired, or not found."

# Not-found 404s, punctuation normalized to the trailing-period form.
ERROR_EVENT_NOT_FOUND = "Event not found."
ERROR_USER_NOT_FOUND = "User not found."
ERROR_ORGANIZER_NOT_FOUND = "Organizer not found."
ERROR_SUBMISSION_NOT_FOUND = "Submission not found."
ERROR_EVENT_CANCELLED = "This event was taken down and can no longer be edited."

# main.py (/internal/tick)
ERROR_INTERNAL_TICK_INVALID_TOKEN = "Invalid token"

# routers/admin.py
ERROR_ADMIN_LOCKOUT = "Too many failed admin login attempts; try again later."
ERROR_ADMIN_DISABLED = (
    "Admin endpoints disabled: ADMIN_USERNAME left at its default value"
)
ERROR_ADMIN_INCORRECT_CREDENTIALS = "Incorrect credentials"
ERROR_UNKNOWN_SOURCE = "Unknown source: {slug!r}"

# routers/browse.py, routers/feedback.py
ERROR_INVALID_SORT = "sort must be one of {sorts}"
ERROR_INVALID_SIGNAL = "Invalid signal. Must be one of: {signals}"
ERROR_INVALID_PREFERENCE_SIGNAL = "signal must be one of: {signals}"

# routers/reports.py
ERROR_INVALID_REPORT_REASON = "reason must be one of: {reasons}"
ERROR_REPORT_DETAIL_REQUIRED = (
    "detail is required when reason is 'other' or is_illegal_allegation is true."
)
ERROR_REPORT_DETAIL_TOO_LONG = "detail must be at most {max_chars} characters."
ERROR_RESOLUTION_NOTE_REQUIRED = "resolution_note is required."

# routers/settings.py
ERROR_NO_UPDATE_FIELDS = "Provide at least one field to update."

# routers/unsubscribe.py
ERROR_UNSUBSCRIBE_LINK_EXPIRED = (
    "Unsubscribe link has expired. Please use Settings instead."
)
ERROR_UNSUBSCRIBE_LINK_INVALID = "Invalid unsubscribe link."

# routers/onboarding.py
ERROR_PERSONA_COUNT = "Select between 1 and {max_selectable} personas."
ERROR_PERSONA_DUPLICATE = "Persona slugs must not repeat."
ERROR_PERSONA_UNKNOWN = "Unknown persona slug(s): {missing}"

# routers/organizer_events.py
ERROR_SUBMISSION_SOURCE_NOT_CONFIGURED = (
    "Submission source not configured; contact support."
)
ERROR_IMAGE_HOST_NOT_ALLOWED = (
    "Image URL must be uploaded via POST /organizer/events/image "
    "(res.cloudinary.com)."
)
ERROR_DAILY_SUBMISSION_LIMIT = "Daily submission limit reached. Try again tomorrow."
ERROR_DAILY_VENUE_CREATION_LIMIT = (
    "Daily venue creation limit reached. Try again tomorrow."
)
ERROR_VENUE_NOT_FOUND = "Venue not found."
ERROR_EVENT_CREATE_FAILED = "Could not create event; please try again."
ERROR_EVENT_URL_SCHEME = "Event URL is not allowed (unsupported scheme)."
ERROR_IMAGE_URL_SCHEME = "Image URL is not allowed (unsupported scheme)."
ERROR_UNSUPPORTED_IMAGE_TYPE = "Unsupported image type: {content_type!r}"
ERROR_DAILY_IMAGE_UPLOAD_LIMIT = "Daily image upload limit reached. Try again tomorrow."
ERROR_IMAGE_TOO_LARGE = "Image exceeds {max_bytes} bytes."
ERROR_IMAGE_UPLOAD_NOT_CONFIGURED = "Image upload is not configured."
ERROR_IMAGE_UPLOAD_FAILED = "Image upload failed; please try again."

# routers/utils.py
ERROR_ADMIN_JOB_FAILED = "{name} failed; see server logs"
ERROR_ADMIN_JOB_ALREADY_RUNNING = "{name} is already running; try again once it finishes."
ERROR_FEATURE_DISABLED = "{feature} disabled: {setting_name} not configured"
