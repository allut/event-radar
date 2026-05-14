"""Live integration tests for PiletileviAdapter — hits real piletilevi.ee.

Run with:
    cd backend
    python3 -m pytest tests/ingestion/test_piletilevi_live.py -v -s -m live

Tests verify:
- fetch_raw() returns Tallinn events with required fields
- Tallinn city filter is working (no non-Tallinn events leaked)
- Deduplication works across listing pages (no duplicate hrefs)
- Detail-page description fetch is working
- normalize() succeeds on all fetched events
- Normalized events have tz-aware starts_at in Europe/Tallinn
- URLs are absolute and point to piletilevi.ee
- CSS selectors match real piletilevi.ee markup (selector validity)
- All raw field types are correct (data extraction correctness)
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
import pytest_asyncio
from bs4 import BeautifulSoup

from app.constants import (
    HTTP_TIMEOUT_SECONDS,
    HTTP_USER_AGENT,
    PILETILEVI_BASE_URL,
    PILETILEVI_LISTING_URLS,
    PILETILEVI_TALLINN_FILTER,
    TALLINN_TZ,
)
from app.ingestion.sources.piletilevi import (
    PiletileviAdapter,
    _CARD_SELECTOR,
    _DATE_SELECTOR,
    _DETAIL_DESC_SELECTOR,
    _IMAGE_SELECTOR,
    _TITLE_SELECTOR,
    _VENUE_SELECTOR,
)

pytestmark = pytest.mark.live

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_source() -> MagicMock:
    source = MagicMock()
    source.slug = "piletilevi"
    source.config = {}
    return source


def _adapter() -> PiletileviAdapter:
    return PiletileviAdapter(_make_source())


# Module-level cache — fetch once, reuse across all tests in the module.
# Safe because pytest runs tests sequentially and the cache value is a plain list.
_raw_events_cache: list[dict[str, Any]] | None = None


@pytest_asyncio.fixture
async def live_raw_events() -> list[dict[str, Any]]:
    global _raw_events_cache
    if _raw_events_cache is not None:
        return _raw_events_cache
    adapter = _adapter()
    try:
        _raw_events_cache = await adapter.fetch_raw()
    except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError) as exc:
        pytest.skip(f"piletilevi.ee unreachable: {exc}")
    return _raw_events_cache


# ---------------------------------------------------------------------------
# fetch_raw() — live listing + detail pages
# ---------------------------------------------------------------------------


class TestLiveFetchRaw:
    async def test_returns_at_least_one_event(self, live_raw_events):
        assert len(live_raw_events) > 0, "expected events from piletilevi.ee listing pages"

    async def test_all_events_have_href(self, live_raw_events):
        missing = [ev for ev in live_raw_events if not ev.get("href")]
        assert not missing, f"{len(missing)} events missing href"

    async def test_all_events_have_title(self, live_raw_events):
        missing = [ev for ev in live_raw_events if not ev.get("title")]
        assert not missing, f"{len(missing)} events missing title"

    async def test_all_events_have_date_str(self, live_raw_events):
        missing = [ev for ev in live_raw_events if not ev.get("date_str")]
        assert not missing, f"{len(missing)} events missing date_str"

    async def test_hrefs_are_unique(self, live_raw_events):
        from collections import Counter
        counts = Counter(ev["href"] for ev in live_raw_events)
        dupes = [h for h, n in counts.items() if n > 1]
        assert not dupes, f"duplicate hrefs (dedup failed): {dupes[:5]}"

    async def test_hrefs_are_piletilevi_ticket_paths(self, live_raw_events):
        # CSS selector uses *=contains, so align assertion the same way
        bad = [ev["href"] for ev in live_raw_events if "/en/tickets/" not in ev["href"]]
        assert not bad, f"unexpected href format: {bad[:5]}"

    async def test_tallinn_filter_applied(self, live_raw_events):
        """Events with a venue string must contain 'Tallinn'."""
        non_tallinn = [
            ev for ev in live_raw_events
            if ev.get("venue") and PILETILEVI_TALLINN_FILTER not in ev["venue"]
        ]
        assert not non_tallinn, (
            f"{len(non_tallinn)} non-Tallinn events leaked filter: "
            f"{[e['venue'] for e in non_tallinn[:5]]}"
        )

    async def test_some_events_have_descriptions(self, live_raw_events):
        """Detail-page fetch must populate at least one description."""
        with_desc = [ev for ev in live_raw_events if ev.get("description")]
        assert len(with_desc) > 0, "no events have descriptions — detail-page fetch likely broken"

    async def test_description_is_non_empty_string(self, live_raw_events):
        for ev in live_raw_events:
            if ev.get("description") is not None:
                assert isinstance(ev["description"], str), f"description not a string: {ev['title']}"
                assert ev["description"].strip(), f"description is blank: {ev['title']}"


# ---------------------------------------------------------------------------
# normalize() — verify all live raw events survive normalization
# ---------------------------------------------------------------------------


class TestLiveNormalize:
    async def test_all_events_normalize_without_returning_none(self, live_raw_events):
        adapter = _adapter()
        failed = [ev for ev in live_raw_events if adapter.normalize(ev) is None]
        assert not failed, (
            f"normalize() returned None for {len(failed)} events: "
            f"{[e['title'] for e in failed[:5]]}"
        )

    async def test_normalized_starts_at_is_tz_aware_tallinn(self, live_raw_events):
        adapter = _adapter()
        for raw in live_raw_events:
            result = adapter.normalize(raw)
            if result is None:
                continue
            assert result.starts_at.utcoffset() is not None, f"starts_at not tz-aware: {raw['title']}"
            assert result.starts_at.tzinfo.key == "Europe/Tallinn", (
                f"expected Europe/Tallinn zone, got {result.starts_at.tzinfo}: {raw['title']}"
            )

    async def test_normalized_urls_are_absolute_piletilevi(self, live_raw_events):
        adapter = _adapter()
        for raw in live_raw_events:
            result = adapter.normalize(raw)
            if result is None:
                continue
            assert result.url.startswith(PILETILEVI_BASE_URL), (
                f"url not absolute piletilevi.ee URL: {result.url}"
            )

    async def test_normalized_titles_match_raw(self, live_raw_events):
        adapter = _adapter()
        for raw in live_raw_events:
            result = adapter.normalize(raw)
            if result is None:
                continue
            assert result.title == raw["title"], (
                f"title mismatch: raw={raw['title']!r} normalized={result.title!r}"
            )

    async def test_normalized_external_ids_match_href(self, live_raw_events):
        adapter = _adapter()
        for raw in live_raw_events:
            result = adapter.normalize(raw)
            if result is None:
                continue
            assert result.external_id == raw["href"], (
                f"external_id != href: {result.external_id!r} vs {raw['href']!r}"
            )

    async def test_most_events_are_upcoming(self, live_raw_events):
        """Piletilevi only lists upcoming events; allow ≤5% past (multi-day events)."""
        adapter = _adapter()
        now = datetime.now(tz=TALLINN_TZ)
        past = []
        total = 0
        for raw in live_raw_events:
            result = adapter.normalize(raw)
            if result is None:
                continue
            total += 1
            if result.starts_at < now:
                past.append(result.title)
        if past and total > 0:
            ratio = len(past) / total
            assert ratio < 0.05, (
                f"{len(past)}/{total} events appear to be in the past: {past[:5]}"
            )


# ---------------------------------------------------------------------------
# CSS selector validity — verify selectors match real piletilevi.ee markup
# ---------------------------------------------------------------------------

# Fetch one listing page and cache the parsed soup for selector tests.
# Module-level cache matches the _raw_events_cache pattern already in this file;
# pytest imports each module once per process so the cache is safe for sequential runs.
_listing_soup_cache: BeautifulSoup | None = None


@pytest_asyncio.fixture
async def listing_soup() -> BeautifulSoup:
    global _listing_soup_cache
    if _listing_soup_cache is not None:
        return _listing_soup_cache
    url = PILETILEVI_BASE_URL + PILETILEVI_LISTING_URLS[0]
    try:
        async with httpx.AsyncClient(
            timeout=HTTP_TIMEOUT_SECONDS,
            follow_redirects=True,
            headers={"User-Agent": HTTP_USER_AGENT},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError) as exc:
        pytest.skip(f"piletilevi.ee unreachable: {exc}")
    _listing_soup_cache = BeautifulSoup(resp.text, "html.parser")
    return _listing_soup_cache


@pytest_asyncio.fixture
async def first_live_card(listing_soup: BeautifulSoup) -> Any:
    cards = listing_soup.select(_CARD_SELECTOR)
    if not cards:
        pytest.skip("no cards found on listing page — site layout may have changed")
    return cards[0]


class TestLiveCSSSelectorValidity:
    """Directly verify each CSS selector against live piletilevi.ee HTML.

    A test failure here means the site changed its markup and the adapter
    will silently return empty/incomplete data.
    """

    async def test_card_selector_matches_elements(self, listing_soup):
        """_CARD_SELECTOR must find at least one event card on the listing page."""
        cards = listing_soup.select(_CARD_SELECTOR)
        assert len(cards) > 0, (
            f"selector {_CARD_SELECTOR!r} matched nothing — site markup changed"
        )

    async def test_title_selector_matches_within_card(self, first_live_card):
        """_TITLE_SELECTOR must find an h3 inside an event card."""
        tag = first_live_card.select_one(_TITLE_SELECTOR)
        assert tag is not None, (
            f"selector {_TITLE_SELECTOR!r} matched nothing inside card — site markup changed"
        )
        assert tag.get_text(strip=True), "title element found but text is empty"

    async def test_date_selector_matches_within_card(self, first_live_card):
        """_DATE_SELECTOR must find the date element inside an event card."""
        tag = first_live_card.select_one(_DATE_SELECTOR)
        assert tag is not None, (
            f"selector {_DATE_SELECTOR!r} matched nothing inside card — site markup changed"
        )
        assert tag.get_text(strip=True), "date element found but text is empty"

    async def test_venue_selector_matches_within_card(self, first_live_card):
        """_VENUE_SELECTOR must find the venue/description element inside an event card."""
        tag = first_live_card.select_one(_VENUE_SELECTOR)
        assert tag is not None, (
            f"selector {_VENUE_SELECTOR!r} matched nothing inside card — site markup changed"
        )

    async def test_image_selector_matches_within_card(self, first_live_card):
        """_IMAGE_SELECTOR must find an image tag inside an event card."""
        tag = first_live_card.select_one(_IMAGE_SELECTOR)
        assert tag is not None, (
            f"selector {_IMAGE_SELECTOR!r} matched nothing inside card — site markup changed"
        )

    async def test_detail_desc_selector_matches_on_detail_page(self, live_raw_events):
        """_DETAIL_DESC_SELECTOR must match on at least one live detail page."""
        if not live_raw_events:
            pytest.skip("no live events to test detail page selector")
        # Use first event that has a non-None description — proves the selector worked.
        events_with_desc = [ev for ev in live_raw_events if ev.get("description")]
        assert events_with_desc, (
            f"selector {_DETAIL_DESC_SELECTOR!r} matched nothing on any detail page"
        )
        # Spot-check: fetch the first event's detail page directly and confirm selector hit.
        first_href = events_with_desc[0]["href"]
        detail_url = PILETILEVI_BASE_URL + first_href
        try:
            async with httpx.AsyncClient(
                timeout=HTTP_TIMEOUT_SECONDS,
                follow_redirects=True,
                headers={"User-Agent": HTTP_USER_AGENT},
            ) as client:
                resp = await client.get(detail_url)
                resp.raise_for_status()
        except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError) as exc:
            pytest.skip(f"detail page unreachable: {exc}")
        detail_soup = BeautifulSoup(resp.text, "html.parser")
        desc_tag = detail_soup.select_one(_DETAIL_DESC_SELECTOR)
        assert desc_tag is not None, (
            f"selector {_DETAIL_DESC_SELECTOR!r} matched nothing on detail page {detail_url}"
        )
        assert desc_tag.get_text(separator=" ", strip=True), (
            f"description element found but text is empty on {detail_url}"
        )


# ---------------------------------------------------------------------------
# Data extraction correctness — field types and format invariants
# ---------------------------------------------------------------------------


class TestLiveDataExtraction:
    """Verify raw field types and formats match what normalize() and downstream expect."""

    async def test_image_url_field_type(self, live_raw_events):
        """image_url must be a string or None — never another type."""
        for ev in live_raw_events:
            img = ev.get("image_url")
            assert img is None or isinstance(img, str), (
                f"image_url is {type(img).__name__} for {ev['title']!r}"
            )

    async def test_some_events_have_image_urls(self, live_raw_events):
        """_IMAGE_SELECTOR must populate image_url on at least some events."""
        with_img = [ev for ev in live_raw_events if ev.get("image_url")]
        assert with_img, "no events have image_url — _IMAGE_SELECTOR or src/data-src attr missing"

    async def test_image_urls_become_absolute_after_normalize(self, live_raw_events):
        """Relative /... image paths must be made absolute by normalize()."""
        adapter = _adapter()
        for raw in live_raw_events:
            result = adapter.normalize(raw)
            if result is None or not result.image_url:
                continue
            assert result.image_url.startswith("http"), (
                f"image_url is not absolute after normalize: {result.image_url!r}"
            )

    async def test_date_str_format_matches_parser_expectation(self, live_raw_events):
        """date_str must match 'We 19.08.2026 • 19:00' — bullet separator required."""
        bad = [
            ev for ev in live_raw_events
            if ev.get("date_str") and "•" not in ev["date_str"]
        ]
        assert not bad, (
            f"{len(bad)} events have date_str without '•' separator — "
            f"_parse_piletilevi_date will return None: {[e['date_str'] for e in bad[:5]]}"
        )

    async def test_date_str_contains_time_component(self, live_raw_events):
        """date_str must include a time in HH:MM format."""
        time_re = re.compile(r"\d{2}:\d{2}")
        bad = [
            ev for ev in live_raw_events
            if ev.get("date_str") and not time_re.search(ev["date_str"])
        ]
        assert not bad, (
            f"{len(bad)} events have date_str without HH:MM time: "
            f"{[e['date_str'] for e in bad[:5]]}"
        )

    async def test_venue_field_type(self, live_raw_events):
        """venue must be a string (possibly empty) or absent — never another type."""
        for ev in live_raw_events:
            venue = ev.get("venue")
            assert venue is None or isinstance(venue, str), (
                f"venue is {type(venue).__name__} for {ev['title']!r}"
            )

    async def test_href_starts_with_slash(self, live_raw_events):
        """href values are relative paths — normalize() prepends PILETILEVI_BASE_URL."""
        bad = [ev for ev in live_raw_events if not ev.get("href", "").startswith("/")]
        assert not bad, (
            f"{len(bad)} hrefs are not relative paths (normalize will produce bad URLs): "
            f"{[e['href'] for e in bad[:5]]}"
        )
