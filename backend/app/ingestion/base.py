import asyncio
import hashlib
import http
import json
import logging
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
import nh3
from bs4 import BeautifulSoup
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
    wait_random,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    CURRENCY_AMOUNT_RE,
    DEFAULT_CURRENCY,
    ESTONIA_BBOX,
    TALLINN_REGION_BBOX,
    EVENT_STATUS_DRAFT,
    EXPLICIT_KEYWORDS,
    NON_EVENT_TITLE_KEYWORDS,
    NON_EVENT_VENUE_KEYWORDS,
    FIENTA_CITY_FILTER,
    HTML_BLOCK_TAGS_TO_BREAK,
    HTML_SANITIZE_ALLOWED_ATTRS,
    HTML_SANITIZE_ALLOWED_TAGS,
    HTML_SANITIZE_MAX_CONSECUTIVE_BR,
    HTTP_RETRY_AFTER_MAX_SECONDS,
    HTTP_RETRYABLE_STATUS_CODES,
    HTTP_RETRY_JITTER_MAX,
    HTTP_RETRY_MAX_ATTEMPTS,
    HTTP_RETRY_WAIT_MAX,
    HTTP_RETRY_WAIT_MIN,
    HTTP_RETRY_WAIT_MULTIPLIER,
    INGEST_REJECT_RECHECK_DAYS,
    INGESTION_ERROR_MAX_LEN,
    LOCALIZED_TEXT_HREFLANG_NORMALIZE,
    LOCALIZED_TEXT_MAX_DESC_CHARS,
    LOCALIZED_TEXT_MAX_TITLE_CHARS,
    PRICE_CONTEXT_MAX_CHARS,
    PRICE_FEE_CLAUSE_RE,
    PRICE_FEE_KEYWORDS,
    PRICE_FROM_STRING_RE,
    SAFE_URL_SCHEMES,
    SLUG_HASH_HEX_LEN,
    SLUG_TITLE_MAX_LEN,
    SOURCE_STATUS_ERROR,
    SOURCE_STATUS_OK,
    TALLINN_TZ,
)
from app.models.models import Event, EventSource, IngestionRun, RawEvent, Source

log = logging.getLogger(__name__)


def _is_retryable(exc: BaseException) -> bool:
    """Return True for transient HTTP failures worth retrying."""
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in HTTP_RETRYABLE_STATUS_CODES
    return isinstance(exc, httpx.RequestError)


def retry_after_seconds(exc: BaseException) -> float | None:
    """Parse a 429 response's Retry-After header (seconds or HTTP-date form).

    Returns None if exc isn't a 429 HTTPStatusError or the header is missing/
    unparseable. Capped at HTTP_RETRY_AFTER_MAX_SECONDS so a misbehaving or
    malicious upstream can't stall the retry loop indefinitely.
    """
    if not isinstance(exc, httpx.HTTPStatusError):
        return None
    if exc.response.status_code != http.HTTPStatus.TOO_MANY_REQUESTS:
        return None
    header = exc.response.headers.get("Retry-After")
    if not header:
        return None
    try:
        seconds = float(header)
    except ValueError:
        try:
            dt = parsedate_to_datetime(header)
        except (TypeError, ValueError):
            return None
        if dt.tzinfo is None:
            # RFC 7231 HTTP-dates always carry GMT, but parsedate_to_datetime
            # returns a naive datetime if the source string omits a zone —
            # treat that as UTC rather than letting .timestamp() assume local.
            dt = dt.replace(tzinfo=UTC)
        seconds = dt.timestamp() - time.time()
    return max(0.0, min(seconds, HTTP_RETRY_AFTER_MAX_SECONDS))


def _retry_wait(retry_state: RetryCallState) -> float:
    """Honor a 429's Retry-After header; otherwise jittered exponential backoff."""
    outcome = retry_state.outcome
    if outcome is not None and outcome.failed:
        exc = outcome.exception()
        if exc is not None:
            wait = retry_after_seconds(exc)
            if wait is not None:
                return wait
    base_wait = wait_exponential(
        multiplier=HTTP_RETRY_WAIT_MULTIPLIER,
        min=HTTP_RETRY_WAIT_MIN,
        max=HTTP_RETRY_WAIT_MAX,
    )(retry_state)
    jitter = wait_random(0, HTTP_RETRY_JITTER_MAX)(retry_state)
    return base_wait + jitter


_http_retry = retry(
    retry=retry_if_exception(_is_retryable),
    wait=_retry_wait,
    stop=stop_after_attempt(HTTP_RETRY_MAX_ATTEMPTS),
    reraise=True,
)


class AsyncRateLimiter:
    """Min-interval gate: serializes acquire() calls so they are >= interval apart.

    Used to proactively pace outbound requests to a rate-limited upstream (Fienta)
    instead of relying solely on reactive retry after a 429 is already hit.
    """

    def __init__(self, interval_seconds: float) -> None:
        self._interval = interval_seconds
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._next_allowed - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = time.monotonic()
            self._next_allowed = now + self._interval

    def backoff(self, seconds: float) -> None:
        """Push the next-allowed time out by at least `seconds` from now.

        Called when a request exhausts retries on a 429, so remaining callers
        sharing this limiter back off together instead of piling onto a source
        that has already signalled it's overloaded.
        """
        candidate = time.monotonic() + seconds
        if candidate > self._next_allowed:
            self._next_allowed = candidate


def host_guard_hook(
    allowed_hosts: str | None | frozenset[str | None],
) -> Callable[[httpx.Request], Coroutine[Any, Any, None]]:
    """Build a client `request` event hook enforcing every request — including
    each redirect hop httpx follows — stays within allowed_hosts (SSRF guard).

    httpx fires the `request` hook once per hop inside its redirect loop, so
    this is the only point that can validate a redirect's *destination* host;
    pre-fetch checks elsewhere only validate the un-redirected URL. Accepts a
    single host or a frozenset when a source legitimately spans more than one
    host (e.g. a deliberate cross-host lookup against a fixed, hardcoded URL).
    """
    raw_hosts: frozenset[str | None] = (
        allowed_hosts
        if isinstance(allowed_hosts, frozenset)
        else frozenset({allowed_hosts})
    )
    # Drop None — a malformed configured URL whose hostname parses to None
    # must never become an allowed host; that would let any redirect target
    # that also parses to a None hostname (e.g. a non-network scheme) bypass
    # the guard. Excluding it makes a misconfigured source fail closed.
    hosts: frozenset[str] = frozenset(h for h in raw_hosts if h is not None)

    async def hook(request: httpx.Request) -> None:
        if urlsplit(str(request.url)).hostname not in hosts:
            # ValueError, not httpx.RequestError: a host mismatch is a
            # permanent guard failure, not a transient one, and
            # httpx.RequestError is retried by _http_retry's predicate.
            raise ValueError(f"request host mismatch (SSRF guard): {request.url}")

    return hook


@_http_retry
async def http_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict | None = None,
    headers: dict | None = None,
) -> httpx.Response:
    """Shared HTTP GET with exponential-backoff retry for transient failures."""
    r = await client.get(url, params=params, headers=headers)
    r.raise_for_status()
    return r


@_http_retry
async def http_post(
    client: httpx.AsyncClient,
    url: str,
    *,
    data: dict | None = None,
    json_body: dict | None = None,
    headers: dict | None = None,
) -> httpx.Response:
    """Shared HTTP POST with exponential-backoff retry for transient failures."""
    r = await client.post(url, data=data, json=json_body, headers=headers)
    r.raise_for_status()
    return r


def safe_external_url(url: str | None, source: str | None = None) -> str | None:
    """Drop URLs whose scheme isn't http(s) — guards against stored XSS via
    javascript:/data: URLs from untrusted sources rendered into <a href>/<img src>."""
    if not url:
        return None
    scheme = urlsplit(url).scheme.lower()
    if scheme not in SAFE_URL_SCHEMES:
        log.warning(
            "dropped non-http(s) url from source %s: scheme=%s", source, scheme
        )
        return None
    return url


_MULTI_BR_RE = re.compile(r"(?:<br\s*/?>\s*){%d,}" % (HTML_SANITIZE_MAX_CONSECUTIVE_BR + 1))
_EDGE_BR_RE = re.compile(r"^(?:\s*<br\s*/?>\s*)+|(?:\s*<br\s*/?>\s*)+$")


def _block_tags_to_breaks(html: str) -> str:
    """Convert bare block-wrapper tags (e.g. <div>) to <br> so line structure survives.

    nh3 strips disallowed tags without inserting any separator, so a source that
    encodes each line as a <div> (Piletilevi) collapses into run-on text. Replacing
    each such wrapper with a trailing <br> before sanitizing preserves the breaks
    using an already-allowlisted tag, keeping the stored HTML clean (no <div> noise).
    """
    lowered = html.lower()
    if not any(f"<{tag}" in lowered for tag in HTML_BLOCK_TAGS_TO_BREAK):
        return html
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(list(HTML_BLOCK_TAGS_TO_BREAK)):
        tag.insert_after(soup.new_tag("br"))
        tag.unwrap()
    return str(soup)


_WHITESPACE_RUN_RE = re.compile(r"[ \t\n\r\f\v]+")


def _collapse_text_whitespace(html: str) -> str:
    """Collapse whitespace runs within text nodes, leaving tags/attributes untouched.

    Source markup (e.g. KUMU's indented anchor tags) leaves newlines/indentation
    inside text nodes; nh3 sanitizes tags but never touches text content, so that
    raw whitespace survives into storage and renders literally under the
    frontend's white-space: pre-wrap. Collapsing here (post-sanitize, text-only)
    fixes it at the source for every HTML-sourced description. Matches ASCII
    whitespace only, not U+00A0 (non-breaking space, which BeautifulSoup decodes
    &nbsp; entities into) — nbsp is intentional spacing from the source content,
    not formatting noise, and Python's \\s would otherwise silently collapse it.
    """
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.find_all(string=True):
        node.replace_with(_WHITESPACE_RUN_RE.sub(" ", node))
    # BeautifulSoup serializes void elements as "<br/>"; normalize back to the
    # bare "<br>" form the rest of sanitize_html and its callers expect.
    return re.sub(r"<br\s*/>", "<br>", str(soup))


def sanitize_html(text: str | None) -> str | None:
    """Sanitize HTML with a strict allowlist; plain text passes through unchanged.

    Safe for storing in description/important_info fields. nh3/ammonia forces
    rel="noopener" on links, drops javascript:/event-handler attrs, and HTML-escapes
    any disallowed tags so they render as visible text rather than markup. Block
    wrappers in HTML_BLOCK_TAGS_TO_BREAK are converted to <br> first (see
    _block_tags_to_breaks) so line boundaries are not lost when nh3 strips them.
    """
    if text is None:
        return None
    cleaned = nh3.clean(
        _block_tags_to_breaks(text),
        tags=set(HTML_SANITIZE_ALLOWED_TAGS),
        attributes=HTML_SANITIZE_ALLOWED_ATTRS,
        url_schemes=set(SAFE_URL_SCHEMES),
        link_rel="noopener noreferrer",
    )
    if not cleaned:
        return None
    cleaned = _MULTI_BR_RE.sub("<br>" * HTML_SANITIZE_MAX_CONSECUTIVE_BR, cleaned)
    cleaned = _EDGE_BR_RE.sub("", cleaned)
    if not cleaned:
        return None
    cleaned = _collapse_text_whitespace(cleaned)
    # Strip ASCII whitespace only — bare .strip() also treats U+00A0 (nbsp) as
    # whitespace and would delete an intentional leading/trailing &nbsp;.
    return cleaned.strip(" \t\n\r\f\v") or None


def html_to_text(text: str | None) -> str | None:
    """Strip HTML tags from a sanitized description, returning plain text.

    Used by plain-text consumers (LLM prompts, explicit-keyword filter, dedup
    quality rank) so they never receive raw HTML tags or entities.
    """
    if not text:
        return text
    return BeautifulSoup(text, "html.parser").get_text(separator=" ", strip=True) or None


_EXPLICIT_KEYWORD_PATTERNS = [
    re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
    for kw in EXPLICIT_KEYWORDS
]


def is_explicit_text(*parts: str | None) -> bool:
    """Word-boundary match of EXPLICIT_KEYWORDS against the joined text parts.

    Used at ingest time to flag sexually-explicit listings (Event.is_explicit)
    before they ever reach the LLM. HTML tags are stripped before matching so
    stored HTML descriptions are scanned correctly. Whitespace runs (including
    literal newlines within a single text node, not just HTML-tag breaks) are
    collapsed to a single space so multi-word keywords (e.g. "anal sex") still
    match across them — a miss here has no Layer-2 backstop, since flagged and
    unflagged-but-explicit events both skip straight past the LLM call.
    """
    text = " ".join(html_to_text(p) or "" for p in parts if p)
    text = re.sub(r"\s+", " ", text)
    return any(pattern.search(text) for pattern in _EXPLICIT_KEYWORD_PATTERNS)


_NON_EVENT_TITLE_PATTERNS = [
    re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
    for kw in NON_EVENT_TITLE_KEYWORDS
]
_NON_EVENT_VENUE_PATTERNS = [
    re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
    for kw in NON_EVENT_VENUE_KEYWORDS
]


def is_non_event_text(title: str | None, venue_name: str | None) -> bool:
    """Word-boundary match flagging non-event listings (Event.is_non_event).

    Scoped narrower than is_explicit_text: NON_EVENT_TITLE_KEYWORDS run against
    the title only (descriptions routinely mention "gift cards available" as a
    payment option — a false positive), and NON_EVENT_VENUE_KEYWORDS run
    against the venue name only (online-only webinars/recordings). Layer 2
    (LLM "non_event" classification flag) catches what this misses.
    """
    title_text = (html_to_text(title) or "") if title else ""
    if any(p.search(title_text) for p in _NON_EVENT_TITLE_PATTERNS):
        return True
    venue_text = (html_to_text(venue_name) or "") if venue_name else ""
    return any(p.search(venue_text) for p in _NON_EVENT_VENUE_PATTERNS)


def normalize_currency(raw: Any, has_price: bool) -> str | None:
    """Coerce a raw currency value; fall back to DEFAULT_CURRENCY only when a price exists."""
    if raw:
        return str(raw)
    return DEFAULT_CURRENCY if has_price else None


# Regex to extract the city token from Fienta-style addresses:
# "<street>, <postal code> <City>, <county>" — city sits after a postal code.
# Estonian codes are 5 digits; foreign codes (LV: 4, LT: 5) also covered by 3-6.
# \w with UNICODE matches any Unicode letter (covers Estonian, Latvian, Lithuanian diacritics).
_CITY_FROM_ADDRESS_RE = re.compile(r"\b\d{3,6}\s+(\w[\w\-]+)", re.UNICODE)


def address_city(address: str) -> str | None:
    """Extract city token from a Fienta-style address string, or None if not parseable."""
    m = _CITY_FROM_ADDRESS_RE.search(address)
    return m.group(1) if m else None


def is_target_city(address: str | None) -> bool:
    """Keep only FIENTA_CITY_FILTER (Tallinn) or city-less, assumed-Tallinn addresses.

    Allowlist, not denylist: drops any address whose parseable city token is not
    FIENTA_CITY_FILTER, so unknown Estonian towns and foreign cities are excluded
    without needing to enumerate them. City-less addresses (no postal-code pattern)
    are kept — usually a Tallinn venue name with no street/postal in the string.

    Known limitation (acceptable — all observed Fienta data carries postal codes):
    an address with a city but no postal code can't be parsed, so it is kept.
    """
    if not address:
        return True
    city = address_city(address)
    if city is None:
        return True  # unparseable → keep
    return city == FIENTA_CITY_FILTER


def parse_dt(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TALLINN_TZ)
        return dt
    except (ValueError, TypeError):
        return None


@dataclass
class NormalizedEvent:
    external_id: str
    title: str
    starts_at: datetime  # must be timezone-aware
    description: str | None = None
    important_info: str | None = None
    ends_at: datetime | None = None
    venue_name: str | None = None
    venue_address: str | None = None
    lat: float | None = None
    lng: float | None = None
    url: str | None = None
    image_url: str | None = None
    price_min: float | None = None
    price_max: float | None = None
    currency: str | None = None
    price_hint: str | None = None
    has_free_tier: bool = False
    title_localized: dict[str, str] | None = None
    description_localized: dict[str, str] | None = None
    important_info_localized: dict[str, str] | None = None

    def __post_init__(self) -> None:
        # Coords without an address are orphan data here — the geocode/sibling-copy
        # chain keys off venue_address — so drop them rather than persist a pin we
        # can never re-derive or match.
        if self.venue_address is None:
            self.lat = None
            self.lng = None


def _make_slug(title: str, starts_at: datetime, external_id: str) -> str:
    safe = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    date_part = starts_at.strftime("%Y%m%d")
    # short hex keeps collision probability <0.1% up to ~10k events/run
    h = hashlib.md5(external_id.encode(), usedforsecurity=False).hexdigest()[
        :SLUG_HASH_HEX_LEN
    ]
    return f"{safe[:SLUG_TITLE_MAX_LEN]}-{date_part}-{h}"


async def existing_external_ids(db: AsyncSession, source_id: int) -> set[str]:
    """Return external_ids already stored in event_sources for this source.

    Lets adapters skip detail fetches for already-ingested events (forward-only
    + self-healing: new events get fetched every run until stored).
    """
    rows = await db.scalars(
        select(EventSource.external_id).where(EventSource.source_id == source_id)
    )
    return {r for r in rows.all() if r is not None}


async def ingest_skip_ids(db: AsyncSession, source_id: int) -> set[str]:
    """external_ids to skip this run: already-stored events (forward-only) plus
    events fetched-but-rejected within INGEST_REJECT_RECHECK_DAYS, so a
    permanently-rejected event isn't re-fetched/re-saved every run."""
    stored = await existing_external_ids(db, source_id)
    cutoff = datetime.now(tz=TALLINN_TZ) - timedelta(days=INGEST_REJECT_RECHECK_DAYS)
    rows = await db.scalars(
        select(RawEvent.external_id).where(
            RawEvent.source_id == source_id,
            RawEvent.fetched_at >= cutoff,
        )
    )
    recent = {r for r in rows.all() if r is not None}
    return stored | recent


_PRICE_FROM_STRING_RE = re.compile(PRICE_FROM_STRING_RE, re.IGNORECASE)


def parse_price_from_string(
    value: str | None,
) -> tuple[float | None, float | None, str | None, bool]:
    """Parse a Fienta listing price_from_string into
    (price_min, price_max, currency, has_free_tier).

    Grammar (verified across all 803 live rows): optional "From ", a number, a 3-letter
    currency; optional ", free" suffix; or the literal "Free"; or None/empty.
    price_min/price_max bound the PAID amount(s); has_free_tier flags a paid listing
    that also has a free option (e.g. members/companions) alongside the paid tier.
      - "10 EUR"           -> (10, 10, "EUR", False)  exact price, min == max
      - "From 28 EUR"      -> (28, None, "EUR", False) open-ended, no listing ceiling
      - "From 6 EUR, free" -> (6, None, "EUR", True)   paid from 6, free tier also exists
      - "40 EUR, free"     -> (40, 40, "EUR", True)    paid 40, free tier also exists
      - "Free"             -> (0, 0, None, False)       genuinely free, no paid tier
      - None / unparseable -> (None, None, None, False)
    """
    if not value:
        return (None, None, None, False)
    text = value.strip()
    has_free = text.lower() == "free" or text.lower().endswith(", free")
    m = _PRICE_FROM_STRING_RE.search(text)
    if not m:
        return (0.0, 0.0, None, False) if has_free else (None, None, None, False)
    amount = float(m.group(1).replace(",", "."))
    currency = m.group(2).upper()
    # The optional "From " prefix is captured inside the match, so test the raw
    # string's start rather than text[:m.start()] (which would be empty here).
    is_from = text.lower().startswith("from")
    ceiling = None if is_from else amount
    return (amount, ceiling, currency, has_free)


_CURRENCY_AMOUNT_RE = re.compile(CURRENCY_AMOUNT_RE, re.IGNORECASE)

_PRICE_FEE_CLAUSE_RE = re.compile(
    PRICE_FEE_CLAUSE_RE.format(
        keywords="|".join(re.escape(kw) for kw in sorted(PRICE_FEE_KEYWORDS, key=len, reverse=True))
    ),
    re.IGNORECASE,
)


def strip_fee_amounts(text: str | None) -> str | None:
    """Remove booking/service/agent-fee clauses from free text.

    Strips patterns like "agenditasu 3,20 €" or "teenustasu 1.40€/ pilet" so
    a downstream price extractor doesn't treat the fee as a ticket price.
    Real prices that trail in the same run survive ("agenditasu 3,20 € Pilet 45 €"
    → " Pilet 45 €"). No-op when no fee keyword is present.
    """
    if not text:
        return text
    return _PRICE_FEE_CLAUSE_RE.sub("", text)


def eur_amounts_from_text(value: str | None) -> list[float]:
    """Return every €/EUR amount found in text (duplicates included), or [] if none.

    Only matches amounts adjacent to a € symbol or EUR code (so durations, years, and
    other stray numbers are ignored). Handles European "12,50" and US "12.50" decimals.
    """
    if not value:
        return []
    return [
        float((m.group(1) or m.group(2)).replace(",", "."))
        for m in _CURRENCY_AMOUNT_RE.finditer(value)
    ]


def eur_price_bounds_from_text(value: str | None) -> tuple[float | None, float | None]:
    """Return (min, max) of all €/EUR amounts in text, or (None, None) if none found."""
    amounts = eur_amounts_from_text(value)
    if not amounts:
        return (None, None)
    return (min(amounts), max(amounts))


def price_context_digest(*texts: str | None) -> str:
    """Return only the lines carrying a €/EUR amount from the given raw HTML texts,
    joined and capped at ``PRICE_CONTEXT_MAX_CHARS``.

    Full ``description_orig``/``important_info`` can run past the LLM prompt's
    per-field char caps (e.g. IMPORTANT_INFO_MAX_CHARS), truncating away distant
    price tiers (see VAN GOGH: paid tiers up to €52 sit past the 1200-char cut).
    Distilling to price-bearing lines first lets the full tier list reach the
    prompt within a small, fixed budget regardless of surrounding prose length.
    Each text is converted from HTML and fee clauses (agenditasu, service fee,
    etc.) are stripped before scanning, mirroring the prompt-field pipeline.
    """
    lines: list[str] = []
    for text in texts:
        if not text:
            continue
        # Newline-separated (not html_to_text's space-joined) so each block/line
        # can be scanned and kept/dropped independently.
        raw_plain = BeautifulSoup(text, "html.parser").get_text(separator="\n", strip=True)
        plain = strip_fee_amounts(raw_plain) or ""
        for line in plain.splitlines():
            line = line.strip()
            if line and _CURRENCY_AMOUNT_RE.search(line):
                lines.append(line)

    # Cap by whole lines rather than a raw character slice — an arbitrary
    # mid-string cut can truncate a price literal (e.g. "€15" -> "€1"), which
    # would otherwise feed a spurious amount into the validation set built
    # from this digest (see _validate_llm_prices).
    kept: list[str] = []
    total_len = 0
    for line in lines:
        added_len = len(line) + (1 if kept else 0)  # +1 for the joining "\n"
        if total_len + added_len > PRICE_CONTEXT_MAX_CHARS:
            break
        kept.append(line)
        total_len += added_len
    return "\n".join(kept)


def _coerce_float(value: Any) -> float | None:
    """Coerce a JSON-LD numeric field (number or numeric string) to float."""
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _jsonld_event_items(data: Any) -> list[dict[str, Any]]:
    """Flatten a parsed JSON-LD document (plain item, list, or ``@graph``) to dicts."""
    if isinstance(data, dict) and "@graph" in data:
        items = data["@graph"]
    else:
        items = data
    if not isinstance(items, list):
        items = [items]
    return [item for item in items if isinstance(item, dict)]


def extract_jsonld_event_location(soup: BeautifulSoup) -> dict[str, Any] | None:
    """Find a schema.org ``Event``'s ``location`` in <script type="application/ld+json">.

    Returns ``{"venue_name", "venue_address", "lat", "lng"}`` (any value may be
    ``None``) from the first ``Event`` whose ``location`` is a ``Place``, or
    ``None`` if no such block is found. ``venue_address`` joins
    ``streetAddress``/``addressLocality``/``addressRegion`` with ", ".
    """
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (TypeError, ValueError):
            continue
        for item in _jsonld_event_items(data):
            item_type = item.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]
            if "Event" not in types:
                continue
            location = item.get("location")
            if not isinstance(location, dict):
                continue
            address = location.get("address")
            address_parts: list[str] = []
            if isinstance(address, dict):
                for key in ("streetAddress", "addressLocality", "addressRegion"):
                    value = address.get(key)
                    if value:
                        address_parts.append(str(value))
            geo = location.get("geo")
            if isinstance(geo, dict):
                lat_raw = geo.get("latitude")
                lng_raw = geo.get("longitude")
            else:
                lat_raw = location.get("latitude")
                lng_raw = location.get("longitude")
            return {
                "venue_name": location.get("name"),
                "venue_address": ", ".join(address_parts) or None,
                "lat": _coerce_float(lat_raw),
                "lng": _coerce_float(lng_raw),
            }
    return None


def extract_jsonld_event_offers(
    soup: BeautifulSoup,
) -> tuple[float | None, float | None, str | None, bool]:
    """Return ``(min_price, max_price, currency, has_free_tier)`` from schema.org
    ``Event`` ``offers[]``.

    Reads all ``Offer`` entries from the first JSON-LD ``Event`` block. price_min/max
    bound the PAID offers only; a zero-priced offer whose ``availability`` is
    ``SoldOut`` is a placeholder (Fienta collapses a sold-out event to a single
    ``{price: 0, availability: SoldOut}`` offer) and is ignored entirely — not
    counted as paid or free. A genuine zero-priced, in-stock offer (e.g. a
    Member/Companion tier) sets ``has_free_tier`` alongside any paid offers found.
    Returns ``(None, None, None, False)`` when no offers or no usable prices are
    found in any Event block.
    """
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (TypeError, ValueError):
            continue
        for item in _jsonld_event_items(data):
            item_type = item.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]
            if "Event" not in types:
                continue
            offers_raw = item.get("offers") or []
            if isinstance(offers_raw, dict):
                offers_raw = [offers_raw]
            paid_prices: list[float] = []
            has_free_offer = False
            currency: str | None = None
            for offer in offers_raw:
                if not isinstance(offer, dict):
                    continue
                price = _coerce_float(offer.get("price"))
                if price is None:
                    continue
                availability = str(offer.get("availability") or "")
                sold_out = availability.endswith("SoldOut")
                if price == 0 and sold_out:
                    continue  # placeholder — not a real offer
                if price > 0:
                    paid_prices.append(price)
                    if currency is None:
                        cur_raw = offer.get("priceCurrency")
                        if cur_raw:
                            currency = str(cur_raw).upper()
                else:
                    has_free_offer = True
            if paid_prices:
                return (min(paid_prices), max(paid_prices), currency, has_free_offer)
            if has_free_offer:
                return (0.0, 0.0, None, False)
            continue  # nothing usable in this block — try next Event item
    return (None, None, None, False)


def extract_jsonld_event_text(soup: BeautifulSoup) -> tuple[str | None, str | None]:
    """Return ``(name, description)`` from the first schema.org ``Event`` JSON-LD block.

    Falls back to the page ``<h1>`` for name when the JSON-LD block has no ``name``
    field. Returns ``(None, None)`` when no ``Event`` block is found.
    """
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (TypeError, ValueError):
            continue
        for item in _jsonld_event_items(data):
            item_type = item.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]
            if "Event" not in types:
                continue
            name_raw = item.get("name")
            name: str | None = name_raw.strip()[:LOCALIZED_TEXT_MAX_TITLE_CHARS] or None if isinstance(name_raw, str) else None
            desc_raw = item.get("description")
            desc: str | None = desc_raw.strip()[:LOCALIZED_TEXT_MAX_DESC_CHARS] or None if isinstance(desc_raw, str) else None
            if name is None:
                h1 = soup.find("h1")
                if h1:
                    name = h1.get_text(strip=True) or None
            return (name, desc)
    return (None, None)


def locale_from_url_path(url: str, locales: frozenset[str]) -> str | None:
    """Return the locale code found as a path segment in url, or None.

    Detects locale from URL structure (e.g. ``/en/event-slug`` → ``"en"``).
    Used to identify which locale an already-loaded page represents so
    callers can reuse its soup instead of re-fetching by URL equality.
    """
    path = urlsplit(url).path
    for segment in path.strip("/").split("/"):
        if segment.lower() in locales:
            return segment.lower()
    return None


def locale_from_html_lang(soup: BeautifulSoup, locales: frozenset[str]) -> str | None:
    """Return the page's <html lang> locale if it is one of `locales`, else None."""
    html_tag = soup.find("html")
    lang = html_tag.get("lang") if html_tag else None
    if isinstance(lang, list):
        lang = lang[0] if lang else None
    if not lang:
        return None
    lang = lang.lower()
    norm = LOCALIZED_TEXT_HREFLANG_NORMALIZE.get(lang, lang.split("-")[0])
    return norm if norm in locales else None


def localized_detail_urls(
    soup: BeautifulSoup,
    base_url: str,
    target_locales: frozenset[str],
) -> dict[str, str]:
    """Return a ``{locale: absolute_url}`` map for each wanted locale found in the page.

    Reads ``<link rel="alternate" hreflang="…" href="…">`` tags and normalises
    hreflang values via LOCALIZED_TEXT_HREFLANG_NORMALIZE.  Falls back to
    ``<a>`` language-switcher anchors whose ``hreflang`` attribute is set.
    Only locales present in ``target_locales`` are returned.
    """
    from urllib.parse import urljoin

    def _str_attr(tag: Any, name: str) -> str:
        val = tag.get(name) or ""
        if isinstance(val, list):
            return val[0] if val else ""
        return val

    result: dict[str, str] = {}
    for tag in soup.find_all("link", rel="alternate"):
        lang = _str_attr(tag, "hreflang")
        if not lang:
            continue
        lang_norm = LOCALIZED_TEXT_HREFLANG_NORMALIZE.get(lang.lower(), lang.lower())
        if lang_norm not in target_locales:
            continue
        href = _str_attr(tag, "href")
        if href:
            result[lang_norm] = urljoin(base_url, href)
    if not result:
        # Fallback: language-switcher <a hreflang="…"> anchors
        for tag in soup.find_all("a", hreflang=True):
            lang = _str_attr(tag, "hreflang")
            lang_norm = LOCALIZED_TEXT_HREFLANG_NORMALIZE.get(lang.lower(), lang.lower())
            if lang_norm not in target_locales:
                continue
            href = _str_attr(tag, "href")
            if href and lang_norm not in result:
                result[lang_norm] = urljoin(base_url, href)
    return result


def coords_in_estonia(lat: float, lng: float) -> bool:
    """Return True when (lat, lng) falls within Estonia's bounding box."""
    lat_min, lat_max, lng_min, lng_max = ESTONIA_BBOX
    return lat_min <= lat <= lat_max and lng_min <= lng <= lng_max


def coords_in_tallinn(lat: float, lng: float) -> bool:
    """Return True when (lat, lng) falls within the greater-Tallinn bounding box."""
    lat_min, lat_max, lng_min, lng_max = TALLINN_REGION_BBOX
    return lat_min <= lat <= lat_max and lng_min <= lng <= lng_max


class SourceAdapter(ABC):
    def __init__(self, source: Source) -> None:
        self.source = source

    @abstractmethod
    async def fetch_raw(self, known_ids: set[str]) -> list[dict[str, Any]]: ...

    @abstractmethod
    def normalize(self, raw: dict[str, Any]) -> NormalizedEvent | None: ...

    def get_raw_external_id(self, raw: dict[str, Any]) -> str | None:
        """Extract the external ID to store on RawEvent. Override for non-'id' key sources."""
        v = raw.get("id", "")
        return str(v) if v else None

    async def run(self, db: AsyncSession) -> IngestionRun:
        """Execute full pipeline: fetch → raw_events → normalize → events(draft).

        NOTE: the caller is responsible for committing or rolling back the session.
        On error, run.error is populated but the caller must still commit to persist
        the failure record (instead of rolling back the entire transaction).
        """
        known_ids = await ingest_skip_ids(db, self.source.id)
        # Release the connection for the crawl below — fetch_raw is network I/O only
        # (no db access), often taking minutes, which would otherwise hold a checked-out
        # connection idle past Neon's auto-suspend window. Nothing has been written yet,
        # so this is a no-op beyond ending the transaction and returning the connection
        # to the pool. Must be commit(), not rollback(): Session.rollback() unconditionally
        # expires every ORM object in the identity map regardless of expire_on_commit,
        # which would make every later `self.source.*` read below (and in fetch_raw()
        # overrides) trigger an implicit lazy-load — disallowed under AsyncSession outside
        # the greenlet-spawn context (raises MissingGreenlet). commit() respects
        # expire_on_commit=False (app/db.py), so self.source stays usable.
        await db.commit()

        # Captured before the crawl: the IngestionRun row is now inserted after
        # fetch_raw() completes, so started_at's server_default=func.now() would
        # otherwise record crawl-end instead of crawl-start, silently losing the
        # one timestamp this audit column exists to track.
        started_at = datetime.now(tz=TALLINN_TZ)
        run = IngestionRun(source_id=self.source.id, started_at=started_at)

        try:
            raw_items = await self.fetch_raw(known_ids)
            db.add(run)
            await db.flush()
            run.raw_count = len(raw_items)
            new_count = 0
            seen_external_ids: set[str] = set()

            for raw in raw_items:
                raw_event = RawEvent(
                    source_id=self.source.id,
                    external_id=self.get_raw_external_id(raw),
                    payload=raw,
                )
                db.add(raw_event)
                await db.flush()

                normalized = self.normalize(raw)
                if normalized is None or not normalized.external_id:
                    continue

                if normalized.external_id in seen_external_ids:
                    raw_event.processed_at = datetime.now(tz=TALLINN_TZ)
                    continue

                existing = await db.scalar(
                    select(EventSource).where(
                        EventSource.source_id == self.source.id,
                        EventSource.external_id == normalized.external_id,
                    )
                )
                if existing:
                    raw_event.processed_at = datetime.now(tz=TALLINN_TZ)
                    continue

                slug = _make_slug(
                    normalized.title, normalized.starts_at, normalized.external_id
                )
                try:
                    async with db.begin_nested():
                        event = Event(
                            slug=slug,
                            title_orig=normalized.title,
                            description_orig=normalized.description,
                            important_info=normalized.important_info,
                            starts_at=normalized.starts_at,
                            ends_at=normalized.ends_at,
                            venue_name=normalized.venue_name,
                            venue_address=normalized.venue_address,
                            lat=normalized.lat,
                            lng=normalized.lng,
                            url=safe_external_url(normalized.url, self.source.slug),
                            image_url=safe_external_url(
                                normalized.image_url, self.source.slug
                            ),
                            price_min=normalized.price_min,
                            price_max=normalized.price_max,
                            currency=normalized.currency,
                            price_hint=normalized.price_hint,
                            has_free_tier=normalized.has_free_tier,
                            title_localized=normalized.title_localized,
                            description_localized=normalized.description_localized,
                            important_info_localized=normalized.important_info_localized,
                            status=EVENT_STATUS_DRAFT,
                            is_explicit=is_explicit_text(
                                normalized.title,
                                normalized.description,
                                normalized.venue_name,
                                normalized.important_info,
                            ),
                            is_non_event=is_non_event_text(
                                normalized.title,
                                normalized.venue_name,
                            ),
                        )
                        db.add(event)
                        await db.flush()
                        db.add(
                            EventSource(
                                event_id=event.id,
                                source_id=self.source.id,
                                external_id=normalized.external_id,
                            )
                        )
                except IntegrityError:
                    log.warning(
                        "slug collision source=%s external_id=%s slug=%s — skipped",
                        self.source.slug,
                        normalized.external_id,
                        slug,
                    )
                    continue

                raw_event.processed_at = datetime.now(tz=TALLINN_TZ)
                seen_external_ids.add(normalized.external_id)
                new_count += 1

            finished_at = datetime.now(tz=TALLINN_TZ)
            run.new_count = new_count
            run.finished_at = finished_at
            self.source.last_run_at = finished_at
            self.source.last_status = SOURCE_STATUS_OK

        except Exception as exc:
            run.error = str(exc)[:INGESTION_ERROR_MAX_LEN]
            self.source.last_status = SOURCE_STATUS_ERROR
            if run.id is None:
                # fetch_raw failed before the persist phase flushed run — it
                # was never added to the session, so add it now to record the
                # error (the caller still expects an IngestionRun row).
                db.add(run)
                await db.flush()
            raise

        return run
