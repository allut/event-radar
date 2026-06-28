"""Unit tests for sanitize_html and html_to_text helpers, plus Fienta HTML description."""

import asyncio
from unittest.mock import MagicMock

import httpx
import pytest

from app.ingestion.base import AsyncRateLimiter, html_to_text, sanitize_html
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
