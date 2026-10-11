"""Event lifecycle: statuses, cancellation reasons, publish thresholds, search SQL, price validation, public counts."""

EVENT_STATUS_DRAFT = "draft"
EVENT_STATUS_CLASSIFIED = "classified"
EVENT_STATUS_PUBLISHED = "published"
EVENT_STATUS_CANCELLED = "cancelled"

EVENT_CANCELLATION_REASON_ORGANIZER_RETRACT = "organizer_retract"
EVENT_CANCELLATION_REASON_ADMIN_RETRACT = "admin_retract"
EVENT_CANCELLATION_REASON_REPORT_TAKEDOWN = "report_takedown"
EVENT_CANCELLATION_REASON_SOURCE_GONE = "source_gone"
VALID_EVENT_CANCELLATION_REASONS = frozenset(
    {
        EVENT_CANCELLATION_REASON_ORGANIZER_RETRACT,
        EVENT_CANCELLATION_REASON_ADMIN_RETRACT,
        EVENT_CANCELLATION_REASON_REPORT_TAKEDOWN,
        EVENT_CANCELLATION_REASON_SOURCE_GONE,
    }
)

# Claim-discovery title search haystack (M9): title_orig plus every locale's
# localized title, so one pg_trgm GIN expression index
# (ix_events_search_text_trgm) backs the ILIKE instead of an unindexed
# JSONB-extract OR that forced a seq scan. Must match the index expression in
# migration 0051 and the Event model textually — no bind params (the planner
# can't match an index expression against a parameter). `||` and coalesce are
# IMMUTABLE, unlike concat_ws.
EVENT_SEARCH_TEXT_SQL = (
    "coalesce(title_orig, '') || ' ' || "
    "coalesce(title_localized ->> 'et', '') || ' ' || "
    "coalesce(title_localized ->> 'en', '') || ' ' || "
    "coalesce(title_localized ->> 'ru', '')"
)

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

# Publish gate — classified events with quality_score below this stay
# 'classified' and never reach a feed. Tunable later from real data.
PUBLISH_MIN_QUALITY_SCORE: float = 0.4

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

# Upper bound (exclusive) for any scraped/LLM-derived price. events.price_* are
# Numeric(10,2); an inf/1e12 from json.loads("Infinity") raised DataError at the
# job's single commit and rolled back the whole batch (OWASP audit M-6).
PRICE_MAX_VALUE = 10**7

# ISO-4217 codes accepted by normalize_currency — anything else is dropped (a
# prompt-injected "XYZ" must not bypass the EUR literal-amount check).
VALID_CURRENCY_CODES: frozenset[str] = frozenset(
    "AED AUD BGN BRL CAD CHF CNY CZK DKK EUR GBP HKD HUF ILS INR ISK JPY KRW MXN "
    "NOK NZD PLN RON RUB RSD SEK SGD THB TRY UAH USD ZAR BYN KZT GEL AMD AZN MDL MKD BAM".split()
)

CURRENCY_CODE_MAX_LEN = 3  # mirrors Event.currency String(3)

# Not-found 404s, punctuation normalized to the trailing-period form.
ERROR_EVENT_NOT_FOUND = "Event not found."

ERROR_EVENT_CANCELLED = "This event was taken down and can no longer be edited."

ERROR_EVENT_URL_SCHEME = "Event URL is not allowed (unsupported scheme)."
