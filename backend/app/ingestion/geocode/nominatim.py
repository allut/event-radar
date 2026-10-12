"""Nominatim lookup: address normalization + the bbox-gated geocode call."""

import logging
import re

import httpx

from app.constants.ingestion import (
    CONTENT_FILTER_WHITESPACE_COLLAPSE_RE,
    ESTONIAN_STREET_TYPE_WORDS,
    GEOCODE_COUNTRY_SUFFIX,
    GEOCODE_COUNTY_RE,
    GEOCODE_FLOOR_RE,
    GEOCODE_INITIAL_RE,
    GEOCODE_SECONDARY_UNIT_RE,
    GEOCODE_UNIT_SUFFIX_RE,
    NOMINATIM_BASE_URL,
    NOMINATIM_QUERY_PARAMS,
    NOMINATIM_USER_AGENT,
)
from app.ingestion.adapter import coords_in_tallinn
from app.ingestion.http_client import http_get
from app.ingestion.patterns import alternation_pattern

log = logging.getLogger(__name__)

# Pre-compiled patterns built from constants - avoids re-compiling per call.
_STREET_TYPE_PATTERN = alternation_pattern(ESTONIAN_STREET_TYPE_WORDS)
_INITIAL_RE = re.compile(GEOCODE_INITIAL_RE)
_UNIT_SUFFIX_RE = re.compile(GEOCODE_UNIT_SUFFIX_RE, re.IGNORECASE)
_FLOOR_RE = re.compile(GEOCODE_FLOOR_RE, re.IGNORECASE)
_COUNTY_RE = re.compile(GEOCODE_COUNTY_RE, re.IGNORECASE)
_SECONDARY_UNIT_RE = re.compile(GEOCODE_SECONDARY_UNIT_RE, re.IGNORECASE)
_WHITESPACE_COLLAPSE_PATTERN = re.compile(CONTENT_FILTER_WHITESPACE_COLLAPSE_RE)


def normalize_address_for_geocoding(address: str) -> str:
    """Return a Nominatim-friendly version of a Fienta venue_address.

    Strips Estonian street-type words entirely (OSM stores streets by bare name,
    so the type word is what makes the match fail), drops a leading personal-name
    initial, unit suffixes, floor notes, and county markers, then appends
    ", Estonia" to anchor country matching. The whitespace-collapse cleans up the
    gaps left by stripping. The stored venue_address is never mutated — query-only.
    """
    result = address
    result = _INITIAL_RE.sub("", result)
    result = _FLOOR_RE.sub("", result)
    result = _COUNTY_RE.sub("", result)
    result = _SECONDARY_UNIT_RE.sub("", result)
    result = _UNIT_SUFFIX_RE.sub("", result)
    result = _STREET_TYPE_PATTERN.sub("", result)
    result = _WHITESPACE_COLLAPSE_PATTERN.sub(" ", result).strip().rstrip(",").strip()
    if not result.endswith(GEOCODE_COUNTRY_SUFFIX):
        result += GEOCODE_COUNTRY_SUFFIX
    return result


async def geocode_address(
    client: httpx.AsyncClient, address: str, original: str | None = None
) -> tuple[float, float] | None:
    """Look up an address via Nominatim, returning ``(lat, lng)`` or None if no match.

    ``address`` is the normalized query sent to Nominatim.
    ``original`` is the raw venue_address (used only in the no-match log line).

    A result outside ``TALLINN_REGION_BBOX`` is treated as no match (logged +
    discarded, not stored) — a bare district/place name can collide with an
    identically-named place elsewhere in Estonia (e.g. Tallinn's Kopli district
    vs. a Kopli village on Saaremaa), and the publish gate's own bbox backstop
    would reject the wrong coord anyway. Leaving the event coords-less instead
    lets it through the publish gate's coords-less branch.
    """
    response = await http_get(
        client,
        NOMINATIM_BASE_URL,
        params={"q": address, **NOMINATIM_QUERY_PARAMS},
        headers={"User-Agent": NOMINATIM_USER_AGENT},
    )
    try:
        results = response.json()
        if not results:
            log.warning(
                "geocode no match: query=%r original=%r",
                address,
                original or address,
            )
            return None
        lat, lng = float(results[0]["lat"]), float(results[0]["lon"])
    except (KeyError, TypeError, ValueError):
        return None
    if not coords_in_tallinn(lat, lng):
        log.warning(
            "geocode out-of-bbox match discarded: query=%r original=%r lat=%s lng=%s",
            address,
            original or address,
            lat,
            lng,
        )
        return None
    return lat, lng
