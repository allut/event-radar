"""Unit tests for sanitize_html and html_to_text helpers, plus Fienta HTML description."""

import asyncio
from unittest.mock import MagicMock

import httpx
import pytest

from bs4 import BeautifulSoup

from app.constants import LOCALIZED_TEXT_FIENTA_LOCALES
from app.ingestion.base import AsyncRateLimiter, html_to_text, locale_from_html_lang, sanitize_html
from app.ingestion.sources.fienta import FientaAdapter


class TestSanitizeHtml:
    def test_none_returns_none(self) -> None:
        assert sanitize_html(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert sanitize_html("") is None

    def test_plain_text_passes_through(self) -> None:
        assert sanitize_html("Hello world") == "Hello world"

    def test_allowed_tags_preserved(self) -> None:
        html = "<p><strong>Bold</strong> and <em>italic</em></p>"
        result = sanitize_html(html)
        assert result is not None
        assert "<strong>Bold</strong>" in result
        assert "<em>italic</em>" in result
        assert "<p>" in result

    def test_allowed_list_tags_preserved(self) -> None:
        html = "<ul><li>Item 1</li><li>Item 2</li></ul>"
        result = sanitize_html(html)
        assert result is not None
        assert "<ul>" in result
        assert "<li>Item 1</li>" in result

    def test_allowed_link_preserved(self) -> None:
        html = '<a href="https://example.com" title="Test">Link</a>'
        result = sanitize_html(html)
        assert result is not None
        assert "https://example.com" in result
        assert ">Link<" in result

    def test_script_tag_stripped(self) -> None:
        html = "<p>Safe</p><script>alert('xss')</script>"
        result = sanitize_html(html)
        assert result is not None
        assert "<script>" not in result
        assert "alert" not in result

    def test_onclick_attr_stripped(self) -> None:
        html = '<p onclick="alert(1)">Text</p>'
        result = sanitize_html(html)
        assert result is not None
        assert "onclick" not in result
        assert "Text" in result

    def test_javascript_href_stripped(self) -> None:
        html = '<a href="javascript:alert(1)">Click</a>'
        result = sanitize_html(html)
        assert result is not None
        assert "javascript:" not in result

    def test_iframe_stripped(self) -> None:
        html = "<p>Good</p><iframe src='evil.com'></iframe>"
        result = sanitize_html(html)
        assert result is not None
        assert "iframe" not in result

    def test_style_attr_stripped(self) -> None:
        html = '<p style="color:red">Text</p>'
        result = sanitize_html(html)
        assert result is not None
        assert "style=" not in result
        assert "Text" in result

    def test_heading_tags_preserved(self) -> None:
        html = "<h3>Title</h3><h4>Sub</h4>"
        result = sanitize_html(html)
        assert result is not None
        assert "<h3>Title</h3>" in result
        assert "<h4>Sub</h4>" in result

    def test_br_preserved(self) -> None:
        result = sanitize_html("Line 1<br>Line 2")
        assert result is not None
        assert "<br" in result

    def test_data_url_href_stripped(self) -> None:
        html = '<a href="data:text/html,<script>alert(1)</script>">Click</a>'
        result = sanitize_html(html)
        assert result is not None
        assert "data:" not in result

    def test_div_lines_become_breaks(self) -> None:
        # Piletilevi-style: each line wrapped in a bare <div>. Without conversion,
        # nh3 strips the divs and the lines glue together ("AB").
        result = sanitize_html("<div>Line A</div><div>Line B</div>")
        assert result is not None
        assert "<div>" not in result
        assert "Line A<br>Line B" in result

    def test_div_no_runon_glue(self) -> None:
        result = sanitize_html("<div>W. Herrndorf, R. Koall</div><div>Lavastaja P.</div>")
        assert result is not None
        assert "KoallLavastaja" not in result
        assert "Koall<br>Lavastaja" in result

    def test_nested_and_empty_divs_collapsed(self) -> None:
        html = "<div><div>A</div><div> </div><div>B</div></div>"
        result = sanitize_html(html)
        assert result is not None
        assert "<div>" not in result
        # Runs of <br> capped; never more than the configured max in a row.
        assert "<br><br><br>" not in result
        assert "A" in result and "B" in result

    def test_div_inner_inline_tags_preserved(self) -> None:
        html = "<div>Plot <em>twist</em></div><div><strong>Bold</strong> line</div>"
        result = sanitize_html(html)
        assert result is not None
        assert "<em>twist</em>" in result
        assert "<strong>Bold</strong>" in result
        assert "<br>" in result

    def test_leading_trailing_breaks_trimmed(self) -> None:
        result = sanitize_html("<div>Only line</div>")
        assert result is not None
        assert not result.startswith("<br>")
        assert not result.endswith("<br>")
        assert "Only line" in result

    def test_edge_break_strips_adjacent_whitespace(self) -> None:
        # Whitespace flanking a leading/trailing <br> (from `<div>content </div>`)
        # must be consumed too, leaving no stray edge whitespace.
        result = sanitize_html("<div>content </div>")
        assert result is not None
        assert result == "content"

    def test_div_with_link_preserved(self) -> None:
        html = '<div>See <a href="https://example.com">here</a></div><div>Next</div>'
        result = sanitize_html(html)
        assert result is not None
        assert "https://example.com" in result
        assert "here</a><br>Next" in result


class TestHtmlToText:
    def test_none_returns_none(self) -> None:
        assert html_to_text(None) is None

    def test_empty_string_returns_empty(self) -> None:
        assert html_to_text("") == ""

    def test_plain_text_unchanged(self) -> None:
        assert html_to_text("Hello world") == "Hello world"

    def test_strips_p_tags(self) -> None:
        result = html_to_text("<p>Paragraph one</p><p>Paragraph two</p>")
        assert result is not None
        assert "<p>" not in result
        assert "Paragraph one" in result
        assert "Paragraph two" in result

    def test_strips_strong_tags(self) -> None:
        result = html_to_text("<p><strong>Bold text</strong> normal</p>")
        assert result is not None
        assert "<strong>" not in result
        assert "Bold text" in result

    def test_strips_list_tags(self) -> None:
        result = html_to_text("<ul><li>Item A</li><li>Item B</li></ul>")
        assert result is not None
        assert "<ul>" not in result
        assert "<li>" not in result
        assert "Item A" in result
        assert "Item B" in result


# ---------------------------------------------------------------------------
# locale_from_html_lang
# ---------------------------------------------------------------------------

class TestLocaleFromHtmlLang:
    def _soup(self, html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "html.parser")

    def test_en_lang_returns_en(self) -> None:
        soup = self._soup('<html lang="en"><body></body></html>')
        assert locale_from_html_lang(soup, LOCALIZED_TEXT_FIENTA_LOCALES) == "en"

    def test_et_ee_normalizes_to_et(self) -> None:
        soup = self._soup('<html lang="et-EE"><body></body></html>')
        assert locale_from_html_lang(soup, LOCALIZED_TEXT_FIENTA_LOCALES) == "et"

    def test_unknown_lang_returns_none(self) -> None:
        soup = self._soup('<html lang="fr"><body></body></html>')
        assert locale_from_html_lang(soup, LOCALIZED_TEXT_FIENTA_LOCALES) is None

    def test_missing_lang_attr_returns_none(self) -> None:
        soup = self._soup("<html><body></body></html>")
        assert locale_from_html_lang(soup, LOCALIZED_TEXT_FIENTA_LOCALES) is None

    def test_fragment_with_no_lang_attr_returns_none(self) -> None:
        # html.parser wraps bare fragments in <html> — this tests the missing-lang path
        soup = self._soup("<p>content</p>")
        assert locale_from_html_lang(soup, LOCALIZED_TEXT_FIENTA_LOCALES) is None


# ---------------------------------------------------------------------------
# Fienta HTML description — normalize() and _fetch_detail()
# ---------------------------------------------------------------------------

def _make_fienta_source(organizer_ids: list[int] | None = None) -> MagicMock:
    source = MagicMock()
    source.config = {"organizer_ids": organizer_ids or [1]}
    return source


def _fienta_adapter() -> FientaAdapter:
    return FientaAdapter(_make_fienta_source())


def _base_raw(**overrides: object) -> dict:
    raw: dict = {
        "id": "42",
        "name": "Test Event",
        "starts_at": "2026-08-01T20:00:00+03:00",
        "venue": {"name": "Vaba Lava", "address": "Telliskivi 60a/3, Tallinn"},
    }
    raw.update(overrides)
    return raw


class TestFientaNormalizeHtml:
    def test_normalize_sanitizes_listing_html(self) -> None:
        raw = _base_raw(description="<p>Cool event</p><script>alert(1)</script>")
        result = _fienta_adapter().normalize(raw)
        assert result is not None
        assert result.description is not None
        assert "<p>Cool event</p>" in result.description
        assert "<script>" not in result.description
        assert "alert" not in result.description

    def test_normalize_plain_text_passes_through(self) -> None:
        raw = _base_raw(description="Just plain text")
        result = _fienta_adapter().normalize(raw)
        assert result is not None
        assert result.description == "Just plain text"

    def test_normalize_none_description_stays_none(self) -> None:
        raw = _base_raw()
        result = _fienta_adapter().normalize(raw)
        assert result is not None
        assert result.description is None

    def test_normalize_body_field_sanitized_when_description_absent(self) -> None:
        raw = _base_raw(body="<p>Body field</p><script>bad</script>")
        result = _fienta_adapter().normalize(raw)
        assert result is not None
        assert result.description is not None
        assert "<p>Body field</p>" in result.description
        assert "<script>" not in result.description


# English-default detail page: no redirect, lang="en", has locale alternates.
_EN_DEFAULT_HTML = (
    '<html lang="en"><head>'
    '<link rel="alternate" hreflang="et" href="https://fienta.com/et/event-88"/>'
    '<link rel="alternate" hreflang="en" href="https://fienta.com/en/event-88"/>'
    '</head><body>'
    '<script type="application/ld+json">'
    '{"@type":"Event","name":"Great Show","description":"Plain text from JSON-LD"}'
    "</script></body></html>"
)

_ET_HTML_88 = (
    "<html><body>"
    '<script type="application/ld+json">'
    '{"@type":"Event","name":"Suur Show","description":"Eesti tekst"}'
    "</script></body></html>"
)

# Minimal HTML page template for detail-page stubs.
_DETAIL_HTML_TEMPLATE = (
    '<html><head>'
    '<link rel="alternate" hreflang="et" href="https://fienta.com/et/event-99"/>'
    '<link rel="alternate" hreflang="en" href="https://fienta.com/en/event-99"/>'
    '<link rel="alternate" hreflang="ru" href="https://fienta.com/ru/event-99"/>'
    '</head><body>'
    '<script type="application/ld+json">'
    '{"@type":"Event","name":"Sündmus","description":"Tere"}'
    "</script></body></html>"
)

_EN_HTML = (
    "<html><body>"
    '<script type="application/ld+json">'
    '{"@type":"Event","name":"Event","description":"Hello"}'
    "</script></body></html>"
)

_RU_HTML = (
    "<html><body>"
    '<script type="application/ld+json">'
    '{"@type":"Event","name":"Мероприятие","description":"Привет"}'
    "</script></body></html>"
)


class TestFetchDetailPrimaryLocaleHtml:
    """_fetch_detail seeds primary-locale description_localized with sanitized listing HTML."""

    @pytest.mark.asyncio
    async def test_primary_locale_desc_is_sanitized_listing_html(self) -> None:
        """Primary locale gets sanitized HTML from item['description'], not plain JSON-LD."""
        item: dict = {
            "id": "99",
            "description": "<p>Tere</p><script>bad</script>",
            "url": "https://fienta.com/event-99",
        }

        async def handler(request: httpx.Request) -> httpx.Response:
            url_str = str(request.url)
            if "/en/event-99" in url_str:
                return httpx.Response(200, text=_EN_HTML, headers={"content-type": "text/html"})
            if "/ru/event-99" in url_str:
                return httpx.Response(200, text=_RU_HTML, headers={"content-type": "text/html"})
            if url_str == "https://fienta.com/event-99":
                return httpx.Response(
                    302,
                    headers={"location": "https://fienta.com/et/event-99"},
                )
            # /et/event-99 — the redirect target
            return httpx.Response(200, text=_DETAIL_HTML_TEMPLATE, headers={"content-type": "text/html"})

        adapter = _fienta_adapter()
        semaphore = asyncio.Semaphore(1)
        limiter = AsyncRateLimiter(0)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            follow_redirects=True,
        ) as client:
            await adapter._fetch_detail(client, item, "fienta.com", semaphore, limiter)

        assert "_detail_localized" in item
        descs = item["_detail_localized"]["description"]

        # Primary locale (et): sanitized HTML, not JSON-LD plain text
        et_desc = descs.get("et")
        assert et_desc is not None
        assert "<p>Tere</p>" in et_desc
        assert "<script>" not in et_desc
        assert "bad" not in et_desc

        # Non-primary locales: JSON-LD plain text (no HTML tags)
        en_desc = descs.get("en")
        assert en_desc == "Hello"
        ru_desc = descs.get("ru")
        assert ru_desc == "Привет"

    @pytest.mark.asyncio
    async def test_primary_locale_title_from_jsonld_not_listing_api(self) -> None:
        """Title for primary locale still comes from JSON-LD (listing API has no locale variant)."""
        item: dict = {
            "id": "99",
            "description": "<p>Tere</p>",
            "url": "https://fienta.com/event-99",
        }

        async def handler(request: httpx.Request) -> httpx.Response:
            url_str = str(request.url)
            if "/en/event-99" in url_str:
                return httpx.Response(200, text=_EN_HTML, headers={"content-type": "text/html"})
            if "/ru/event-99" in url_str:
                return httpx.Response(200, text=_RU_HTML, headers={"content-type": "text/html"})
            if url_str == "https://fienta.com/event-99":
                return httpx.Response(
                    302,
                    headers={"location": "https://fienta.com/et/event-99"},
                )
            return httpx.Response(200, text=_DETAIL_HTML_TEMPLATE, headers={"content-type": "text/html"})

        adapter = _fienta_adapter()
        semaphore = asyncio.Semaphore(1)
        limiter = AsyncRateLimiter(0)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            follow_redirects=True,
        ) as client:
            await adapter._fetch_detail(client, item, "fienta.com", semaphore, limiter)

        titles = item["_detail_localized"]["title"]
        assert titles.get("et") == "Sündmus"
        assert titles.get("en") == "Event"

    @pytest.mark.asyncio
    async def test_english_default_page_seeds_en_html(self) -> None:
        """English-default Fienta page (no /en/ redirect, lang='en') seeds en HTML description."""
        item: dict = {
            "id": "88",
            "description": "<p>Rich HTML content</p><strong>Bold</strong>",
            "url": "https://fienta.com/event-88",
        }

        async def handler(request: httpx.Request) -> httpx.Response:
            url_str = str(request.url)
            if "/et/event-88" in url_str:
                return httpx.Response(200, text=_ET_HTML_88, headers={"content-type": "text/html"})
            # Canonical URL: no redirect — English default
            return httpx.Response(200, text=_EN_DEFAULT_HTML, headers={"content-type": "text/html"})

        adapter = _fienta_adapter()
        semaphore = asyncio.Semaphore(1)
        limiter = AsyncRateLimiter(0)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            follow_redirects=True,
        ) as client:
            await adapter._fetch_detail(client, item, "fienta.com", semaphore, limiter)

        assert "_detail_localized" in item
        descs = item["_detail_localized"]["description"]

        # Primary locale (en via html lang): must contain HTML tags, not plain JSON-LD
        en_desc = descs.get("en")
        assert en_desc is not None, "en description must be set"
        assert "<p>" in en_desc, "en description must contain HTML markup"
        assert "<strong>" in en_desc or "Bold" in en_desc

        # Non-primary locale (et): JSON-LD plain text
        et_desc = descs.get("et")
        assert et_desc == "Eesti tekst"
