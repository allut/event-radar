import http
from zoneinfo import ZoneInfo

TALLINN_TZ_NAME = "Europe/Tallinn"
TALLINN_TZ = ZoneInfo(TALLINN_TZ_NAME)

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400

HTTP_TIMEOUT_SECONDS: float = 30.0
HTTP_USER_AGENT = "EventRadarBot/1.0 (+https://eventradar.ee)"
HTTP_RETRY_MAX_ATTEMPTS = 3
HTTP_RETRY_WAIT_MULTIPLIER = 1
HTTP_RETRY_WAIT_MIN = 2
HTTP_RETRY_WAIT_MAX = 30
HTTP_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({
    http.HTTPStatus.TOO_MANY_REQUESTS,       # 429
    http.HTTPStatus.BAD_GATEWAY,             # 502
    http.HTTPStatus.SERVICE_UNAVAILABLE,     # 503
    http.HTTPStatus.GATEWAY_TIMEOUT,         # 504
})

SLUG_TITLE_MAX_LEN = 60
SLUG_HASH_HEX_LEN = 8
INGESTION_ERROR_MAX_LEN = 500

ORGANIZER_MIN_EVENTS_FOR_AUTO_ADD = 3
ORGANIZER_NAME_MAX_LEN = 200
FIENTA_ORGANIZER_SCAN_LIMIT = 1000
FIENTA_ORGANIZER_CHECK_LIMIT = 5   # max events fetched when probing a single organizer for staleness
FIENTA_CITY_FILTER = "Tallinn"
FIENTA_MAX_PAGES = 50              # safety ceiling per organizer — prevents runaway pagination

SOURCE_STATUS_OK = "ok"
SOURCE_STATUS_ERROR = "error"

EVENT_STATUS_DRAFT = "draft"
EVENT_STATUS_CLASSIFIED = "classified"
EVENT_STATUS_PUBLISHED = "published"
EVENT_STATUS_CANCELLED = "cancelled"

DEFAULT_CURRENCY = "EUR"
DEFAULT_USER_LOCALE = "en"
DEFAULT_USER_CITY = "Tallinn"
VALID_LOCALES: frozenset[str] = frozenset({"en", "et", "ru"})

# Deduplication
DEDUP_LOOKBACK_DAYS = 30    # only re-cluster events that started within this window
TITLE_RATIO_THRESHOLD = 70  # rapidfuzz token_set_ratio threshold for title match
VENUE_RATIO_THRESHOLD = 70  # rapidfuzz token_set_ratio threshold for venue match
TIME_WINDOW_HOURS = 12      # max |Δstart| in hours for two events to be dedup candidates

# Resend email delivery
RESEND_SEND_URL = "https://api.resend.com/emails"
RESEND_TIMEOUT_SECONDS: float = 10.0
RESEND_ERROR_SNIPPET_LEN = 200
# Email i18n strings (subjects, labels, templates) live in app/i18n.py.
DIGEST_SEND_HOUR = 7  # 07:00 Europe/Tallinn, one hour after build_daily_feeds
DIGEST_MAX_WHY_GO_BULLETS = 3

# Auth tokens
AUTH_MAGIC_SALT = "magic-link-v1"
AUTH_SESSION_SALT = "session-v1"

# Persona weights
PERSONA_PRIMARY_WEIGHT: float = 1.0
PERSONA_SECONDARY_WEIGHT: float = 0.4

# Ranking / scoring
DAILY_5_COUNT = 5
DAILY_5_MAX_PER_CATEGORY = 2
DAILY_5_LOOKAHEAD_DAYS = 14
RECENCY_DECAY_DAYS = 21
FEEDBACK_DECAY_BASE: float = 0.9         # per-day decay on feedback signal
FEEDBACK_INDIRECT_WEIGHT: float = 0.5    # weight of category-matched indirect signal
SCORE_HARD_EXCLUDE: float = -2.0         # sentinel: outside [-1,1] clamp, cannot be a valid score
SCORE_WEIGHT_AFFINITY: float = 0.45
SCORE_WEIGHT_RECENCY: float = 0.20
SCORE_WEIGHT_FEEDBACK: float = 0.20
SCORE_WEIGHT_QUALITY: float = 0.10
SCORE_WEIGHT_LOCALITY: float = 0.05

# Tallinn centre bounding box (~5 km radius) used for locality bonus
TALLINN_CENTER_LAT: float = 59.437
TALLINN_CENTER_LNG: float = 24.745
TALLINN_LAT_DELTA: float = 0.05
TALLINN_LNG_DELTA: float = 0.10

# Feedback signals
VALID_SIGNALS: frozenset[str] = frozenset({"like", "dislike", "bookmark", "view", "click_external"})

# Taxonomy
VALID_CATEGORIES: frozenset[str] = frozenset({
    "music", "theater", "exhibitions", "workshops", "sports",
    "food_drink", "networking", "literature", "family", "cinema",
    "alternative", "nightlife",
})

VALID_VIBES: frozenset[str] = frozenset({
    "trendy", "casual", "intimate", "high_energy", "educational",
    "indie", "underground", "mainstream", "accessible", "niche",
})

# Time-of-day / day-of-week slots derived from event.starts_at (Europe/Tallinn).
# An event can match multiple slots simultaneously (e.g. Saturday evening → weekend + evening).
# late_night: 22:00–05:59  |  evening: 18:00–21:59  |  daytime: 10:00–17:59  |  morning: 06:00–09:59
# weekend: Sat/Sun  |  weekday: Mon–Fri
VALID_TIMES: frozenset[str] = frozenset({
    "late_night", "evening", "daytime", "morning", "weekend", "weekday",
})
TIME_LATE_NIGHT_START = 22
TIME_EVENING_START = 18
TIME_DAYTIME_START = 10
TIME_MORNING_START = 6

# LLM
LLM_MAX_PROMPT_CHARS = 1200                 # cap on event text passed to classification prompt
LLM_MAX_TOKENS = 400                        # max completion tokens per LLM call
LLM_DEDUP_CONFIDENCE_THRESHOLD: float = 0.7 # minimum confidence to accept LLM same=true verdict
LLM_CLASSIFY_BATCH_SIZE = 30                # max events processed per classify_pending run
LLM_REQUEST_TIMEOUT_SECONDS: float = 30.0

LLM_DEDUP_TITLE_MAX_LEN = 200
LLM_DEDUP_VENUE_MAX_LEN = 100
LLM_DEDUP_MAX_CANDIDATE_PAIRS_PER_PASS = 100
LLM_DEDUP_PROMPT_TEMPLATE = """\
Are these two events the same event?

Event A: {title_a}
Date A: {date_a}
Venue A: {venue_a}

Event B: {title_b}
Date B: {date_b}
Venue B: {venue_b}

Respond with JSON only, no explanation: {{"same": true or false, "confidence": 0.0-1.0}}"""

LLM_CLASSIFY_WHY_GO_MAX_BULLETS = 3
LLM_CLASSIFY_LANGUAGE_CODE_MAX_LEN = 5
LLM_CLASSIFY_VENUE_FALLBACK = "unknown"
LLM_CLASSIFY_DESC_FALLBACK = "(no description)"
LLM_CLASSIFY_PROMPT_TEMPLATE = """\
Classify this Tallinn event. Respond with JSON only.

Allowed categories (pick 1-3): music, theater, exhibitions, workshops, sports, food_drink, networking, literature, family, cinema, alternative, nightlife
Allowed vibes (pick 1-3): trendy, casual, intimate, high_energy, educational, indie, underground, mainstream, accessible, niche

Event title: {title}
Venue: {venue}
Description: {description}

JSON format:
{{"categories": ["music"], "vibes": ["underground", "intimate"], "why_go": {{"en": ["reason 1", "reason 2", "reason 3"], "et": ["põhjus 1", "põhjus 2", "põhjus 3"], "ru": ["причина 1", "причина 2", "причина 3"]}}, "quality": 0.8, "language": "et"}}

Rules:
- "language" must be the ISO 639-1 code of the event's original language (et, en, ru, or other).
- "quality" is 0.0-1.0 indicating how compelling the event is.
- "why_go" must be a dict with keys "en", "et", "ru", each containing exactly 3 short bullets (max 15 words each).
- Only use values from the allowed lists for categories and vibes."""

# Newsletter inbound email extraction
LLM_TASK_NEWSLETTER = "newsletter_extract"
NEWSLETTER_SOURCE_SLUG = "newsletter_inbound"
NEWSLETTER_SUBJECT_MAX_LEN = 200
NEWSLETTER_BODY_MAX_LEN = 1500

NEWSLETTER_EXTRACT_PROMPT_TEMPLATE = """\
Extract all events from the email below. Only include events in or near Tallinn, Estonia.

Subject: {subject}

Body:
{body}

Respond with a JSON object with one key "events" containing an array of event objects. Each event must have:
- title: string (required, event name)
- starts_at: ISO 8601 datetime string like "2026-05-15T20:00:00+03:00" (null if unknown)
- venue_name: string or null
- url: string or null (ticketing or info URL)
- description: string or null (1-2 sentence summary)
- price_min: number or null (in EUR, 0 means free)

If no events found, return {{"events": []}}.
JSON only, no explanation."""

# JSON-LD ingestion
JSONLD_EVENT_TYPES: frozenset[str] = frozenset({
    "Event", "MusicEvent", "TheaterEvent", "ExhibitionEvent",
    "SocialEvent", "SportsEvent", "ChildrensEvent", "ComedyEvent",
    "DanceEvent", "FestivalEvent", "LiteraryEvent", "ScreeningEvent",
    "VisualArtsEvent",
})

LLM_PROVIDERS: list[dict[str, str]] = [
    {
        "name": "groq",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "key_attr": "GROQ_API_KEY",
    },
    {
        "name": "cerebras",
        "base_url": "https://api.cerebras.ai/v1",
        "model": "qwen-3-235b-a22b-instruct-2507",
        "key_attr": "CEREBRAS_API_KEY",
    },
    {
        "name": "mistral",
        "base_url": "https://api.mistral.ai/v1",
        "model": "mistral-small-latest",
        "key_attr": "MISTRAL_API_KEY",
    },
]

# Piletilevi HTML scraper
PILETILEVI_BASE_URL = "https://www.piletilevi.ee"
PILETILEVI_SOURCE_SLUG = "piletilevi"
PILETILEVI_TALLINN_FILTER = "Tallinn"
PILETILEVI_DATE_FORMAT = "%d.%m.%Y %H:%M"
PILETILEVI_MAX_DETAIL_FETCHES = 200  # cap per ingestion run (~6 listings × 25 cards = 150 normal)
PILETILEVI_LISTING_URLS: list[str] = [
    "/eng/tickets/",
    "/eng/tickets/concerts/",
    "/eng/tickets/theater/",
    "/eng/tickets/classical-music/",
    "/eng/tickets/comedy/",
    "/eng/tickets/exhibitions/",
]
