"""Tests for HtmlListingAdapter base + Piletilevi/Kumu/EstoniaConcertHall."""
import base64
import json as json_module
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest
import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.constants import TALLINN_TZ
from app.ingestion.selectors import (
    ECH_SITE_TITLE_SUFFIX,
    ESTONIA_CONCERT_HALL_AJAX_ACTION,
    ESTONIA_CONCERT_HALL_AJAX_PATH,
    ESTONIA_CONCERT_HALL_MAX_EVENTS,
    ESTONIA_CONCERT_HALL_PILETILEVI_URL,
    ESTONIA_CONCERT_HALL_VENUES,
    KUMU_SITE_TITLE_SUFFIX,
    KUMU_VENUE_ADDRESS,
    KUMU_VENUE_LAT,
    KUMU_VENUE_LNG,
    KUMU_VENUE_NAME,
    PILETILEVI_LOGIN_EXPRESS_URL,
    PILETILEVI_PRICES_URL,
)
from app.ingestion.adapter import NormalizedEvent
from app.ingestion.sources.estonia_concert_hall import (
    EstoniaConcertHallAdapter,
    estonia_concert_hall_localized_text,
)
from app.ingestion.sources.html_base import (
    HtmlListingAdapter,
    ListingRequest,
    full_res_wp_image,
    next_occurrence_year,
)
from app.ingestion.sources.kumu import KumuAdapter, kumu_localized_text
from app.ingestion.sources.piletilevi import (
    PiletileviAdapter,
    _parse_piletilevi_date,
    _piletilevi_important_info,
    _price_bounds_from_store,
    full_res_piletilevi_image,
    piletilevi_localized_text,
)


def _make_source(slug: str = "test-source", url: str = "https://example.test/listing"):
    source = MagicMock()
    source.slug = slug
    source.config = {"url": url}
    return source


def _mock_response(text: str, status: int = 200):
    resp = MagicMock(spec=httpx.Response)
    resp.text = text
    resp.status_code = status
    return resp


def _known_ids(known_ids=()):
    return set(known_ids)


# ---------------------------------------------------------------------------
# next_occurrence_year
# ---------------------------------------------------------------------------


class TestNextOccurrenceYear:
    def test_future_date_this_year(self):
        assert next_occurrence_year(12, 2, today=date(2026, 6, 12)) == 2026

    def test_past_date_rolls_to_next_year(self):
        assert next_occurrence_year(5, 30, today=date(2026, 6, 12)) == 2027

    def test_today_itself_stays_this_year(self):
        assert next_occurrence_year(6, 12, today=date(2026, 6, 12)) == 2026


# ---------------------------------------------------------------------------
# Base HtmlListingAdapter — pagination, dedup, partial tolerance, detail cap
# ---------------------------------------------------------------------------


class _StubAdapter(HtmlListingAdapter):
    """Minimal adapter for exercising the base fetch_raw loop in isolation."""

    def __init__(self, source, pages_cards, needs_detail=False, max_pages=1):
        super().__init__(source)
        self._pages_cards = pages_cards
        self.needs_detail = needs_detail
        self.max_pages = max_pages

    def listing_url_for_page(self, page):
        if page > len(self._pages_cards):
            return None
        return f"https://example.test/page{page}"

    def parse_cards(self, soup):
        idx = int(soup.get_text(strip=True))
        return self._pages_cards[idx]

    def parse_date(self, card):
        return datetime(2026, 1, 1, tzinfo=TALLINN_TZ)

    async def parse_detail(self, client, soup, card):
        card["description"] = soup.get_text(strip=True)


class _PostStubAdapter(HtmlListingAdapter):
    """Adapter exercising the POST dispatch via ``listing_request``."""

    def __init__(self, source, cards):
        super().__init__(source)
        self._cards = cards
        self.max_pages = 1

    def listing_request(self, page):
        if page != 1:
            return None
        return ListingRequest(
            url="https://example.test/ajax", method="POST", data={"a": "1"}
        )

    def parse_cards(self, soup):
        return self._cards

    def parse_date(self, card):
        return datetime(2026, 1, 1, tzinfo=TALLINN_TZ)


class TestBasePagination:
    @pytest.mark.asyncio
    async def test_single_page_default_stops_after_one_fetch(self):
        card_a = {"external_id": "a", "title": "A", "url": "https://example.test/a"}
        adapter = _StubAdapter(_make_source(), pages_cards=[[card_a]], max_pages=1)

        with patch("app.ingestion.sources.html_base.http_get") as mock_get:
            mock_get.side_effect = [_mock_response("0")]
            results = await adapter.fetch_raw(_known_ids())

        assert mock_get.call_count == 1
        assert [c["external_id"] for c in results] == ["a"]

    @pytest.mark.asyncio
    async def test_pagination_stops_on_zero_new_cards(self):
        card_a = {"external_id": "a", "title": "A", "url": "https://example.test/a"}
        card_b = {"external_id": "b", "title": "B", "url": "https://example.test/b"}
        adapter = _StubAdapter(
            _make_source(),
            pages_cards=[[card_a, card_b], [card_a, card_b]],
            max_pages=5,
        )

        with patch("app.ingestion.sources.html_base.http_get") as mock_get:
            mock_get.side_effect = [_mock_response("0"), _mock_response("1")]
            results = await adapter.fetch_raw(_known_ids())

        # Page 2 yields no new cards (all already seen) → loop halts before page 3
        assert mock_get.call_count == 2
        assert [c["external_id"] for c in results] == ["a", "b"]

    @pytest.mark.asyncio
    async def test_pagination_dedup_across_pages(self):
        card_a = {"external_id": "a", "title": "A", "url": "https://example.test/a"}
        card_b = {"external_id": "b", "title": "B", "url": "https://example.test/b"}
        adapter = _StubAdapter(
            _make_source(),
            pages_cards=[[card_a], [card_a, card_b]],
            max_pages=5,
        )

        with patch("app.ingestion.sources.html_base.http_get") as mock_get:
            mock_get.side_effect = [_mock_response("0"), _mock_response("1")]
            results = await adapter.fetch_raw(_known_ids())

        assert mock_get.call_count == 2
        assert [c["external_id"] for c in results] == ["a", "b"]

    @pytest.mark.asyncio
    async def test_listing_error_raises_when_no_cards_collected(self):
        adapter = _StubAdapter(_make_source(), pages_cards=[[]], max_pages=1)

        with patch("app.ingestion.sources.html_base.http_get") as mock_get:
            mock_get.side_effect = [httpx.ConnectError("boom")]
            with pytest.raises(httpx.ConnectError):
                await adapter.fetch_raw(_known_ids())

    @pytest.mark.asyncio
    async def test_listing_error_tolerated_when_other_pages_succeed(self):
        card_a = {"external_id": "a", "title": "A", "url": "https://example.test/a"}
        adapter = _StubAdapter(
            _make_source(),
            pages_cards=[[], [card_a]],
            max_pages=2,
        )

        with patch("app.ingestion.sources.html_base.http_get") as mock_get:
            mock_get.side_effect = [httpx.ConnectError("boom"), _mock_response("1")]
            results = await adapter.fetch_raw(_known_ids())

        assert [c["external_id"] for c in results] == ["a"]

    @pytest.mark.asyncio
    async def test_needs_detail_caps_and_fetches_detail_pages(self):
        card_a = {"external_id": "a", "title": "A", "url": "https://example.test/a"}
        card_b = {"external_id": "b", "title": "B", "url": "https://example.test/b"}
        card_c = {"external_id": "c", "title": "C", "url": "https://example.test/c"}
        adapter = _StubAdapter(
            _make_source(),
            pages_cards=[[card_a, card_b, card_c]],
            needs_detail=True,
            max_pages=5,
        )

        with patch("app.ingestion.sources.html_base.HTML_LISTING_MAX_DETAIL_FETCHES", 2), \
             patch("app.ingestion.sources.html_base.http_get") as mock_get:
            mock_get.side_effect = [
                _mock_response("0"),  # listing page 1
                _mock_response("detail-a"),  # detail for card a
                _mock_response("detail-b"),  # detail for card b
            ]
            results = await adapter.fetch_raw(_known_ids())

        # Detail cap (2) truncates the 3 collected cards before detail fetches
        assert [c["external_id"] for c in results] == ["a", "b"]
        assert results[0]["description"] == "detail-a"
        assert results[1]["description"] == "detail-b"
        assert mock_get.call_count == 3

    @pytest.mark.asyncio
    async def test_known_ids_skip_does_not_consume_detail_cap(self):
        card_a = {"external_id": "a", "title": "A", "url": "https://example.test/a"}
        card_b = {"external_id": "b", "title": "B", "url": "https://example.test/b"}
        card_c = {"external_id": "c", "title": "C", "url": "https://example.test/c"}
        adapter = _StubAdapter(
            _make_source(),
            pages_cards=[[card_a, card_b], [card_c]],
            needs_detail=True,
            max_pages=2,
        )

        with patch("app.ingestion.sources.html_base.HTML_LISTING_MAX_DETAIL_FETCHES", 2), \
             patch("app.ingestion.sources.html_base.http_get") as mock_get:
            mock_get.side_effect = [
                _mock_response("0"),  # listing page 1 (a, b — both known)
                _mock_response("1"),  # listing page 2 (c — new)
                _mock_response("detail-c"),  # detail for card c
            ]
            results = await adapter.fetch_raw(_known_ids({"a", "b"}))

        # a/b are known: counted for pagination but never enter cards, so the
        # cap (2) is never spent on them and the run advances to page 2.
        assert [c["external_id"] for c in results] == ["c"]
        assert results[0]["description"] == "detail-c"
        assert mock_get.call_count == 3

    @pytest.mark.asyncio
    async def test_all_known_page_still_advances_pagination(self):
        card_a = {"external_id": "a", "title": "A", "url": "https://example.test/a"}
        card_b = {"external_id": "b", "title": "B", "url": "https://example.test/b"}
        adapter = _StubAdapter(
            _make_source(),
            pages_cards=[[card_a], [card_b]],
            max_pages=2,
        )

        with patch("app.ingestion.sources.html_base.http_get") as mock_get:
            mock_get.side_effect = [_mock_response("0"), _mock_response("1")]
            results = await adapter.fetch_raw(_known_ids({"a"}))

        # Page 1 is entirely known (new_ids_on_page=1, but 0 cards collected)
        # — pagination must still proceed to page 2 rather than treating the
        # known-only page as the end of the catalog.
        assert mock_get.call_count == 2
        assert [c["external_id"] for c in results] == ["b"]

    @pytest.mark.asyncio
    async def test_detail_fetch_failure_is_swallowed(self):
        card_a = {"external_id": "a", "title": "A", "url": "https://example.test/a"}
        adapter = _StubAdapter(
            _make_source(),
            pages_cards=[[card_a]],
            needs_detail=True,
            max_pages=1,
        )

        with patch("app.ingestion.sources.html_base.http_get") as mock_get:
            mock_get.side_effect = [
                _mock_response("0"),
                httpx.ConnectError("detail down"),
            ]
            results = await adapter.fetch_raw(_known_ids())

        assert [c["external_id"] for c in results] == ["a"]
        assert "description" not in results[0]


class TestBaseListingRequestDispatch:
    @pytest.mark.asyncio
    async def test_post_method_dispatches_to_http_post(self):
        card_a = {"external_id": "a", "title": "A", "url": "https://example.test/a"}
        adapter = _PostStubAdapter(_make_source(), cards=[card_a])

        with patch("app.ingestion.sources.html_base.http_post") as mock_post, \
             patch("app.ingestion.sources.html_base.http_get") as mock_get:
            mock_post.return_value = _mock_response("<html></html>")
            results = await adapter.fetch_raw(_known_ids())

        assert mock_get.call_count == 0
        assert mock_post.call_count == 1
        _, url = mock_post.call_args.args
        assert url == "https://example.test/ajax"
        assert mock_post.call_args.kwargs["data"] == {"a": "1"}
        assert [c["external_id"] for c in results] == ["a"]


class TestBaseNormalize:
    def test_missing_title_or_external_id_returns_none(self):
        adapter = _StubAdapter(_make_source(), pages_cards=[[]])
        assert adapter.normalize({"external_id": "x", "title": ""}) is None
        assert adapter.normalize({"external_id": "", "title": "X"}) is None

    def test_unparseable_date_returns_none(self):
        class _NoDateAdapter(_StubAdapter):
            def parse_date(self, card):
                return None

        adapter = _NoDateAdapter(_make_source(), pages_cards=[[]])
        result = adapter.normalize({"external_id": "x", "title": "X"})
        assert result is None

    def test_happy_path_builds_normalized_event(self):
        adapter = _StubAdapter(_make_source(), pages_cards=[[]])
        result = adapter.normalize(
            {
                "external_id": "x",
                "title": "X",
                "venue": "Venue",
                "description": "Desc",
                "image_url": "https://example.test/img.jpg",
                "url": "https://example.test/x",
            }
        )
        assert isinstance(result, NormalizedEvent)
        assert result.external_id == "x"
        assert result.venue_name == "Venue"
        assert result.description == "Desc"
        assert result.image_url == "https://example.test/img.jpg"
        assert result.url == "https://example.test/x"
        assert result.starts_at.tzinfo is not None

    def test_venue_address_and_coords_forwarded(self):
        adapter = _StubAdapter(_make_source(), pages_cards=[[]])
        result = adapter.normalize(
            {
                "external_id": "x",
                "title": "X",
                "venue_address": "Some Street 1, 10146 Tallinn",
                "lat": 59.437,
                "lng": 24.745,
            }
        )
        assert isinstance(result, NormalizedEvent)
        assert result.venue_address == "Some Street 1, 10146 Tallinn"
        assert result.lat == 59.437
        assert result.lng == 24.745

    def test_price_fields_forwarded(self):
        adapter = _StubAdapter(_make_source(), pages_cards=[[]])
        result = adapter.normalize(
            {
                "external_id": "x",
                "title": "X",
                "price_min": 10.0,
                "price_max": 30.0,
                "currency": "EUR",
            }
        )
        assert isinstance(result, NormalizedEvent)
        assert result.price_min == 10.0
        assert result.price_max == 30.0
        assert result.currency == "EUR"
        assert result.price_hint is None


# ---------------------------------------------------------------------------
# PiletileviAdapter — piletilevi.ee/en/tickets/all (Nuxt SSR markup)
# ---------------------------------------------------------------------------

PILETILEVI_LISTING_HTML = """
<html><body>
  <a class="card card--normal" href="/en/tickets/AA1/jazz-night">
    <div class="card__cover"><img class="card__image" src="https://www.piletilevi.ee/i/height=252/images/aa1.jpg"/></div>
    <div class="card__info">
      <div class="card__time-title"><div class="card__time">We 19.08.2026 • 19:00</div><h3>Jazz Night</h3></div>
      <div class="card__description">Jazz Club, Tallinn</div>
    </div>
  </a>
  <a class="card card--normal" href="/en/tickets/BB2/riga-rock">
    <div class="card__info">
      <div class="card__time-title"><div class="card__time">Fr 21.08.2026 • 20:00</div><h3>Riga Rock</h3></div>
      <div class="card__description">Rock Arena, Riga</div>
    </div>
  </a>
  <a class="card card--normal" href="/en/tickets/CC3/festival-pass">
    <div class="card__info">
      <div class="card__time-title"><div class="card__time">Th 11.06.2026 - Su 14.06.2026</div><h3>Festival Pass</h3></div>
      <div class="card__description">Outdoors, Tallinn</div>
    </div>
  </a>
</body></html>
"""

PILETILEVI_EMPTY_HTML = "<html><body></body></html>"

PILETILEVI_DETAIL_HTML = """
<html><body>
  <div class="event__description">A wonderful jazz evening with local musicians.</div>
</body></html>
"""

PILETILEVI_DETAIL_WITH_LOCATION_HTML = """
<html><head>
<script type="application/ld+json">
{"@type": "Event", "name": "Jazz Night", "location": {"@type": "Place", "name": "Jazz Club", "address": {"streetAddress": "Rataskaevu 10", "addressLocality": "Tallinn", "addressRegion": "Harju maakond"}, "latitude": 59.4372, "longitude": 24.7454}}
</script>
</head><body>
  <div class="event__description">A wonderful jazz evening with local musicians.</div>
</body></html>
"""

PILETILEVI_DETAIL_WITH_ARRAY_TYPE_AND_STRING_COORDS_HTML = """
<html><head>
<script type="application/ld+json">
{"@type": ["MusicEvent", "Event"], "name": "Jazz Night", "location": {"@type": "Place", "name": "Jazz Club", "address": {"streetAddress": "Rataskaevu 10", "addressLocality": "Tallinn", "addressRegion": "Harju maakond"}, "latitude": "59.4372", "longitude": "24.7454"}}
</script>
</head><body>
  <div class="event__description">A wonderful jazz evening with local musicians.</div>
</body></html>
"""

PILETILEVI_DETAIL_WITH_IMPORTANT_INFO_HTML = """
<html><body>
  <div class="event__description">A wonderful jazz evening with local musicians.</div>
  <div class="white-rounded-block">
    <h2 class="text-20 font-bold pb-6">Important information</h2>
    <div class="collapsable-container">Age limit: 18+. Language: English. Duration: 2 hours.</div>
  </div>
  <div class="white-rounded-block">
    <h2 class="text-20 font-bold pb-6">Event location</h2>
    <div class="collapsable-container">Jazz Club, Tallinn</div>
  </div>
</body></html>
"""

PILETILEVI_DETAIL_ET_WITH_IMPORTANT_INFO_HTML = """
<html><body>
  <div class="event__description">Imeline džässõhtu kohalike muusikutega.</div>
  <div class="white-rounded-block">
    <h2 class="text-20 font-bold pb-6">Hinnainfo</h2>
    <div class="collapsable-container">Vanusepiir: 18+. Keel: inglise. Kestus: 2 tundi.</div>
  </div>
  <div class="white-rounded-block">
    <h2 class="text-20 font-bold pb-6">Toimumiskoht</h2>
    <div class="collapsable-container">Jazziklubi, Tallinn</div>
  </div>
</body></html>
"""


PILETILEVI_DETAIL_RU_WITH_IMPORTANT_INFO_HTML = """
<html><body>
  <div class="event__description">Чудесный джазовый вечер с местными музыкантами.</div>
  <div class="white-rounded-block">
    <h2 class="text-20 font-bold pb-6">Дополнительная информация</h2>
    <div class="collapsable-container">Возрастное ограничение: 18+. Язык: английский. Продолжительность: 2 часа.</div>
  </div>
  <div class="white-rounded-block">
    <h2 class="text-20 font-bold pb-6">Место проведения</h2>
    <div class="collapsable-container">Джаз-клуб, Таллин</div>
  </div>
</body></html>
"""


PILETILEVI_DETAIL_WITH_BRACKET_ARTIFACT_HTML = """
<html><body>
  <div class="event__description">A wonderful jazz evening with local musicians.</div>
  <div class="white-rounded-block">
    <h2 class="text-20 font-bold pb-6">Important information</h2>
    [<p>Ticket prices include fees.</p><p>Age limit: 18+.</p>]
  </div>
</body></html>
"""

# JSON-LD description is source-flattened, glued plain text (no paragraph
# breaks) — the .event__description HTML block below is the same content
# with real <p> structure, as Piletilevi's live pages actually carry both.
PILETILEVI_DETAIL_WITH_MULTI_PARAGRAPH_DESC_HTML = """
<html><body>
<script type="application/ld+json">
{"@type": "Event", "name": "Summer Flower Ball", "description": "First paragraph text.Second paragraph glued on."}
</script>
  <div class="event__description"><p>First paragraph text.</p><p>Second paragraph glued on.</p></div>
</body></html>
"""


def _piletilevi_adapter():
    return PiletileviAdapter(
        _make_source(slug="piletilevi", url=settings.PILETILEVI_BASE_URL)
    )


class TestPiletileviParseDate:
    def test_standard_date_time(self):
        result = _parse_piletilevi_date("We 19.08.2026 • 19:00")
        assert result is not None
        assert (result.year, result.month, result.day) == (2026, 8, 19)
        assert (result.hour, result.minute) == (19, 0)
        assert result.tzinfo == TALLINN_TZ

    def test_malformed_no_bullet_returns_none(self):
        assert _parse_piletilevi_date("Th 11.06.2026 - Su 14.06.2026") is None

    def test_empty_string_returns_none(self):
        assert _parse_piletilevi_date("") is None


class TestPiletileviParseCards:
    def test_extracts_common_card_fields(self):
        adapter = _piletilevi_adapter()
        soup = BeautifulSoup(PILETILEVI_LISTING_HTML, "html.parser")
        cards = adapter.parse_cards(soup)
        assert [c["external_id"] for c in cards] == [
            "/en/tickets/AA1/jazz-night",
            "/en/tickets/BB2/riga-rock",
            "/en/tickets/CC3/festival-pass",
        ]
        jazz = cards[0]
        assert jazz["title"] == "Jazz Night"
        assert jazz["venue"] == "Jazz Club, Tallinn"
        assert jazz["url"] == settings.PILETILEVI_BASE_URL + "/en/tickets/AA1/jazz-night"
        assert jazz["image_url"] == "https://www.piletilevi.ee/i/height=1009/images/aa1.jpg"

    def test_passes_filter_drops_non_tallinn_venue(self):
        adapter = _piletilevi_adapter()
        soup = BeautifulSoup(PILETILEVI_LISTING_HTML, "html.parser")
        cards = {c["external_id"]: c for c in adapter.parse_cards(soup)}
        assert adapter.passes_filter(cards["/en/tickets/AA1/jazz-night"]) is True
        assert adapter.passes_filter(cards["/en/tickets/BB2/riga-rock"]) is False

    def test_relative_image_url_becomes_absolute(self):
        html = """
        <a class="card" href="/en/tickets/DD4/test">
          <div class="card__time-title"><div class="card__time">We 19.08.2026 • 19:00</div><h3>Test</h3></div>
          <img class="card__image" src="/media/img/event.jpg"/>
        </a>
        """
        adapter = _piletilevi_adapter()
        cards = adapter.parse_cards(BeautifulSoup(html, "html.parser"))
        assert cards[0]["image_url"] == settings.PILETILEVI_BASE_URL + "/media/img/event.jpg"


class TestPiletileviNormalize:
    def test_unparseable_date_card_dropped_by_normalize(self):
        adapter = _piletilevi_adapter()
        soup = BeautifulSoup(PILETILEVI_LISTING_HTML, "html.parser")
        cards = {c["external_id"]: c for c in adapter.parse_cards(soup)}
        # Multi-day range "Th ... - Su ..." has no bullet → unparseable → dropped
        assert adapter.normalize(cards["/en/tickets/CC3/festival-pass"]) is None

    def test_happy_path(self):
        adapter = _piletilevi_adapter()
        soup = BeautifulSoup(PILETILEVI_LISTING_HTML, "html.parser")
        cards = {c["external_id"]: c for c in adapter.parse_cards(soup)}
        result = adapter.normalize(cards["/en/tickets/AA1/jazz-night"])
        assert isinstance(result, NormalizedEvent)
        assert result.title == "Jazz Night"
        assert result.external_id == "/en/tickets/AA1/jazz-night"
        assert result.venue_name == "Jazz Club, Tallinn"
        assert result.url == settings.PILETILEVI_BASE_URL + "/en/tickets/AA1/jazz-night"
        assert result.starts_at.tzinfo == TALLINN_TZ


class TestPiletileviFetchRaw:
    @pytest.mark.asyncio
    async def test_pagination_stops_when_page_yields_no_new_cards(self):
        adapter = _piletilevi_adapter()
        listing_resp = _mock_response(PILETILEVI_LISTING_HTML)
        empty_resp = _mock_response(PILETILEVI_EMPTY_HTML)
        detail_resp = _mock_response(PILETILEVI_DETAIL_HTML)

        with patch("app.ingestion.sources.html_base.http_get") as mock_get:
            mock_get.side_effect = [
                listing_resp,  # page 1 — 2 cards survive the Tallinn filter
                empty_resp,  # page 2 — no cards → pagination halts
                detail_resp,  # detail fetch for Jazz Night
                detail_resp,  # detail fetch for Festival Pass... no, dropped by normalize
            ]
            results = await adapter.fetch_raw(_known_ids())

        # Riga Rock filtered (non-Tallinn); Jazz Night + Festival Pass collected as raw
        # cards (Festival Pass is dropped later by normalize() for its date format).
        assert len(results) == 2
        external_ids = [r["external_id"] for r in results]
        assert "/en/tickets/AA1/jazz-night" in external_ids
        assert "/en/tickets/BB2/riga-rock" not in external_ids

    @pytest.mark.asyncio
    async def test_detail_description_merged_onto_card(self):
        adapter = _piletilevi_adapter()
        single_card_html = """
        <a class="card" href="/en/tickets/AA1/jazz-night">
          <div class="card__time-title"><div class="card__time">We 19.08.2026 • 19:00</div><h3>Jazz Night</h3></div>
          <div class="card__description">Jazz Club, Tallinn</div>
        </a>
        """
        with patch("app.ingestion.sources.html_base.http_get") as mock_get:
            mock_get.side_effect = [
                _mock_response(single_card_html),
                _mock_response(PILETILEVI_EMPTY_HTML),
                _mock_response(PILETILEVI_DETAIL_HTML),
            ]
            results = await adapter.fetch_raw(_known_ids())

        assert len(results) == 1
        assert (
            results[0]["description"]
            == "A wonderful jazz evening with local musicians."
        )

    @pytest.mark.asyncio
    async def test_empty_first_page_raises_on_fetch_error(self):
        adapter = _piletilevi_adapter()
        with patch("app.ingestion.sources.html_base.http_get") as mock_get:
            mock_get.side_effect = httpx.ConnectError("down")
            with pytest.raises(httpx.ConnectError):
                await adapter.fetch_raw(_known_ids())


class TestPiletileviParseDetail:
    @pytest.mark.asyncio
    async def test_jsonld_location_populates_address_and_coords(self):
        adapter = _piletilevi_adapter()
        soup = BeautifulSoup(PILETILEVI_DETAIL_WITH_LOCATION_HTML, "html.parser")
        card: dict = {}
        await adapter.parse_detail(MagicMock(), soup, card)
        assert card["venue_address"] == "Rataskaevu 10, Tallinn, Harju maakond"
        assert card["lat"] == 59.4372
        assert card["lng"] == 24.7454
        assert card["description"] == "A wonderful jazz evening with local musicians."

    @pytest.mark.asyncio
    async def test_array_type_and_string_coords_are_handled(self):
        adapter = _piletilevi_adapter()
        soup = BeautifulSoup(
            PILETILEVI_DETAIL_WITH_ARRAY_TYPE_AND_STRING_COORDS_HTML, "html.parser"
        )
        card: dict = {}
        await adapter.parse_detail(MagicMock(), soup, card)
        assert card["venue_address"] == "Rataskaevu 10, Tallinn, Harju maakond"
        assert card["lat"] == 59.4372
        assert card["lng"] == 24.7454

    @pytest.mark.asyncio
    async def test_no_jsonld_leaves_address_and_coords_unset(self):
        adapter = _piletilevi_adapter()
        soup = BeautifulSoup(PILETILEVI_DETAIL_HTML, "html.parser")
        card: dict = {}
        await adapter.parse_detail(MagicMock(), soup, card)
        assert "venue_address" not in card
        assert "lat" not in card
        assert "lng" not in card

    @pytest.mark.asyncio
    async def test_important_info_section_present_is_captured(self):
        adapter = _piletilevi_adapter()
        soup = BeautifulSoup(
            PILETILEVI_DETAIL_WITH_IMPORTANT_INFO_HTML, "html.parser"
        )
        card: dict = {}
        await adapter.parse_detail(MagicMock(), soup, card)
        assert (
            card["important_info"]
            == "Age limit: 18+. Language: English. Duration: 2 hours."
        )

    @pytest.mark.asyncio
    async def test_important_info_section_absent_is_none(self):
        adapter = _piletilevi_adapter()
        soup = BeautifulSoup(PILETILEVI_DETAIL_HTML, "html.parser")
        card: dict = {}
        await adapter.parse_detail(MagicMock(), soup, card)
        assert card["important_info"] is None

    def test_important_info_et_locale_uses_hinnainfo_heading(self):
        soup = BeautifulSoup(PILETILEVI_DETAIL_ET_WITH_IMPORTANT_INFO_HTML, "html.parser")
        result = _piletilevi_important_info(soup, "et")
        assert result == "Vanusepiir: 18+. Keel: inglise. Kestus: 2 tundi."

    def test_important_info_et_locale_absent_returns_none(self):
        soup = BeautifulSoup(PILETILEVI_DETAIL_WITH_IMPORTANT_INFO_HTML, "html.parser")
        assert _piletilevi_important_info(soup, "et") is None

    def test_important_info_en_locale_explicit(self):
        soup = BeautifulSoup(PILETILEVI_DETAIL_WITH_IMPORTANT_INFO_HTML, "html.parser")
        result = _piletilevi_important_info(soup, "en")
        assert result == "Age limit: 18+. Language: English. Duration: 2 hours."

    def test_important_info_unknown_locale_falls_back_to_en(self):
        # "fi" has no heading mapping in PILETILEVI_IMPORTANT_INFO_HEADINGS,
        # so it falls back to the en heading text — "ru" now has its own
        # mapping (see test_important_info_ru_locale_uses_russian_heading)
        # and is no longer a stand-in for "unmapped locale".
        soup = BeautifulSoup(PILETILEVI_DETAIL_WITH_IMPORTANT_INFO_HTML, "html.parser")
        result = _piletilevi_important_info(soup, "fi")
        assert result == "Age limit: 18+. Language: English. Duration: 2 hours."

    def test_important_info_ru_locale_uses_russian_heading(self):
        soup = BeautifulSoup(
            PILETILEVI_DETAIL_RU_WITH_IMPORTANT_INFO_HTML, "html.parser"
        )
        result = _piletilevi_important_info(soup, "ru")
        assert result == (
            "Возрастное ограничение: 18+. Язык: английский. "
            "Продолжительность: 2 часа."
        )

    def test_important_info_ru_locale_absent_returns_none(self):
        soup = BeautifulSoup(PILETILEVI_DETAIL_WITH_IMPORTANT_INFO_HTML, "html.parser")
        assert _piletilevi_important_info(soup, "ru") is None

    def test_stray_bracket_fragment_artifacts_excluded(self):
        # Piletilevi's Nuxt SSR markup wraps the block's real <p> content in
        # bare "[" / "]" text-node siblings (fragment-boundary artifacts).
        # These must not leak into the stored important_info.
        soup = BeautifulSoup(
            PILETILEVI_DETAIL_WITH_BRACKET_ARTIFACT_HTML, "html.parser"
        )
        result = _piletilevi_important_info(soup, "en")
        assert result is not None
        assert not result.startswith("[")
        assert not result.endswith("]")
        assert result == "<p>Ticket prices include fees.</p><p>Age limit: 18+.</p>"


class TestPiletileviLocalizedText:
    def test_description_keeps_paragraph_structure_not_jsonld_glued_text(self):
        soup = BeautifulSoup(
            PILETILEVI_DETAIL_WITH_MULTI_PARAGRAPH_DESC_HTML, "html.parser"
        )
        title, desc = piletilevi_localized_text(soup)
        assert title == "Summer Flower Ball"
        assert desc == "<p>First paragraph text.</p><p>Second paragraph glued on.</p>"
        # The bug: JSON-LD's own description string glues sentences together.
        assert desc is not None
        assert "on.Second" not in desc

    def test_title_from_jsonld_desc_none_when_no_description_selector(self):
        soup = BeautifulSoup(PILETILEVI_DETAIL_WITH_LOCATION_HTML, "html.parser")
        title, desc = piletilevi_localized_text(soup)
        assert title == "Jazz Night"
        assert desc == "A wonderful jazz evening with local musicians."

    def test_no_jsonld_and_no_description_selector_returns_none_none(self):
        soup = BeautifulSoup("<html><body><p>Nothing here</p></body></html>", "html.parser")
        title, desc = piletilevi_localized_text(soup)
        assert title is None
        assert desc is None

    def test_oversized_description_truncated_to_plain_text_cap(self):
        # Mirrors kumu_localized_text/estonia_concert_hall_localized_text: an
        # over-cap HTML description falls back to plain text truncated at
        # LOCALIZED_TEXT_MAX_DESC_CHARS, rather than storing unbounded HTML.
        from app.constants import LOCALIZED_TEXT_MAX_DESC_CHARS

        long_paragraph = "word " * (LOCALIZED_TEXT_MAX_DESC_CHARS // 4)
        html = (
            "<html><body>"
            f'<div class="event__description"><p>{long_paragraph}</p></div>'
            "</body></html>"
        )
        soup = BeautifulSoup(html, "html.parser")
        _, desc = piletilevi_localized_text(soup)
        assert desc is not None
        assert len(desc) <= LOCALIZED_TEXT_MAX_DESC_CHARS
        assert "<p>" not in desc


class TestPriceBoundsFromStore:
    def test_single_sector_two_ticket_types(self):
        # Captured live from GET .../api/v1/store/events/EIHT67B2EC/prices
        payload = {
            "planType": "SECTION_BASED",
            "availableTickets": 22,
            "eventSections": [
                {
                    "id": "1791",
                    "title": "Raekoda",
                    "priceZones": [
                        {
                            "id": "9",
                            "ticketTypes": [
                                {"id": "1", "name": "General admission ticket", "price": 36.9, "fee": 0.0},
                                {"id": "3735", "name": "SOODUSPILET", "price": 26.9, "fee": 0.0},
                            ],
                        }
                    ],
                }
            ],
        }
        assert _price_bounds_from_store(payload) == (26.9, 36.9, False)

    def test_multi_sector_flattens_across_sections(self):
        payload = {
            "eventSections": [
                {"priceZones": [{"ticketTypes": [{"price": 93.9}]}]},
                {"priceZones": [{"ticketTypes": [{"price": 83.9}]}]},
            ]
        }
        assert _price_bounds_from_store(payload) == (83.9, 93.9, False)

    def test_paid_and_free_companion_ticket(self):
        payload = {
            "eventSections": [
                {"priceZones": [{"ticketTypes": [{"price": 20.0}, {"price": 0.0}]}]}
            ]
        }
        assert _price_bounds_from_store(payload) == (20.0, 20.0, True)

    def test_genuinely_free_event(self):
        payload = {"eventSections": [{"priceZones": [{"ticketTypes": [{"price": 0.0}]}]}]}
        assert _price_bounds_from_store(payload) == (0.0, 0.0, False)

    def test_no_ticket_types_returns_none(self):
        assert _price_bounds_from_store({"eventSections": []}) == (None, None, False)

    def test_non_numeric_price_skipped(self):
        payload = {
            "eventSections": [
                {"priceZones": [{"ticketTypes": [{"price": "n/a"}, {"price": 15.0}]}]}
            ]
        }
        assert _price_bounds_from_store(payload) == (15.0, 15.0, False)

    def test_negative_price_ignored_not_treated_as_free(self):
        # A negative price is garbage data — must not flip has_free_tier True
        # the way a genuine zero-priced companion ticket would.
        payload = {
            "eventSections": [
                {"priceZones": [{"ticketTypes": [{"price": -5.0}, {"price": 15.0}]}]}
            ]
        }
        assert _price_bounds_from_store(payload) == (15.0, 15.0, False)

    def test_only_negative_price_returns_none(self):
        payload = {"eventSections": [{"priceZones": [{"ticketTypes": [{"price": -5.0}]}]}]}
        assert _price_bounds_from_store(payload) == (None, None, False)


_PILETILEVI_DETAIL_URL = "https://www.piletilevi.ee/en/tickets/EIHT67B2EC/prantsuse-jazz"


class TestPiletileviParseDetailPrice:
    @pytest.mark.asyncio
    async def test_single_sector_price_populates_card(self):
        adapter = _piletilevi_adapter()
        soup = BeautifulSoup(PILETILEVI_DETAIL_HTML, "html.parser")
        card: dict = {"url": _PILETILEVI_DETAIL_URL}
        payload = {
            "eventSections": [
                {"priceZones": [{"ticketTypes": [
                    {"price": 36.9}, {"price": 26.9},
                ]}]}
            ]
        }
        with (
            patch("app.ingestion.sources.piletilevi.http_post") as mock_post,
            patch("app.ingestion.sources.piletilevi.http_get") as mock_get,
        ):
            mock_get.return_value = _piletilevi_response(payload)
            await adapter.parse_detail(MagicMock(), soup, card)

        assert card["price_min"] == 26.9
        assert card["price_max"] == 36.9
        assert card["currency"] == "EUR"
        assert card["has_free_tier"] is False
        assert mock_post.call_count == 1
        login_url = mock_post.call_args_list[0].args[1]
        assert login_url == PILETILEVI_LOGIN_EXPRESS_URL
        price_url = mock_get.call_args_list[0].args[1]
        assert price_url == PILETILEVI_PRICES_URL.format(code="EIHT67B2EC")

    @pytest.mark.asyncio
    async def test_paid_and_free_tier_sets_has_free_tier(self):
        adapter = _piletilevi_adapter()
        soup = BeautifulSoup(PILETILEVI_DETAIL_HTML, "html.parser")
        card: dict = {"url": _PILETILEVI_DETAIL_URL}
        payload = {
            "eventSections": [
                {"priceZones": [{"ticketTypes": [{"price": 20.0}, {"price": 0.0}]}]}
            ]
        }
        with (
            patch("app.ingestion.sources.piletilevi.http_post") as mock_post,
            patch("app.ingestion.sources.piletilevi.http_get") as mock_get,
        ):
            mock_get.return_value = _piletilevi_response(payload)
            await adapter.parse_detail(MagicMock(), soup, card)

        assert mock_post.call_count == 1
        assert card["price_min"] == 20.0
        assert card["price_max"] == 20.0
        assert card["currency"] == "EUR"
        assert card["has_free_tier"] is True

    @pytest.mark.asyncio
    async def test_genuinely_free_event_zero_price_no_currency(self):
        adapter = _piletilevi_adapter()
        soup = BeautifulSoup(PILETILEVI_DETAIL_HTML, "html.parser")
        card: dict = {"url": _PILETILEVI_DETAIL_URL}
        payload = {"eventSections": [{"priceZones": [{"ticketTypes": [{"price": 0.0}]}]}]}
        with (
            patch("app.ingestion.sources.piletilevi.http_post") as mock_post,
            patch("app.ingestion.sources.piletilevi.http_get") as mock_get,
        ):
            mock_get.return_value = _piletilevi_response(payload)
            await adapter.parse_detail(MagicMock(), soup, card)

        assert mock_post.call_count == 1
        assert card["price_min"] == 0.0
        assert card["price_max"] == 0.0
        assert card["currency"] is None
        assert card["has_free_tier"] is False

    @pytest.mark.asyncio
    async def test_prices_api_error_leaves_price_unset(self):
        adapter = _piletilevi_adapter()
        soup = BeautifulSoup(PILETILEVI_DETAIL_HTML, "html.parser")
        card: dict = {"url": _PILETILEVI_DETAIL_URL}
        with (
            patch("app.ingestion.sources.piletilevi.http_post") as mock_post,
            patch("app.ingestion.sources.piletilevi.http_get") as mock_get,
        ):
            mock_get.side_effect = httpx.HTTPStatusError(
                "error", request=MagicMock(), response=MagicMock()
            )
            await adapter.parse_detail(MagicMock(), soup, card)

        assert mock_post.call_count == 1
        assert "price_min" not in card
        assert "has_free_tier" not in card

    @pytest.mark.asyncio
    async def test_session_bootstrap_failure_skips_prices_call(self):
        adapter = _piletilevi_adapter()
        soup = BeautifulSoup(PILETILEVI_DETAIL_HTML, "html.parser")
        card: dict = {"url": _PILETILEVI_DETAIL_URL}
        with (
            patch("app.ingestion.sources.piletilevi.http_post") as mock_post,
            patch("app.ingestion.sources.piletilevi.http_get") as mock_get,
        ):
            mock_post.side_effect = httpx.HTTPStatusError(
                "error", request=MagicMock(), response=MagicMock()
            )
            await adapter.parse_detail(MagicMock(), soup, card)

        assert mock_get.call_count == 0
        assert "price_min" not in card

    @pytest.mark.asyncio
    async def test_url_without_code_skips_price_lookup_entirely(self):
        adapter = _piletilevi_adapter()
        soup = BeautifulSoup(PILETILEVI_DETAIL_HTML, "html.parser")
        card: dict = {"url": "https://www.piletilevi.ee/en/search"}
        with (
            patch("app.ingestion.sources.piletilevi.http_post") as mock_post,
            patch("app.ingestion.sources.piletilevi.http_get") as mock_get,
        ):
            await adapter.parse_detail(MagicMock(), soup, card)

        assert mock_post.call_count == 0
        assert mock_get.call_count == 0
        assert "price_min" not in card

    @pytest.mark.asyncio
    async def test_missing_url_key_skips_price_lookup(self):
        adapter = _piletilevi_adapter()
        soup = BeautifulSoup(PILETILEVI_DETAIL_HTML, "html.parser")
        card: dict = {}
        with (
            patch("app.ingestion.sources.piletilevi.http_post") as mock_post,
            patch("app.ingestion.sources.piletilevi.http_get") as mock_get,
        ):
            await adapter.parse_detail(MagicMock(), soup, card)

        assert mock_post.call_count == 0
        assert mock_get.call_count == 0
        assert "price_min" not in card

    @pytest.mark.asyncio
    async def test_empty_sections_leaves_price_unset(self):
        adapter = _piletilevi_adapter()
        soup = BeautifulSoup(PILETILEVI_DETAIL_HTML, "html.parser")
        card: dict = {"url": _PILETILEVI_DETAIL_URL}
        with (
            patch("app.ingestion.sources.piletilevi.http_post") as mock_post,
            patch("app.ingestion.sources.piletilevi.http_get") as mock_get,
        ):
            mock_get.return_value = _piletilevi_response({"eventSections": []})
            await adapter.parse_detail(MagicMock(), soup, card)

        assert mock_post.call_count == 1
        assert "price_min" not in card

    @pytest.mark.asyncio
    async def test_session_cached_across_cards(self):
        adapter = _piletilevi_adapter()
        soup = BeautifulSoup(PILETILEVI_DETAIL_HTML, "html.parser")
        payload = {"eventSections": [{"priceZones": [{"ticketTypes": [{"price": 5.0}]}]}]}
        with (
            patch("app.ingestion.sources.piletilevi.http_post") as mock_post,
            patch("app.ingestion.sources.piletilevi.http_get") as mock_get,
        ):
            mock_get.return_value = _piletilevi_response(payload)
            card1: dict = {"url": _PILETILEVI_DETAIL_URL}
            card2: dict = {"url": "https://www.piletilevi.ee/en/tickets/OTHERCODE/other"}
            await adapter.parse_detail(MagicMock(), soup, card1)
            await adapter.parse_detail(MagicMock(), soup, card2)

        # 1 login call total, 2 price calls — session cookie reused across cards.
        assert mock_post.call_count == 1
        assert mock_get.call_count == 2
        assert card1["price_min"] == 5.0
        assert card2["price_min"] == 5.0


# ---------------------------------------------------------------------------
# KumuAdapter — kumu.ekm.ee/en/calendar/
# ---------------------------------------------------------------------------

KUMU_LISTING_HTML = """
<html><body>
<ul class="event-grid__cards">
  <li class="event-grid__item">
    <div class="card__header">
      <span class="card__header-date-text">12/06/2026 | 19:00</span>
      <a class="card__link" href="https://kumu.ekm.ee/en/syndmus/example-1/">
        <h2 class="no-title-styles card__header-title">Example Concert
          <span class="h-visually-hidden">12/06/2026 | 19:00</span>
        </h2>
      </a>
    </div>
    <div class="card__image">
      <img class="image__img lazyload" data-srcset="https://kumu.ekm.ee/img-200.jpg 200w, https://kumu.ekm.ee/img-600.jpg 600w" src="data:image/svg+xml,placeholder"/>
    </div>
  </li>
  <li class="event-grid__item">
    <div class="card__header">
      <span class="card__header-date-text">not-a-date</span>
      <a class="card__link" href="https://kumu.ekm.ee/en/syndmus/example-2/">
        <h2 class="no-title-styles card__header-title">Bad Date Event
          <span class="h-visually-hidden">extra</span>
        </h2>
      </a>
    </div>
  </li>
</ul>
</body></html>
"""

KUMU_ITALIC_TITLE_HTML = """
<html><body>
<ul class="event-grid__cards">
  <li class="event-grid__item">
    <div class="card__header">
      <span class="card__header-date-text">15/06/2026 | 18:00</span>
      <a class="card__link" href="https://kumu.ekm.ee/en/syndmus/example-3/">
        <h2 class="no-title-styles card__header-title"><i>Kristi Kongi: Chromatic Drift</i> through the Eyes of a Museum Insider
          <span class="h-visually-hidden">15/06/2026 | 18:00</span>
        </h2>
      </a>
    </div>
  </li>
</ul>
</body></html>
"""

KUMU_PAGE2_HTML = """
<html><body>
<ul class="event-grid__cards">
  <li class="event-grid__item">
    <div class="card__header">
      <span class="card__header-date-text">20/06/2026 | 19:00</span>
      <a class="card__link" href="https://kumu.ekm.ee/en/syndmus/example-3/">
        <h2 class="no-title-styles card__header-title">Page Two Concert
          <span class="h-visually-hidden">20/06/2026 | 19:00</span>
        </h2>
      </a>
    </div>
  </li>
</ul>
</body></html>
"""

KUMU_EMPTY_PAGE_HTML = """
<html><body>
<ul class="event-grid__cards">
</ul>
</body></html>
"""


def _kumu_adapter():
    return KumuAdapter(_make_source(slug="kumu"))


class TestKumuParseCards:
    def test_title_excludes_hidden_date_span(self):
        adapter = _kumu_adapter()
        soup = BeautifulSoup(KUMU_LISTING_HTML, "html.parser")
        cards = adapter.parse_cards(soup)
        assert cards[0]["title"] == "Example Concert"
        assert cards[0]["external_id"] == "https://kumu.ekm.ee/en/syndmus/example-1/"
        assert cards[0]["url"] == "https://kumu.ekm.ee/en/syndmus/example-1/"

    def test_image_url_falls_back_to_data_srcset(self):
        adapter = _kumu_adapter()
        soup = BeautifulSoup(KUMU_LISTING_HTML, "html.parser")
        cards = adapter.parse_cards(soup)
        assert cards[0]["image_url"] == "https://kumu.ekm.ee/img-200.jpg"

    def test_title_with_leading_italic_element_includes_full_text(self):
        adapter = _kumu_adapter()
        soup = BeautifulSoup(KUMU_ITALIC_TITLE_HTML, "html.parser")
        cards = adapter.parse_cards(soup)
        assert (
            cards[0]["title"]
            == "Kristi Kongi: Chromatic Drift through the Eyes of a Museum Insider"
        )

    def test_static_venue_address_and_coords(self):
        adapter = _kumu_adapter()
        soup = BeautifulSoup(KUMU_LISTING_HTML, "html.parser")
        cards = adapter.parse_cards(soup)
        assert cards[0]["venue"] == KUMU_VENUE_NAME
        assert cards[0]["venue_address"] == KUMU_VENUE_ADDRESS
        assert cards[0]["lat"] == KUMU_VENUE_LAT
        assert cards[0]["lng"] == KUMU_VENUE_LNG


class TestKumuParseDate:
    def test_parses_pipe_separated_format(self):
        adapter = _kumu_adapter()
        result = adapter.parse_date({"date_str": "12/06/2026 | 19:00"})
        assert result == datetime(2026, 6, 12, 19, 0, tzinfo=TALLINN_TZ)

    def test_unparseable_date_returns_none(self):
        adapter = _kumu_adapter()
        assert adapter.parse_date({"date_str": "not-a-date"}) is None


class TestKumuFetchRaw:
    @pytest.mark.asyncio
    async def test_single_page_fetch_drops_unparseable_date_card(self):
        adapter = _kumu_adapter()
        with patch("app.ingestion.sources.html_base.http_get") as mock_get:
            # Both listing fetches return the same page — page 2 yields zero new
            # ids (all already seen on page 1), so pagination stops there. The
            # same response is also reused for the per-card detail fetches
            # (needs_detail=True); it has no .event-header__ticket-price, so
            # parse_detail is a no-op for both cards.
            mock_get.return_value = _mock_response(KUMU_LISTING_HTML)
            raw_items = await adapter.fetch_raw(_known_ids())

        assert mock_get.call_count == 4  # 2 listing pages + 2 detail fetches
        assert len(raw_items) == 2  # both raw cards collected
        normalized = [adapter.normalize(r) for r in raw_items]
        normalized = [n for n in normalized if n is not None]
        assert len(normalized) == 1  # "Bad Date Event" dropped by normalize
        assert normalized[0].title == "Example Concert"

    @pytest.mark.asyncio
    async def test_pagination_stops_on_empty_page_and_dedups(self):
        adapter = _kumu_adapter()
        with patch("app.ingestion.sources.html_base.http_get") as mock_get:
            # 3 listing fetches, then needs_detail fetches a detail page per
            # collected card (3 cards) — reuse the empty page (no price selector)
            # so parse_detail is a no-op for each.
            mock_get.side_effect = [
                _mock_response(KUMU_LISTING_HTML),
                _mock_response(KUMU_PAGE2_HTML),
                _mock_response(KUMU_EMPTY_PAGE_HTML),
                _mock_response(KUMU_EMPTY_PAGE_HTML),
                _mock_response(KUMU_EMPTY_PAGE_HTML),
                _mock_response(KUMU_EMPTY_PAGE_HTML),
            ]
            raw_items = await adapter.fetch_raw(_known_ids())

        assert mock_get.call_count == 6
        urls = [call.args[1] for call in mock_get.call_args_list]
        assert urls[:3] == [
            "https://example.test/listing",
            "https://example.test/listing/page/2/",
            "https://example.test/listing/page/3/",
        ]
        assert {c["external_id"] for c in raw_items} == {
            "https://kumu.ekm.ee/en/syndmus/example-1/",
            "https://kumu.ekm.ee/en/syndmus/example-2/",
            "https://kumu.ekm.ee/en/syndmus/example-3/",
        }

    @pytest.mark.asyncio
    async def test_known_events_excluded_from_returned_items(self):
        """fetch_raw() must drop already-stored cards from its return value, not
        just skip their detail fetch — otherwise every re-run re-inserts a
        raw_events row for unchanged listing data (regression)."""
        adapter = _kumu_adapter()
        known = {"https://kumu.ekm.ee/en/syndmus/example-1/"}
        with patch("app.ingestion.sources.html_base.http_get") as mock_get:
            mock_get.return_value = _mock_response(KUMU_LISTING_HTML)
            raw_items = await adapter.fetch_raw(_known_ids(known))

        assert {c["external_id"] for c in raw_items} == {
            "https://kumu.ekm.ee/en/syndmus/example-2/",
        }

    @pytest.mark.asyncio
    async def test_empty_known_ids_returns_all_items_unchanged(self):
        """An empty known_ids set must return every fetched card unchanged."""
        adapter = _kumu_adapter()
        with patch("app.ingestion.sources.html_base.http_get") as mock_get:
            mock_get.return_value = _mock_response(KUMU_LISTING_HTML)
            raw_items = await adapter.fetch_raw(_known_ids())

        assert {c["external_id"] for c in raw_items} == {
            "https://kumu.ekm.ee/en/syndmus/example-1/",
            "https://kumu.ekm.ee/en/syndmus/example-2/",
        }


class TestKumuParseDetail:
    @pytest.mark.asyncio
    async def test_price_hint_extracted_from_ticket_price_selector(self):
        adapter = _kumu_adapter()
        html = '<div class="event-header__ticket-price">10 - 15 €</div>'
        soup = BeautifulSoup(html, "html.parser")
        card: dict = {}
        await adapter.parse_detail(MagicMock(), soup, card)
        assert card["price_hint"] == "10 - 15 €"

    @pytest.mark.asyncio
    async def test_price_hint_includes_label_and_tooltip_tiers(self):
        adapter = _kumu_adapter()
        html = """
        <div class="event-header__ticket">
          <span class="h-uppercase">Adult: Kumu Art Museum</span>
          <div class="event-header__ticket-price h-no-break">
            €16
            <div class="tooltip-wrapper">
              <ul class="tooltip-list">
                <li class="tooltip-list__item">
                  <div class="tooltip-list__item-title">Family: Kumu Art Museum</div>
                  <div class="tooltip-list__item-value">€32</div>
                </li>
                <li class="tooltip-list__item">
                  <div class="tooltip-list__item-title">Discount: Kumu Art Museum</div>
                  <div class="tooltip-list__item-value">€11</div>
                </li>
                <li class="tooltip-list__item">
                  <div class="tooltip-list__item-title">Adult ticket with donation: Art Museum of Estonia</div>
                  <div class="tooltip-list__item-value">€25</div>
                </li>
              </ul>
            </div>
          </div>
        </div>
        """
        soup = BeautifulSoup(html, "html.parser")
        card: dict = {}
        await adapter.parse_detail(MagicMock(), soup, card)
        assert card["price_hint"] == (
            "Adult: Kumu Art Museum €16, Family: Kumu Art Museum €32, "
            "Discount: Kumu Art Museum €11, "
            "Adult ticket with donation: Art Museum of Estonia €25"
        )

    @pytest.mark.asyncio
    async def test_price_hint_bare_headline_without_label_span(self):
        adapter = _kumu_adapter()
        html = '<div class="event-header__ticket-price">10 - 15 €</div>'
        soup = BeautifulSoup(html, "html.parser")
        card: dict = {}
        await adapter.parse_detail(MagicMock(), soup, card)
        assert card["price_hint"] == "10 - 15 €"

    @pytest.mark.asyncio
    async def test_no_price_selector_leaves_card_unchanged(self):
        adapter = _kumu_adapter()
        soup = BeautifulSoup("<html></html>", "html.parser")
        card: dict = {}
        await adapter.parse_detail(MagicMock(), soup, card)
        assert "price_hint" not in card

    @pytest.mark.asyncio
    async def test_description_extracted_from_content_dynamic_selector(self):
        adapter = _kumu_adapter()
        html = '<div class="single__content-dynamic text">An exhibition of works.</div>'
        soup = BeautifulSoup(html, "html.parser")
        card: dict = {}
        await adapter.parse_detail(MagicMock(), soup, card)
        assert card["description"] == "An exhibition of works."

    @pytest.mark.asyncio
    async def test_no_description_selector_leaves_card_unchanged(self):
        adapter = _kumu_adapter()
        soup = BeautifulSoup("<html></html>", "html.parser")
        card: dict = {}
        await adapter.parse_detail(MagicMock(), soup, card)
        assert "description" not in card


# ---------------------------------------------------------------------------
# EstoniaConcertHallAdapter — concert.ee/en/
# ---------------------------------------------------------------------------

CONCERT_HALL_HTML = """
<html><body>
<div class="event-list">
  <div class="row">
    <div class="col-1">
      <div class="date"><span class="day">Fr</span><span>3.</span><span>07</span></div>
      <div class="image" style="background-image: url(https://concert.ee/img/tallinn.jpg)"></div>
      <div class="info">
        <h2><a href="https://concert.ee/en/festival/tallinn-show/?ek_id=1">Tallinn Show</a></h2>
        <div class="detail-wrap">
          <div class="event-date"><span class="day">Friday</span><span>,</span><span>3.07</span></div>
          <div class="event-time">20:00</div>
          <div class="loc-wrap">
            <div class="event-location">Tallinn,</div>
            <div class="event-venue">Alexela Kontserdimaja</div>
          </div>
        </div>
      </div>
    </div>
  </div>
  <div class="row">
    <div class="col-1">
      <div class="date"><span class="day">Fr</span><span>3.</span><span>07</span></div>
      <div class="image" style="background-image: url(https://concert.ee/img/haapsalu.jpg)"></div>
      <div class="info">
        <h2><a href="https://concert.ee/en/festival/haapsalu-show/?ek_id=2">Haapsalu Show</a></h2>
        <div class="detail-wrap">
          <div class="event-date"><span class="day">Friday</span><span>,</span><span>3.07</span></div>
          <div class="event-time">18:00</div>
          <div class="loc-wrap">
            <div class="event-location">Haapsalu,</div>
            <div class="event-venue">Haapsalu Jaani kirik</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>
</body></html>
"""


def _concert_hall_adapter():
    return EstoniaConcertHallAdapter(
        _make_source(slug="estonia_concert_hall", url="https://concert.ee/en/")
    )


class TestEstoniaConcertHallParseCards:
    def test_extracts_fields_and_image_from_style(self):
        adapter = _concert_hall_adapter()
        soup = BeautifulSoup(CONCERT_HALL_HTML, "html.parser")
        cards = adapter.parse_cards(soup)
        assert len(cards) == 2
        tallinn = cards[0]
        assert tallinn["title"] == "Tallinn Show"
        assert tallinn["venue"] == "Alexela Kontserdimaja"
        assert tallinn["location"] == "Tallinn,"
        assert tallinn["image_url"] == "https://concert.ee/img/tallinn.jpg"

    def test_tallinn_filter(self):
        adapter = _concert_hall_adapter()
        soup = BeautifulSoup(CONCERT_HALL_HTML, "html.parser")
        cards = adapter.parse_cards(soup)
        assert adapter.passes_filter(cards[0]) is True  # Tallinn,
        assert adapter.passes_filter(cards[1]) is False  # Haapsalu,

    def test_known_venue_gets_static_address_and_coords(self):
        html = CONCERT_HALL_HTML.replace(
            "Alexela Kontserdimaja", "Estonia kontserdisaal"
        )
        adapter = _concert_hall_adapter()
        soup = BeautifulSoup(html, "html.parser")
        cards = adapter.parse_cards(soup)
        info = ESTONIA_CONCERT_HALL_VENUES["Estonia kontserdisaal"]
        assert cards[0]["venue"] == info.name
        assert cards[0]["venue_address"] == info.address
        assert cards[0]["lat"] == info.lat
        assert cards[0]["lng"] == info.lng

    def test_unknown_venue_leaves_address_and_coords_unset(self):
        adapter = _concert_hall_adapter()
        soup = BeautifulSoup(CONCERT_HALL_HTML, "html.parser")
        cards = adapter.parse_cards(soup)
        assert cards[0]["venue"] == "Alexela Kontserdimaja"
        assert "venue_address" not in cards[0]
        assert "lat" not in cards[0]
        assert "lng" not in cards[0]


class TestEstoniaConcertHallParseDate:
    def test_parses_day_month_time_with_year_inference(self):
        adapter = _concert_hall_adapter()
        card = {"date_text": "Friday , 3.07", "time_text": "20:00"}
        result = adapter.parse_date(card)
        assert result is not None
        assert (result.month, result.day, result.hour, result.minute) == (7, 3, 20, 0)
        assert result.tzinfo == TALLINN_TZ
        now_year = datetime.now(TALLINN_TZ).year
        assert result.year in (now_year, now_year + 1)

    def test_missing_date_returns_none(self):
        adapter = _concert_hall_adapter()
        assert adapter.parse_date({"date_text": "", "time_text": "20:00"}) is None


class TestEstoniaConcertHallListingRequest:
    def test_page_one_posts_to_admin_ajax(self):
        adapter = _concert_hall_adapter()
        req = adapter.listing_request(1)
        assert req is not None
        assert isinstance(req, ListingRequest)
        assert req.method == "POST"
        assert req.url == f"https://concert.ee{ESTONIA_CONCERT_HALL_AJAX_PATH}"
        assert req.data == {
            "action": ESTONIA_CONCERT_HALL_AJAX_ACTION,
            "ek_ajax_count[]": str(ESTONIA_CONCERT_HALL_MAX_EVENTS),
        }

    def test_page_two_returns_none(self):
        adapter = _concert_hall_adapter()
        assert adapter.listing_request(2) is None


class TestEstoniaConcertHallFetchRaw:
    @pytest.mark.asyncio
    async def test_single_page_fetch_and_tallinn_filter(self):
        adapter = _concert_hall_adapter()
        with patch("app.ingestion.sources.html_base.http_post") as mock_post, \
                patch("app.ingestion.sources.html_base.http_get") as mock_get:
            mock_post.return_value = _mock_response(CONCERT_HALL_HTML)
            mock_get.return_value = _mock_response("<html></html>")
            raw_items = await adapter.fetch_raw(_known_ids())

        # 1 listing POST, 1 detail GET for the single Tallinn card that survives
        # the filter. mock_post is not called again since the detail page has
        # no pid link and no .main content, so parse_detail short-circuits
        # before the session bootstrap + price lookup.
        assert mock_post.call_count == 1
        _, url = mock_post.call_args.args
        assert url == f"https://concert.ee{ESTONIA_CONCERT_HALL_AJAX_PATH}"
        assert mock_post.call_args.kwargs["data"]["action"] == ESTONIA_CONCERT_HALL_AJAX_ACTION
        assert mock_get.call_count == 1
        assert len(raw_items) == 1
        assert raw_items[0]["title"] == "Tallinn Show"
        assert raw_items[0].get("price_hint") is None
        assert raw_items[0].get("description") is None


_CONCERT_HALL_DETAIL_WITH_PID_HTML = """
<html><body>
  <a href="https://www.piletilevi.ee/buy?pid=12345&foo=bar">Buy ticket</a>
</body></html>
"""


def _piletilevi_response(payload: dict):
    resp = MagicMock(spec=httpx.Response)
    resp.json.return_value = payload
    return resp


def _make_jwt(claims: dict) -> str:
    """Build a JWT-shaped string with a base64url-encoded payload (no real signature)."""
    payload = base64.urlsafe_b64encode(json_module.dumps(claims).encode()).rstrip(b"=")
    return f"header.{payload.decode()}.signature"


def _auth_response(session_key: str = "testkey"):
    resp = MagicMock(spec=httpx.Response)
    resp.json.return_value = {
        "accessToken": _make_jwt({"yellow_session": session_key})
    }
    return resp


class TestEstoniaConcertHallParseDetail:
    @pytest.mark.asyncio
    async def test_description_extracted_from_main_selector(self):
        adapter = _concert_hall_adapter()
        html = '<html><body><div class="main">Performers and programme notes.</div></body></html>'
        soup = BeautifulSoup(html, "html.parser")
        card: dict = {}
        await adapter.parse_detail(MagicMock(), soup, card)
        assert card["description"] == "Performers and programme notes."

    @pytest.mark.asyncio
    async def test_no_main_selector_leaves_description_unset(self):
        adapter = _concert_hall_adapter()
        soup = BeautifulSoup("<html><body>No content</body></html>", "html.parser")
        card: dict = {}
        await adapter.parse_detail(MagicMock(), soup, card)
        assert "description" not in card

    @pytest.mark.asyncio
    async def test_pid_resolves_price_via_piletilevi_store(self):
        adapter = _concert_hall_adapter()
        soup = BeautifulSoup(_CONCERT_HALL_DETAIL_WITH_PID_HTML, "html.parser")
        card: dict = {}
        payload = {
            "responseData": {
                "configuration": {
                    "sections": [
                        {"minPrice": "10.00", "maxPrice": "20.00"},
                        {"minPrice": "15.00", "maxPrice": "30.00"},
                    ]
                }
            }
        }
        with patch("app.ingestion.sources.estonia_concert_hall.http_post") as mock_post:
            mock_post.side_effect = [_auth_response("testkey"), _piletilevi_response(payload)]
            await adapter.parse_detail(MagicMock(), soup, card)

        assert card["price_min"] == 10.00
        assert card["price_max"] == 30.00
        assert card["currency"] == "EUR"
        assert "price_hint" not in card
        assert mock_post.call_count == 2
        _, price_url = mock_post.call_args_list[1].args
        assert price_url.startswith(ESTONIA_CONCERT_HALL_PILETILEVI_URL)
        assert "key=testkey" in price_url
        assert mock_post.call_args_list[1].kwargs["data"] == {"concert": "12345"}

    @pytest.mark.asyncio
    async def test_equal_min_max_price_collapses_to_single_value(self):
        adapter = _concert_hall_adapter()
        soup = BeautifulSoup(_CONCERT_HALL_DETAIL_WITH_PID_HTML, "html.parser")
        card: dict = {}
        payload = {
            "responseData": {
                "configuration": {"sections": [{"minPrice": "25.00", "maxPrice": "25.00"}]}
            }
        }
        with patch("app.ingestion.sources.estonia_concert_hall.http_post") as mock_post:
            mock_post.side_effect = [_auth_response("testkey"), _piletilevi_response(payload)]
            await adapter.parse_detail(MagicMock(), soup, card)

        assert card["price_min"] == 25.00
        assert card["price_max"] == 25.00
        assert card["currency"] == "EUR"
        assert "price_hint" not in card

    @pytest.mark.asyncio
    async def test_no_pid_link_leaves_card_unchanged(self):
        adapter = _concert_hall_adapter()
        soup = BeautifulSoup("<html><body>No ticket link</body></html>", "html.parser")
        card: dict = {}
        with patch("app.ingestion.sources.estonia_concert_hall.http_post") as mock_post:
            await adapter.parse_detail(MagicMock(), soup, card)

        assert mock_post.call_count == 0
        assert "price_min" not in card
        assert "price_hint" not in card

    @pytest.mark.asyncio
    async def test_session_bootstrap_failure_leaves_price_unchanged(self):
        adapter = _concert_hall_adapter()
        soup = BeautifulSoup(_CONCERT_HALL_DETAIL_WITH_PID_HTML, "html.parser")
        card: dict = {}
        with patch("app.ingestion.sources.estonia_concert_hall.http_post") as mock_post:
            mock_post.side_effect = httpx.HTTPStatusError(
                "error", request=MagicMock(), response=MagicMock()
            )
            await adapter.parse_detail(MagicMock(), soup, card)

        assert mock_post.call_count == 1  # only the failed auth call
        assert "price_min" not in card
        assert "price_hint" not in card

    @pytest.mark.asyncio
    async def test_piletilevi_request_failure_leaves_card_unchanged(self):
        adapter = _concert_hall_adapter()
        soup = BeautifulSoup(_CONCERT_HALL_DETAIL_WITH_PID_HTML, "html.parser")
        card: dict = {}
        with patch("app.ingestion.sources.estonia_concert_hall.http_post") as mock_post:
            mock_post.side_effect = [
                _auth_response("testkey"),
                httpx.HTTPStatusError("error", request=MagicMock(), response=MagicMock()),
            ]
            await adapter.parse_detail(MagicMock(), soup, card)

        assert "price_min" not in card
        assert "price_hint" not in card

    @pytest.mark.asyncio
    async def test_empty_sections_leaves_card_unchanged(self):
        adapter = _concert_hall_adapter()
        soup = BeautifulSoup(_CONCERT_HALL_DETAIL_WITH_PID_HTML, "html.parser")
        card: dict = {}
        payload = {"responseData": {"configuration": {"sections": []}}}
        with patch("app.ingestion.sources.estonia_concert_hall.http_post") as mock_post:
            mock_post.side_effect = [_auth_response("testkey"), _piletilevi_response(payload)]
            await adapter.parse_detail(MagicMock(), soup, card)

        assert "price_min" not in card
        assert "price_hint" not in card

    @pytest.mark.asyncio
    async def test_session_key_cached_across_cards(self):
        adapter = _concert_hall_adapter()
        soup = BeautifulSoup(_CONCERT_HALL_DETAIL_WITH_PID_HTML, "html.parser")
        payload = {"responseData": {"configuration": {"sections": [{"minPrice": "5.00", "maxPrice": "5.00"}]}}}
        with patch("app.ingestion.sources.estonia_concert_hall.http_post") as mock_post:
            mock_post.side_effect = [
                _auth_response("testkey"),
                _piletilevi_response(payload),
                _piletilevi_response(payload),
            ]
            card1: dict = {}
            card2: dict = {}
            await adapter.parse_detail(MagicMock(), soup, card1)
            await adapter.parse_detail(MagicMock(), soup, card2)

        # 1 auth call total, 2 price calls — session key reused across cards.
        assert mock_post.call_count == 3
        assert card1["price_min"] == 5.00
        assert card1["price_max"] == 5.00
        assert card2["price_min"] == 5.00
        assert card2["price_max"] == 5.00


# ---------------------------------------------------------------------------
# kumu_localized_text / estonia_concert_hall_localized_text
# ---------------------------------------------------------------------------

_KUMU_DETAIL_HTML_ET = """
<html><head>
<meta property="og:title" content="Kumu katuseterrassi külastus - Kumu kunstimuuseum"/>
</head><body>
<div class="single__content-dynamic">Kumu muuseum on avatud igal nädalavahetusel.</div>
</body></html>
"""

_KUMU_DETAIL_HTML_EN = """
<html><head>
<meta property="og:title" content="Visit to Kumu Rooftop Terrace - Kumu kunstimuuseum"/>
</head><body>
<div class="single__content-dynamic">Kumu museum is open every weekend.</div>
</body></html>
"""

_KUMU_DETAIL_HTML_NO_OG = """
<html><body>
<h1>Kumu katuseterrassi külastus 28.06.2026 | 13.00</h1>
<div class="single__content-dynamic">Muuseumi külastus.</div>
</body></html>
"""

_KUMU_DETAIL_HTML_EMPTY = "<html><body></body></html>"

_ECH_DETAIL_HTML_EN = """
<html><head>
<meta property="og:title" content="Summer Classics at Niguliste - Eesti Kontsert"/>
</head><body>
<div class="main">An evening of classical music in historic Niguliste church.</div>
</body></html>
"""

_ECH_DETAIL_HTML_ET = """
<html><head>
<meta property="og:title" content="Suveklassika Niguliste kirikus - Eesti Kontsert"/>
</head><body>
<div class="main">Klassikalise muusika õhtu ajaloolises Niguliste kirikus.</div>
</body></html>
"""

_ECH_DETAIL_HTML_EMPTY = "<html><head></head><body></body></html>"

_PILETILEVI_DETAIL_HTML_WITH_JSONLD = """
<html><head>
<script type="application/ld+json">
{"@type": "Event", "name": "Jazz Night", "description": "A jazz evening."}
</script>
<meta property="og:title" content="Jazz Night - Piletilevi"/>
</head><body></body></html>
"""


class TestKumuLocalizedText:
    def test_suffix_stripped_from_og_title(self):
        soup = BeautifulSoup(_KUMU_DETAIL_HTML_ET, "html.parser")
        title, _ = kumu_localized_text(soup)
        assert title == "Kumu katuseterrassi külastus"
        assert KUMU_SITE_TITLE_SUFFIX not in (title or "")

    def test_description_from_content_dynamic_selector(self):
        soup = BeautifulSoup(_KUMU_DETAIL_HTML_ET, "html.parser")
        _, desc = kumu_localized_text(soup)
        assert desc == "Kumu muuseum on avatud igal nädalavahetusel."

    def test_english_variant_also_suffix_stripped(self):
        soup = BeautifulSoup(_KUMU_DETAIL_HTML_EN, "html.parser")
        title, _ = kumu_localized_text(soup)
        assert title == "Visit to Kumu Rooftop Terrace"

    def test_fallback_to_h1_when_og_title_absent(self):
        soup = BeautifulSoup(_KUMU_DETAIL_HTML_NO_OG, "html.parser")
        title, _ = kumu_localized_text(soup)
        assert title == "Kumu katuseterrassi külastus 28.06.2026 | 13.00"

    def test_returns_none_none_when_page_has_no_text(self):
        soup = BeautifulSoup(_KUMU_DETAIL_HTML_EMPTY, "html.parser")
        title, desc = kumu_localized_text(soup)
        assert title is None
        assert desc is None


class TestEstoniaConcertHallLocalizedText:
    def test_suffix_stripped_from_og_title(self):
        soup = BeautifulSoup(_ECH_DETAIL_HTML_EN, "html.parser")
        title, _ = estonia_concert_hall_localized_text(soup)
        assert title == "Summer Classics at Niguliste"
        assert ECH_SITE_TITLE_SUFFIX not in (title or "")

    def test_description_from_main_selector(self):
        soup = BeautifulSoup(_ECH_DETAIL_HTML_EN, "html.parser")
        _, desc = estonia_concert_hall_localized_text(soup)
        assert desc == "An evening of classical music in historic Niguliste church."

    def test_estonian_variant_suffix_stripped(self):
        soup = BeautifulSoup(_ECH_DETAIL_HTML_ET, "html.parser")
        title, _ = estonia_concert_hall_localized_text(soup)
        assert title == "Suveklassika Niguliste kirikus"

    def test_returns_none_none_when_page_has_no_text(self):
        soup = BeautifulSoup(_ECH_DETAIL_HTML_EMPTY, "html.parser")
        title, desc = estonia_concert_hall_localized_text(soup)
        assert title is None
        assert desc is None


class TestExtractLocalizedTextHook:
    def test_base_default_delegates_to_jsonld(self):
        """HtmlListingAdapter.extract_localized_text default uses JSON-LD.

        Uses a bare _StubAdapter (not Piletilevi, which now overrides this
        hook with piletilevi_localized_text — see TestPiletileviLocalizedText)
        to exercise the base class's own default behavior in isolation.
        """
        adapter = _StubAdapter(_make_source(), pages_cards=[])
        soup = BeautifulSoup(_PILETILEVI_DETAIL_HTML_WITH_JSONLD, "html.parser")
        title, desc = adapter.extract_localized_text(soup)
        assert title == "Jazz Night"
        assert desc == "A jazz evening."

    def test_piletilevi_adapter_uses_html_description_not_jsonld(self):
        """PiletileviAdapter overrides the hook to avoid the glued JSON-LD text."""
        adapter = _piletilevi_adapter()
        soup = BeautifulSoup(
            PILETILEVI_DETAIL_WITH_MULTI_PARAGRAPH_DESC_HTML, "html.parser"
        )
        title, desc = adapter.extract_localized_text(soup)
        assert title == "Summer Flower Ball"
        assert desc == "<p>First paragraph text.</p><p>Second paragraph glued on.</p>"

    def test_kumu_adapter_uses_og_title(self):
        adapter = _kumu_adapter()
        soup = BeautifulSoup(_KUMU_DETAIL_HTML_EN, "html.parser")
        title, _ = adapter.extract_localized_text(soup)
        assert title == "Visit to Kumu Rooftop Terrace"

    def test_ech_adapter_uses_og_title(self):
        adapter = _concert_hall_adapter()
        soup = BeautifulSoup(_ECH_DETAIL_HTML_EN, "html.parser")
        title, _ = adapter.extract_localized_text(soup)
        assert title == "Summer Classics at Niguliste"


# ---------------------------------------------------------------------------
# full_res_wp_image
# ---------------------------------------------------------------------------


class TestFullResWpImage:
    def test_strips_wp_thumbnail_suffix_concert(self):
        url = "https://concert.ee/wp-content/uploads/2024/01/poster-82x118.jpg"
        expected = "https://concert.ee/wp-content/uploads/2024/01/poster.jpg"
        assert full_res_wp_image(url) == expected

    def test_strips_arbitrary_dims_concert(self):
        url = "https://concert.ee/img/555x800px_Jouluks-koju-555x800.jpg"
        # Only the trailing -WxH suffix is stripped; an in-name "555x800px" stays.
        expected = "https://concert.ee/img/555x800px_Jouluks-koju.jpg"
        assert full_res_wp_image(url) == expected

    def test_concert_url_without_suffix_unchanged(self):
        url = "https://concert.ee/wp-content/uploads/2024/01/poster.jpg"
        assert full_res_wp_image(url) == url

    def test_strips_wp_thumbnail_suffix_kumu(self):
        url = "https://kumu.ekm.ee/wp-content/uploads/2024/01/exhibit-200x200.jpg"
        expected = "https://kumu.ekm.ee/wp-content/uploads/2024/01/exhibit.jpg"
        assert full_res_wp_image(url) == expected

    def test_kumu_url_without_suffix_unchanged(self):
        url = "https://kumu.ekm.ee/wp-content/uploads/2024/01/exhibit.jpg"
        assert full_res_wp_image(url) == url

    def test_piletilevi_url_untouched(self):
        # piletilevi.ee is not in WP_THUMBNAIL_HOSTS — never rewritten here.
        url = "https://www.piletilevi.ee/media/event-481x252.jpg"
        assert full_res_wp_image(url) == url

    def test_fienta_query_string_url_untouched(self):
        url = "https://fienta.com/image?w=1070&h=601"
        assert full_res_wp_image(url) == url

    def test_concert_query_string_not_at_end_untouched(self):
        # The \.\w+$ anchor means a suffix mid-URL (before a query) is left alone.
        url = "https://concert.ee/img/poster-82x118.jpg?ver=2"
        assert full_res_wp_image(url) == url

    def test_none_returns_none(self):
        assert full_res_wp_image(None) is None


# ---------------------------------------------------------------------------
# full_res_piletilevi_image
# ---------------------------------------------------------------------------


class TestFullResPiletileviImage:
    def test_rewrites_height_segment(self):
        url = "https://www.piletilevi.ee/i/height=252/images/event.jpg"
        expected = "https://www.piletilevi.ee/i/height=1009/images/event.jpg"
        assert full_res_piletilevi_image(url) == expected

    def test_rewrites_any_height_value(self):
        url = "https://www.piletilevi.ee/i/height=100/img/poster.png"
        expected = "https://www.piletilevi.ee/i/height=1009/img/poster.png"
        assert full_res_piletilevi_image(url) == expected

    def test_url_without_height_segment_unchanged(self):
        url = "https://www.piletilevi.ee/images/event.jpg"
        assert full_res_piletilevi_image(url) == url

    def test_concert_url_untouched(self):
        url = "https://concert.ee/wp-content/uploads/poster-82x118.jpg"
        assert full_res_piletilevi_image(url) == url

    def test_fienta_url_untouched(self):
        url = "https://fienta.com/image?w=1070&h=601"
        assert full_res_piletilevi_image(url) == url

    def test_none_returns_none(self):
        assert full_res_piletilevi_image(None) is None
