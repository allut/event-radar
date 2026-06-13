"""Tests for HtmlListingAdapter base + Piletilevi/Kumu/EstoniaConcertHall/Telliskivi."""
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest
import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.constants import (
    ESTONIA_CONCERT_HALL_AJAX_ACTION,
    ESTONIA_CONCERT_HALL_AJAX_PATH,
    ESTONIA_CONCERT_HALL_MAX_EVENTS,
    TALLINN_TZ,
)
from app.ingestion.base import NormalizedEvent
from app.ingestion.sources.html_listing import (
    EstoniaConcertHallAdapter,
    HtmlListingAdapter,
    KumuAdapter,
    ListingRequest,
    PiletileviAdapter,
    TelliskiviAdapter,
    _next_occurrence_year,
    _parse_piletilevi_date,
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


# ---------------------------------------------------------------------------
# _next_occurrence_year
# ---------------------------------------------------------------------------


class TestNextOccurrenceYear:
    def test_future_date_this_year(self):
        assert _next_occurrence_year(12, 2, today=date(2026, 6, 12)) == 2026

    def test_past_date_rolls_to_next_year(self):
        assert _next_occurrence_year(5, 30, today=date(2026, 6, 12)) == 2027

    def test_today_itself_stays_this_year(self):
        assert _next_occurrence_year(6, 12, today=date(2026, 6, 12)) == 2026


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

    def parse_detail(self, soup, card):
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

        with patch("app.ingestion.sources.html_listing.http_get") as mock_get:
            mock_get.side_effect = [_mock_response("0")]
            results = await adapter.fetch_raw()

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

        with patch("app.ingestion.sources.html_listing.http_get") as mock_get:
            mock_get.side_effect = [_mock_response("0"), _mock_response("1")]
            results = await adapter.fetch_raw()

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

        with patch("app.ingestion.sources.html_listing.http_get") as mock_get:
            mock_get.side_effect = [_mock_response("0"), _mock_response("1")]
            results = await adapter.fetch_raw()

        assert mock_get.call_count == 2
        assert [c["external_id"] for c in results] == ["a", "b"]

    @pytest.mark.asyncio
    async def test_listing_error_raises_when_no_cards_collected(self):
        adapter = _StubAdapter(_make_source(), pages_cards=[[]], max_pages=1)

        with patch("app.ingestion.sources.html_listing.http_get") as mock_get:
            mock_get.side_effect = [httpx.ConnectError("boom")]
            with pytest.raises(httpx.ConnectError):
                await adapter.fetch_raw()

    @pytest.mark.asyncio
    async def test_listing_error_tolerated_when_other_pages_succeed(self):
        card_a = {"external_id": "a", "title": "A", "url": "https://example.test/a"}
        adapter = _StubAdapter(
            _make_source(),
            pages_cards=[[], [card_a]],
            max_pages=2,
        )

        with patch("app.ingestion.sources.html_listing.http_get") as mock_get:
            mock_get.side_effect = [httpx.ConnectError("boom"), _mock_response("1")]
            results = await adapter.fetch_raw()

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

        with patch("app.ingestion.sources.html_listing.HTML_LISTING_MAX_DETAIL_FETCHES", 2), \
             patch("app.ingestion.sources.html_listing.http_get") as mock_get:
            mock_get.side_effect = [
                _mock_response("0"),  # listing page 1
                _mock_response("detail-a"),  # detail for card a
                _mock_response("detail-b"),  # detail for card b
            ]
            results = await adapter.fetch_raw()

        # Detail cap (2) truncates the 3 collected cards before detail fetches
        assert [c["external_id"] for c in results] == ["a", "b"]
        assert results[0]["description"] == "detail-a"
        assert results[1]["description"] == "detail-b"
        assert mock_get.call_count == 3

    @pytest.mark.asyncio
    async def test_detail_fetch_failure_is_swallowed(self):
        card_a = {"external_id": "a", "title": "A", "url": "https://example.test/a"}
        adapter = _StubAdapter(
            _make_source(),
            pages_cards=[[card_a]],
            needs_detail=True,
            max_pages=1,
        )

        with patch("app.ingestion.sources.html_listing.http_get") as mock_get:
            mock_get.side_effect = [
                _mock_response("0"),
                httpx.ConnectError("detail down"),
            ]
            results = await adapter.fetch_raw()

        assert [c["external_id"] for c in results] == ["a"]
        assert "description" not in results[0]


class TestBaseListingRequestDispatch:
    @pytest.mark.asyncio
    async def test_post_method_dispatches_to_http_post(self):
        card_a = {"external_id": "a", "title": "A", "url": "https://example.test/a"}
        adapter = _PostStubAdapter(_make_source(), cards=[card_a])

        with patch("app.ingestion.sources.html_listing.http_post") as mock_post, \
             patch("app.ingestion.sources.html_listing.http_get") as mock_get:
            mock_post.return_value = _mock_response("<html></html>")
            results = await adapter.fetch_raw()

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
        assert jazz["image_url"] == "https://www.piletilevi.ee/i/height=252/images/aa1.jpg"

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

        with patch("app.ingestion.sources.html_listing.http_get") as mock_get:
            mock_get.side_effect = [
                listing_resp,  # page 1 — 2 cards survive the Tallinn filter
                empty_resp,  # page 2 — no cards → pagination halts
                detail_resp,  # detail fetch for Jazz Night
                detail_resp,  # detail fetch for Festival Pass... no, dropped by normalize
            ]
            results = await adapter.fetch_raw()

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
        with patch("app.ingestion.sources.html_listing.http_get") as mock_get:
            mock_get.side_effect = [
                _mock_response(single_card_html),
                _mock_response(PILETILEVI_EMPTY_HTML),
                _mock_response(PILETILEVI_DETAIL_HTML),
            ]
            results = await adapter.fetch_raw()

        assert len(results) == 1
        assert (
            results[0]["description"]
            == "A wonderful jazz evening with local musicians."
        )

    @pytest.mark.asyncio
    async def test_empty_first_page_raises_on_fetch_error(self):
        adapter = _piletilevi_adapter()
        with patch("app.ingestion.sources.html_listing.http_get") as mock_get:
            mock_get.side_effect = httpx.ConnectError("down")
            with pytest.raises(httpx.ConnectError):
                await adapter.fetch_raw()


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
        with patch("app.ingestion.sources.html_listing.http_get") as mock_get:
            # Both fetches return the same page — page 2 yields zero new ids
            # (all already seen on page 1), so pagination stops there.
            mock_get.return_value = _mock_response(KUMU_LISTING_HTML)
            raw_items = await adapter.fetch_raw()

        assert mock_get.call_count == 2
        assert len(raw_items) == 2  # both raw cards collected
        normalized = [adapter.normalize(r) for r in raw_items]
        normalized = [n for n in normalized if n is not None]
        assert len(normalized) == 1  # "Bad Date Event" dropped by normalize
        assert normalized[0].title == "Example Concert"

    @pytest.mark.asyncio
    async def test_pagination_stops_on_empty_page_and_dedups(self):
        adapter = _kumu_adapter()
        with patch("app.ingestion.sources.html_listing.http_get") as mock_get:
            mock_get.side_effect = [
                _mock_response(KUMU_LISTING_HTML),
                _mock_response(KUMU_PAGE2_HTML),
                _mock_response(KUMU_EMPTY_PAGE_HTML),
            ]
            raw_items = await adapter.fetch_raw()

        assert mock_get.call_count == 3
        urls = [call.args[1] for call in mock_get.call_args_list]
        assert urls == [
            "https://example.test/listing",
            "https://example.test/listing/page/2/",
            "https://example.test/listing/page/3/",
        ]
        assert {c["external_id"] for c in raw_items} == {
            "https://kumu.ekm.ee/en/syndmus/example-1/",
            "https://kumu.ekm.ee/en/syndmus/example-2/",
            "https://kumu.ekm.ee/en/syndmus/example-3/",
        }


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
        with patch("app.ingestion.sources.html_listing.http_post") as mock_post:
            mock_post.return_value = _mock_response(CONCERT_HALL_HTML)
            raw_items = await adapter.fetch_raw()

        assert mock_post.call_count == 1
        _, url = mock_post.call_args.args
        assert url == f"https://concert.ee{ESTONIA_CONCERT_HALL_AJAX_PATH}"
        assert mock_post.call_args.kwargs["data"]["action"] == ESTONIA_CONCERT_HALL_AJAX_ACTION
        assert len(raw_items) == 1
        assert raw_items[0]["title"] == "Tallinn Show"


# ---------------------------------------------------------------------------
# TelliskiviAdapter — telliskivi.cc/en/events/
# ---------------------------------------------------------------------------

TELLISKIVI_HTML = """
<html><body>
  <div class="card card--featured">
    <a class="card__overlay-link" href="https://telliskivi.cc/en/events/example-1/"></a>
    <div class="card__image">
      <img class="image__img lazyload" data-srcset="https://telliskivi.cc/img-300.png 300w, https://telliskivi.cc/img-600.png 600w" src="data:image/gif;base64,placeholder"/>
    </div>
    <div class="card__content">
      <div class="card__timestamp">
        <div class="card__timestamp-item">
          <span class="card__timestamp-date">Dec 2</span>
          <span class="card__timestamp-day">Wednesday</span>
        </div>
      </div>
      <h3 class="card__title">December Market</h3>
    </div>
  </div>
  <div class="card">
    <a class="card__overlay-link" href="https://telliskivi.cc/en/events/example-2/"></a>
    <div class="card__content">
      <div class="card__timestamp">
        <div class="card__timestamp-item">
          <span class="card__timestamp-date">not a date</span>
        </div>
      </div>
      <h3 class="card__title">Bad Date Event</h3>
    </div>
  </div>
</body></html>
"""


def _telliskivi_adapter():
    return TelliskiviAdapter(_make_source(slug="telliskivi"))


class TestTelliskiviParseCards:
    def test_extracts_fields(self):
        adapter = _telliskivi_adapter()
        soup = BeautifulSoup(TELLISKIVI_HTML, "html.parser")
        cards = adapter.parse_cards(soup)
        assert len(cards) == 2
        assert cards[0]["title"] == "December Market"
        assert cards[0]["external_id"] == "https://telliskivi.cc/en/events/example-1/"
        assert cards[0]["image_url"] == "https://telliskivi.cc/img-300.png"
        assert cards[0]["date_str"] == "Dec 2"


class TestTelliskiviParseDate:
    def test_parses_month_day_with_year_inference(self):
        adapter = _telliskivi_adapter()
        result = adapter.parse_date({"date_str": "Dec 2"})
        assert result is not None
        assert (result.month, result.day, result.hour, result.minute) == (12, 2, 0, 0)
        assert result.tzinfo == TALLINN_TZ
        now_year = datetime.now(TALLINN_TZ).year
        assert result.year in (now_year, now_year + 1)

    def test_unparseable_date_returns_none(self):
        adapter = _telliskivi_adapter()
        assert adapter.parse_date({"date_str": "not a date"}) is None


class TestTelliskiviFetchRaw:
    @pytest.mark.asyncio
    async def test_single_page_fetch_drops_unparseable_date_card(self):
        adapter = _telliskivi_adapter()
        with patch("app.ingestion.sources.html_listing.http_get") as mock_get:
            mock_get.return_value = _mock_response(TELLISKIVI_HTML)
            raw_items = await adapter.fetch_raw()

        assert mock_get.call_count == 1
        assert len(raw_items) == 2
        normalized = [n for n in (adapter.normalize(r) for r in raw_items) if n]
        assert len(normalized) == 1
        assert normalized[0].title == "December Market"
