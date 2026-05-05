from zoneinfo import ZoneInfo

TALLINN_TZ_NAME = "Europe/Tallinn"
TALLINN_TZ = ZoneInfo(TALLINN_TZ_NAME)

HTTP_TIMEOUT_SECONDS: float = 30.0
HTTP_USER_AGENT = "EventRadarBot/1.0 (+https://eventradar.ee)"
HTTP_RETRY_MAX_ATTEMPTS = 3
HTTP_RETRY_WAIT_MULTIPLIER = 1
HTTP_RETRY_WAIT_MIN = 2
HTTP_RETRY_WAIT_MAX = 30

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

# Deduplication
DEDUP_LOOKBACK_DAYS = 30   # only re-cluster events that started within this window
TITLE_RATIO_THRESHOLD = 70  # rapidfuzz token_set_ratio threshold for title match
VENUE_RATIO_THRESHOLD = 70  # rapidfuzz token_set_ratio threshold for venue match
TIME_WINDOW_HOURS = 12      # max |Δstart| in hours for two events to be dedup candidates
