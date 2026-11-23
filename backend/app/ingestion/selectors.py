"""Per-source scrape configuration: CSS selectors, site paths/formats, and
fixed-venue tables for the HTML-listing adapters (and Fienta's detail page).

Everything here is tied to a live site's DOM/URL structure, not business
logic — a markup change on a source site should be a one-line fix here.
Cross-source tuning knobs (caps, timeouts) stay in app/constants/ingestion.py.
"""

from typing import NamedTuple

from app.constants.ingestion import (
    ESTONIA_CONCERT_HALL_VERIFICATION_DOMAIN,
    KUMU_VERIFICATION_DOMAIN,
)

# --- Piletilevi (www.piletilevi.ee) ---
PILETILEVI_HOST = "piletilevi.ee"
# The city as a whole comma-separated part: "Tallinna mnt 13" is a street
# elsewhere, and "Tallinn-Narva mnt 5" a road.
PILETILEVI_TALLINN_RE = r"(?:^|,)\s*(?:\d{5}\s+)?Tallinn\s*(?:,|$)"
PILETILEVI_DATE_FORMAT = "%d.%m.%Y %H:%M"
PILETILEVI_DATE_SEPARATOR = "•"
PILETILEVI_ALL_PATH = "/en/tickets/all"
PILETILEVI_MAX_PAGES = 70  # safety bound — real stop is an empty page or the detail cap

PILETILEVI_CARD_SELECTOR = "a.card"
PILETILEVI_TITLE_SELECTOR = ".card__time-title h3"
PILETILEVI_DATE_SELECTOR = ".card__time"
PILETILEVI_VENUE_SELECTOR = '[data-cy="card-description"]'
PILETILEVI_IMAGE_SELECTOR = "img.card__image"
PILETILEVI_DETAIL_DESC_SELECTOR = ".event__description"
# Promoter profile page's "Contacts and additional details" mailto — the only
# mailto: link on that page (#412 claim verification, app/claims/).
PILETILEVI_PROMOTER_CONTACT_SELECTOR = "a[href^='mailto:']"
# No stable class on the "Important information" h2 (generic Tailwind
# utilities) — only two h2s exist on the page, so anchoring on heading text
# is unambiguous. ET uses "Hinnainfo"; EN uses "Important information"; RU
# uses "Дополнительная информация" (verified live on piletilevi.ee/ru/tickets/...).
PILETILEVI_IMPORTANT_INFO_HEADINGS: dict[str, str] = {
    "en": "Important information",
    "et": "Hinnainfo",
    "ru": "Дополнительная информация",
}
# Tag of the important-info heading, matched by its text (PILETILEVI_IMPORTANT_INFO_HEADINGS).
PILETILEVI_IMPORTANT_INFO_HEADING_TAG = "h2"
# Wrapper the important-info heading lives inside — used to scope the sibling
# text extraction to that one block rather than the whole detail page.
PILETILEVI_INFO_BLOCK_CLASS = "white-rounded-block"

# Piletilevi image height parameter — the listing page pins height=252; the
# full-resolution variant uses this value in the same /height=N/ path segment.
PILETILEVI_IMAGE_HEIGHT = 1009

# Piletilevi's own public store price API (same host as the listing, unlike the
# ECH-via-Piletilevi cross-host lookup below) — an unauthenticated session
# cookie (bootstrapped once per run via the empty-body login call) then
# authorizes the per-event prices lookup by event code (the path segment
# after /tickets/, e.g. "EIHT67B2EC").
PILETILEVI_LOGIN_EXPRESS_URL = "https://www.piletilevi.ee/api/v1/login/express"
PILETILEVI_PRICES_URL = "https://www.piletilevi.ee/api/v1/store/events/{code}/prices"
PILETILEVI_PRICES_LANGUAGE = "en"
# Business states the prices endpoint reports as HTTP 400 (not request errors):
# a pre-sale event answers {"code": ...}, a sold-out one a list of
# [{"errors": [{"message": ...}]}].
PILETILEVI_SALE_NOT_STARTED_CODE = "web_event_sale_has_not_started"
PILETILEVI_SOLD_OUT_MESSAGE = "This event is SOLD OUT."
PILETILEVI_PRICE_OUTCOME_SALE_NOT_STARTED = "sale_not_started"
PILETILEVI_PRICE_OUTCOME_SOLD_OUT = "sold_out"

# --- KUMU (kumu.ekm.ee) ---
KUMU_HOST = KUMU_VERIFICATION_DOMAIN
KUMU_DATE_FORMAT = "%d/%m/%Y | %H:%M"
KUMU_MAX_PAGES = 15  # safety bound — calendar is ~4 pages today

KUMU_CARD_SELECTOR = "ul.event-grid__cards > li.event-grid__item"
KUMU_LINK_SELECTOR = "a.card__link"
KUMU_TITLE_SELECTOR = "h2.card__header-title"
KUMU_HIDDEN_SELECTOR = ".h-visually-hidden"
KUMU_DATE_SELECTOR = ".card__header-date-text"
KUMU_IMAGE_SELECTOR = "img.image__img.lazyload"
KUMU_PRICE_SELECTOR = ".event-header__ticket-price"
KUMU_PRICE_TOOLTIP_ITEM_SELECTOR = ".tooltip-list__item"
KUMU_PRICE_TOOLTIP_TITLE_SELECTOR = ".tooltip-list__item-title"
KUMU_PRICE_TOOLTIP_VALUE_SELECTOR = ".tooltip-list__item-value"
KUMU_DESCRIPTION_SELECTOR = ".single__content-dynamic"

# Fixed-venue address/coords — KUMU scrapes a single venue's own site, so
# every event normalizes to the same place.
KUMU_VENUE_NAME = "Kumu Art Museum"
KUMU_VENUE_ADDRESS = "A. Weizenbergi 34, 10127 Tallinn"
KUMU_VENUE_LAT = 59.4363374
KUMU_VENUE_LNG = 24.7958299
KUMU_SITE_TITLE_SUFFIX = " - Kumu kunstimuuseum"
KUMU_SITE_NAME_ET = "Kumu kunstimuuseum"  # ET site name; homepage og:title starts with this

# --- Estonia Concert Hall (concert.ee) ---
ESTONIA_CONCERT_HALL_HOST = ESTONIA_CONCERT_HALL_VERIFICATION_DOMAIN
ESTONIA_CONCERT_HALL_TALLINN_FILTER = "Tallinn"
ESTONIA_CONCERT_HALL_AJAX_PATH = "/wp-admin/admin-ajax.php"
ESTONIA_CONCERT_HALL_AJAX_ACTION = "ek_list_display"
ESTONIA_CONCERT_HALL_MAX_EVENTS = 500  # ek_ajax_count; server returns min(count, total)
# Piletilevi store price lookup — concert.ee's "Buy ticket" links carry a Piletilevi
# store event id (pid) that resolves to min/max price via this public embed endpoint.
# The endpoint requires a fresh per-session "key", bootstrapped via an express-auth
# call (yellow_session claim of the returned JWT) before each ingestion run.
ESTONIA_CONCERT_HALL_PILETILEVI_URL = "https://store.piletilevi.ee/public/"
ESTONIA_CONCERT_HALL_PILETILEVI_CENTER = "7"
ESTONIA_CONCERT_HALL_PILETILEVI_SHOP_PROVIDER = "econ"
ESTONIA_CONCERT_HALL_PILETILEVI_AUTH_URL = (
    "https://store.piletilevi.ee/web-api/customer/public/auth/express"
)
ESTONIA_CONCERT_HALL_PILETILEVI_SESSION_CLAIM = "yellow_session"
ESTONIA_CONCERT_HALL_PILETILEVI_PARAMS = {
    "center": ESTONIA_CONCERT_HALL_PILETILEVI_CENTER,
    "lang": "eng",
    "application": "ajaxFrontend",
    "type": "concertInformation",
    "shop_provider": ESTONIA_CONCERT_HALL_PILETILEVI_SHOP_PROVIDER,
}

ESTONIA_CONCERT_HALL_ROW_SELECTOR = ".event-list .row"
ESTONIA_CONCERT_HALL_TITLE_SELECTOR = ".info h2 a"
ESTONIA_CONCERT_HALL_DATE_SELECTOR = ".event-date"
ESTONIA_CONCERT_HALL_TIME_SELECTOR = ".event-time"
ESTONIA_CONCERT_HALL_LOCATION_SELECTOR = ".event-location"
ESTONIA_CONCERT_HALL_VENUE_SELECTOR = ".event-venue"
ESTONIA_CONCERT_HALL_IMAGE_SELECTOR = ".image"
ESTONIA_CONCERT_HALL_DESCRIPTION_SELECTOR = ".main"

ECH_SITE_TITLE_SUFFIX = " - Eesti Kontsert"
ECH_SITE_NAME_ET = "Eesti Kontsert"  # ET site name; homepage og:title starts with this

# Host -> ET site name, for app/ingestion/refetch.py's suspect-locale-title
# check: a stored localized title that starts with the site's own homepage
# name (rather than an actual event title) looks like site-level content.
SUSPECT_LOCALE_TITLE_PREFIXES: dict[str, str] = {
    KUMU_HOST: KUMU_SITE_NAME_ET,
    ESTONIA_CONCERT_HALL_HOST: ECH_SITE_NAME_ET,
}


class VenueInfo(NamedTuple):
    name: str
    address: str
    lat: float
    lng: float


# concert.ee (Estonia Concert Hall source) lists Eesti Kontsert events across many
# venues, not just Estonia Concert Hall itself. Map the exact `.event-venue` text to
# its address/coords for the Tallinn venues seen in practice; unmatched venues (and
# the source's own listing/location filtering) leave venue_address/lat/lng unset.
ESTONIA_CONCERT_HALL_VENUES: dict[str, VenueInfo] = {
    "Estonia kontserdisaal": VenueInfo(
        "Estonia Concert Hall", "Estonia pst 4, 10143 Tallinn", 59.4348964, 24.7511983
    ),
    "Kadrioru loss": VenueInfo(
        "Kadriorg Palace", "A. Weizenbergi 37, 10127 Tallinn", 59.4384656, 24.7910249
    ),
    "Niguliste muuseum": VenueInfo(
        "Niguliste Museum", "Niguliste 3, 10130 Tallinn", 59.4359214, 24.7427740
    ),
    "Tallinna raekoda": VenueInfo(
        "Tallinn Town Hall", "Raekoja plats 1, 10146 Tallinn", 59.4370067, 24.7453123
    ),
    "KUMU auditoorium": VenueInfo(
        KUMU_VENUE_NAME, KUMU_VENUE_ADDRESS, KUMU_VENUE_LAT, KUMU_VENUE_LNG
    ),
    "Tallinna Filharmoonia Mustpeade maja": VenueInfo(
        "Mustpeade Maja", "Pikk 26, 10133 Tallinn", 59.4387989, 24.7467744
    ),
    "Tallinna Jaani kirik": VenueInfo(
        "St. John's Church", "Vabaduse väljak 1, 10146 Tallinn", 59.4337210, 24.7453922
    ),
}

# --- Fienta (fienta.com) ---
FIENTA_DESCRIPTION_SELECTOR = "div.rich-text"

# WordPress thumbnail suffix stripping — hosts whose image URLs contain a -WxH
# suffix that can be dropped to get the full-resolution original.
WP_THUMBNAIL_HOSTS: frozenset[str] = frozenset(
    {ESTONIA_CONCERT_HALL_HOST, KUMU_HOST}
)
WP_THUMBNAIL_SUFFIX_RE = r"-\d+x\d+(\.\w+)$"

# --- Piletilevi image/price scraping regexes ---
PILETILEVI_HEIGHT_PATH_RE = r"/height=\d+/"
PILETILEVI_CODE_RE = r"/tickets/([A-Za-z0-9]+)"

# --- Estonia Concert Hall scraping regexes ---
ESTONIA_CONCERT_HALL_DATE_RE = r"(\d{1,2})\.(\d{1,2})"
ESTONIA_CONCERT_HALL_IMAGE_URL_RE = r"url\((.*?)\)"
ESTONIA_CONCERT_HALL_PID_RE = r"pid=(\d+)"

# --- Fienta address-parsing regexes ---
# "<street>, <postal code> <City>, <county>" — city sits after a postal code.
# Estonian codes are 5 digits; foreign codes (LV: 4, LT: 5) also covered by 3-6.
# \w with UNICODE matches any Unicode letter (Estonian/Latvian/Lithuanian diacritics).
FIENTA_CITY_FROM_ADDRESS_RE = r"\b\d{3,6}\s+(\w[\w\-]+)"
# Matches a 5-digit postal code (Estonian format) anywhere in an address string.
FIENTA_POSTAL_CODE_RE = r"\b\d{5}\b"

# --- schema.org JSON-LD scraping constants ---
# Shared by app/ingestion/jsonld.py (Fienta/Piletilevi detail pages + the
# daily detail-refetch sync) and any future adapter reading Event JSON-LD.
JSONLD_SCRIPT_TYPE = "application/ld+json"
JSONLD_EVENT_TYPE = "Event"
# A zero-priced offer whose availability ends in this suffix is a sold-out
# placeholder, not a real free tier — see extract_jsonld_event_offers.
JSONLD_SOLD_OUT_SUFFIX = "SoldOut"
JSONLD_ADDRESS_FIELDS: tuple[str, ...] = (
    "streetAddress",
    "addressLocality",
    "addressRegion",
)

# --- Cloudflare email-obfuscation marker (app/ingestion/sanitize.py) ---
# Cloudflare's "Email Address Protection" rewrites a mailto anchor's href to
# this prefix + an encoded data-cfemail-style payload; decode_cfemail() reverses it.
CFEMAIL_HREF_MARKER = "/cdn-cgi/l/email-protection#"
