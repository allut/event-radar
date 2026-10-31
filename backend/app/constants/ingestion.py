"""Ingestion: sources, Fienta/HTML scrapers, content filters, price parsing, refetch, geocoding, publishers."""

from datetime import timedelta
from typing import NamedTuple

INGESTION_ERROR_MAX_LEN = 500
PRICE_HINT_MAX_CHARS = 300  # cap on Event.price_hint, kept short for the LLM prompt

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
# Write-phase attempts for the weekly organizer sync: one retry when the server dropped the connection during the HTTP phase (#530).
ORGANIZER_SYNC_DB_WRITE_ATTEMPTS = 2
# Publisher.name (models/claims.py) column width.
PUBLISHER_NAME_MAX_LEN = 255
# Page budget for the weekly city-filtered discovery scan; ~14 pages of 100 at today's volume (#634).
FIENTA_ORGANIZER_SCAN_MAX_PAGES = 50
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

# Event claiming (#409/#410/#411) — see CONTEXT.md's Event Claiming glossary.
PUBLISHER_STATUS_ACTIVE = "active"
PUBLISHER_STATUS_RETIRED = "retired"
VALID_PUBLISHER_STATUSES = frozenset(
    {PUBLISHER_STATUS_ACTIVE, PUBLISHER_STATUS_RETIRED}
)
# KUMU/Estonia Concert Hall are each a single institution — one Publisher row
# per source (external_id NULL), named here rather than seeds.py per the
# "backend constants" rule.
PUBLISHER_NAME_KUMU = "Kumu Art Museum"
PUBLISHER_NAME_ESTONIA_CONCERT_HALL = "Estonia Concert Hall"

KUMU_VERIFICATION_DOMAIN = "kumu.ekm.ee"
ESTONIA_CONCERT_HALL_VERIFICATION_DOMAIN = "concert.ee"

SOURCE_SLUG_NEWSLETTER = "newsletter_inbound"

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
# Same cap, for the Fienta API source (fienta.py) — unlike html_base.py's
# listing adapters, Fienta had no ceiling on its per-run detail fan-out, so a
# cold start or organizer bulk-publish could queue thousands of live tasks
# behind one rate limiter (Big-O audit H10). The skip-id set (known_ids) makes
# truncation here self-healing across runs, same as HTML_LISTING_MAX_DETAIL_FETCHES.
FIENTA_MAX_DETAIL_FETCHES = 300

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
# copy pass. events rows are never deleted (see docs/backend-ops.md "Data Retention"), so
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
# ~12 min/run, fine for the daily REFETCH_HOUR cron.
REFETCH_MAX_PER_RUN = 1000
REFETCH_REQUEST_DELAY_SECONDS: float = 1.0
# Source hosts refetched in parallel (each host stays sequential at the delay
# above). Bounds the fan-out; there are only a handful of ingest hosts.
REFETCH_HOST_CONCURRENCY = 4
# Sources ingest_all_enabled runs at once. Each scrapes its own host behind
# its own rate limiter and session; the cap bounds memory and DB connections.
INGEST_SOURCE_CONCURRENCY = 3
# Wall-clock backstop, independent of REFETCH_MAX_PER_RUN: an event that
# triggers locale-variant fetches (fetch_locale_variants) pays its own
# REFETCH_REQUEST_DELAY_SECONDS per variant, so REFETCH_MAX_PER_RUN events
# don't bound run time the way the count alone suggests. The job starts at
# REFETCH_HOUR and build_daily_feeds runs at FEED_BUILD_HOUR — this cap leaves
# real margin in that window.
# detail_refetched_at ordering means anything cut off here is picked up first
# next run, so this is self-limiting with no coverage loss.
REFETCH_MAX_RUN_SECONDS: float = 2400.0
# Flat daily throttle: an event re-synced within this window is not due again.
# Guards mainly against manual POST /admin/refetch re-runs; the cron fires once daily.
REFETCH_MIN_INTERVAL_DAYS = 1
# A detail page answering one of these means the source removed the event. Any
# other status (5xx, 403, 429) or a transport error is treated as transient.
REFETCH_GONE_STATUS_CODES: frozenset[int] = frozenset({404, 410})
# How long a detail page must keep answering gone before the event is
# cancelled, so one bad response from the source can't cancel a live event.
REFETCH_GONE_CANCEL_AFTER_DAYS = 2
# Absolute tolerance (currency units) when comparing a stored price against the
# detail-page price — sub-cent float noise must read as "unchanged", not a change.
REFETCH_PRICE_TOLERANCE = 0.005
# Mid-loop commit cadence — see GEOCODE_COMMIT_INTERVAL_SECONDS for the rationale.
REFETCH_COMMIT_INTERVAL_SECONDS: float = 120.0
# An external_id fetched but rejected by normalize() (e.g. non-Tallinn) is not
# re-fetched/re-saved on every run; it is retried once after this window so a
# transient rejection still self-heals. Pure backend scalar — not cross-stack.
INGEST_REJECT_RECHECK_DAYS = 7
# Lower bound on existing_external_ids' EventSource->Event join, applied to
# coalesce(ends_at, starts_at). Without it, every external_id ever stored for a
# source is loaded into a Python set on every hourly ingest run, growing
# monotonically since events rows are never deleted. A source's live listing
# never re-surfaces an external_id belonging to an event that ended this long
# ago (long-running listings like Fienta's exhibitions stay inside the window
# until they end), so dropping it from the skip set costs nothing beyond the
# event_sources unique index + IntegrityError handler already guarding against
# a duplicate insert (see insert_normalized_event).
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
# Digit runs are bounded (\d{1,7}) and the amount-first branch refuses to start
# mid-run ((?<!\d)) — the unbounded form rescanned a long digit run from every
# start position (quadratic; OWASP audit M-4).
CURRENCY_AMOUNT_RE = (
    r"(?:€|\bEUR\b)\s*(\d{1,7}(?:[.,]\d{1,2})?)(?!\d)"
    r"|(?<!\d)(\d{1,7}(?:[.,]\d{1,2})?)\s*(?:€|\bEUR\b)"
)

# app/ingestion/content_filters.py::is_explicit_text — collapses whitespace
# runs (incl. literal newlines within a text node) before keyword matching,
# so a multi-word keyword still matches across them.
CONTENT_FILTER_WHITESPACE_COLLAPSE_RE = r"\s+"

# app/ingestion/sanitize.py::decode_cfemail — fast-path markers: skip parsing
# a description that carries neither form of Cloudflare's email obfuscation
# (most descriptions have none).
HTML_CF_EMAIL_MARKERS = ("__cf_email__", "email-protection")

ERROR_UNKNOWN_SOURCE = "Unknown source: {slug!r}"

# ---------------------------------------------------------------------------
# Single-institution sources (KUMU, Estonia Concert Hall) — one Publisher and
# one hardcoded DNS-TXT verification domain per source; see CONTEXT.md's
# Publisher glossary entry. Piletilevi is deliberately absent: its Publisher
# resolution is promoter-id-keyed, not source-constant.
# ---------------------------------------------------------------------------
class SingleInstitution(NamedTuple):
    publisher_name: str
    verification_domain: str


SINGLE_INSTITUTION_SOURCES: dict[str, SingleInstitution] = {
    SOURCE_SLUG_KUMU: SingleInstitution(PUBLISHER_NAME_KUMU, KUMU_VERIFICATION_DOMAIN),
    SOURCE_SLUG_ESTONIA_CONCERT_HALL: SingleInstitution(
        PUBLISHER_NAME_ESTONIA_CONCERT_HALL, ESTONIA_CONCERT_HALL_VERIFICATION_DOMAIN
    ),
}
# Sources whose events the publisher_id backfill can stamp (Fienta's per-organizer
# Publishers plus the single-institution ones above).
PUBLISHER_BACKFILL_SOURCE_SLUGS: tuple[str, ...] = (
    SOURCE_SLUG_FIENTA,
    *SINGLE_INSTITUTION_SOURCES,
)

# A Fienta listing the live organizer re-query could not resolve waits this long
# before the next attempt (stops a permanently unresolvable listing being
# re-crawled every 6h run).
PUBLISHER_RESOLVE_RETRY_COOLDOWN = timedelta(days=7)

JSONLD_ID_KEY = "@id"
JSONLD_TYPE_KEY = "@type"
