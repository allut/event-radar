"""Unit tests for sanitize_html and html_to_text helpers, plus Fienta HTML description."""

import asyncio
from unittest.mock import MagicMock

import httpx
import pytest

from bs4 import BeautifulSoup

from app.constants import (
    LOCALIZED_TEXT_FIENTA_LOCALES,
    ORGANIZER_HTML_SANITIZE_ALLOWED_ATTRS,
    ORGANIZER_HTML_SANITIZE_ALLOWED_TAGS,
)
from app.ingestion.http_client import AsyncRateLimiter
from app.ingestion.locale_urls import locale_from_html_lang
from app.ingestion.sanitize import decode_cfemail, html_to_text, sanitize_html
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

    def test_whitespace_around_link_collapsed(self) -> None:
        # KUMU-style indentation: source markup wraps the anchor on its own
        # line, leaving newlines/indentation as literal text-node whitespace.
        # Under the frontend's white-space: pre-wrap that renders as visible
        # gaps before/after the link (event 1575's Facebook link).
        html = (
            "Vaata rohkem:\n            "
            '<a href="https://facebook.com/example">Facebook</a>\n            '
            "See you there!"
        )
        result = sanitize_html(html)
        assert result is not None
        assert "Vaata rohkem: <a" in result
        assert ">Facebook</a> See you there!" in result
        assert "  " not in result
        assert "\n" not in result

    def test_whitespace_collapse_preserves_href(self) -> None:
        # Whitespace collapsing must only touch text nodes, never attributes.
        html = '<a href="https://example.com/path?a=1&amp;b=2">  spaced   text  </a>'
        result = sanitize_html(html)
        assert result is not None
        assert 'href="https://example.com/path?a=1&amp;b=2"' in result
        assert "spaced text" in result

    def test_whitespace_collapse_preserves_nbsp(self) -> None:
        # &nbsp; decodes to U+00A0, which Python's \s matches — collapsing it
        # would silently turn intentional non-breaking spacing into an
        # ordinary breakable space.
        result = sanitize_html("a&nbsp;&nbsp;b")
        assert result is not None
        assert result == "a\xa0\xa0b"

    def test_block_boundary_leading_space_stripped(self) -> None:
        # ECH-style performer list: <h4> heading followed by tab-indented name,
        # then <br>-separated lines (event 1580's "Esitajad:" block). A leading
        # space right after </h4> or a <br> is a formatting artifact, not a
        # real word-boundary separator, so it must not survive.
        html = (
            "<h4>Esitajad:</h4>\n\t\t\t\t\t\t\t\tMomir Novakovic (akordion)<br>\n"
            "Villu Vihermäe (viola da gamba)<br>\n"
            "Saale Fischer (klavessiin)\t\t\t\t\t\t\t<br>\n"
            "<p>Kavas:<br>\nMarais, Rameau, Couperin, Royer, Forqueray</p>"
        )
        result = sanitize_html(html)
        assert result is not None
        assert "</h4>Momir Novakovic" in result
        assert "<br>Villu Vihermäe" in result
        assert "<br><p>Kavas:<br>Marais" in result
        assert " <br>" not in result
        assert "<br> " not in result

    def test_inline_tag_spacing_preserved(self) -> None:
        # Word-boundary spaces around inline tags (a, strong, em, ...) are
        # real content, not formatting artifacts — must survive even though
        # they touch a tag boundary, unlike block-boundary tags (br/p/h4/...).
        html = '<p>visit our <a href="https://example.com">website</a> today</p>'
        result = sanitize_html(html)
        assert result is not None
        assert "visit our <a" in result
        assert "website</a> today" in result

    def test_word_separator_space_inside_inline_tag_preserved(self) -> None:
        # A word-boundary space that is the first/last character *inside* an
        # inline tag (not just adjacent to it) must survive — the text node
        # has no previous/next sibling, but its parent is inline, so it is
        # not a block boundary. Regression: an earlier version stripped this
        # and merged "before"+"important" into "beforeimportant".
        result = sanitize_html("<p>before<b> important</b> after</p>")
        assert result is not None
        assert "before<b> important</b> after" in result

        result2 = sanitize_html("<p>before <b>important </b>after</p>")
        assert result2 is not None
        assert "before <b>important </b>after" in result2

    def test_block_edge_inline_wrapper_space_stripped(self) -> None:
        # An inline tag wrapping the very first/last content of a block, with
        # its own leading/trailing space, is still a block-edge artifact even
        # though the text node's *immediate* parent is inline — the search
        # must walk up through the inline ancestor chain to find this.
        # Regression: an earlier version only checked the immediate parent
        # and left these stray spaces in place.
        result = sanitize_html("<p><b> Hello world</b> after</p>")
        assert result is not None
        assert result == "<p><b>Hello world</b> after</p>"

        result2 = sanitize_html("<p>before <b>trailing space here </b></p>")
        assert result2 is not None
        assert result2 == "<p>before <b>trailing space here</b></p>"

    def test_trailing_empty_paragraph_removed(self) -> None:
        result = sanitize_html("<p>Real content</p><p></p>")
        assert result == "<p>Real content</p>"

    def test_trailing_empty_paragraph_with_br_removed(self) -> None:
        result = sanitize_html("<p>Real content</p><p><br></p>")
        assert result == "<p>Real content</p>"

    def test_trailing_empty_paragraph_with_span_removed(self) -> None:
        result = sanitize_html("<p>Real content</p><p><span></span></p>")
        assert result == "<p>Real content</p>"

    def test_trailing_nbsp_only_paragraph_removed(self) -> None:
        result = sanitize_html("<p>Real content</p><p>&nbsp;</p>")
        assert result == "<p>Real content</p>"

    def test_leading_and_multiple_trailing_empty_paragraphs_removed(self) -> None:
        # Regression case matching event id 5: two stacked empty trailing <p>s.
        result = sanitize_html("<p></p><p>Real content</p><p></p><p><br></p>")
        assert result == "<p>Real content</p>"

    def test_empty_list_item_and_now_empty_list_both_removed(self) -> None:
        # Emptying the only <li> must cascade to remove the now-empty <ul>.
        result = sanitize_html("<p>Before</p><ul><li></li></ul>")
        assert result == "<p>Before</p>"

    def test_non_empty_list_item_survives_alongside_empty_sibling(self) -> None:
        result = sanitize_html("<ul><li>Keep me</li><li></li></ul>")
        assert result is not None
        assert "<li>Keep me</li>" in result
        assert result.count("<li>") == 1

    def test_bare_trailing_br_exposed_by_empty_block_removal_is_stripped(self) -> None:
        # A bare <br> (from a stray div-to-br conversion) immediately before a
        # trailing empty <p> is not at the string edge until that <p> is
        # removed — must be re-caught by the second edge-br pass.
        result = sanitize_html("<p>Real content</p><br><p></p>")
        assert result == "<p>Real content</p>"

    def test_edge_nbsp_preserved(self) -> None:
        # A bare .strip() also treats U+00A0 as whitespace and would delete a
        # leading/trailing &nbsp; — must survive at the string boundary too.
        result = sanitize_html("&nbsp;Foo")
        assert result == "\xa0Foo"
        result = sanitize_html("Foo&nbsp;")
        assert result == "Foo\xa0"

    def test_decode_cfemail_known_vector(self) -> None:
        assert (
            decode_cfemail("d5bfb4bbb4fbb9b0a3bca1bcbbb495b2b8b4bcb9fbb6bab8")
            == "jana.levitina@gmail.com"
        )

    def test_decode_cfemail_malformed_returns_none(self) -> None:
        assert decode_cfemail("") is None
        assert decode_cfemail("z") is None
        assert decode_cfemail("abc") is None  # odd length
        assert decode_cfemail("not-hex-at-all") is None

    def test_cfemail_anchor_form_decoded(self) -> None:
        # Cloudflare's `__cf_email__`-classed anchor, hex in the href fragment
        # — the form actually present in Fienta's et-locale pages.
        html = (
            '<p>Contact: <a href="/cdn-cgi/l/email-protection'
            '#d5bfb4bbb4fbb9b0a3bca1bcbbb495b2b8b4bcb9fbb6bab8" '
            'class="__cf_email__">[email&#160;protected]</a></p>'
        )
        result = sanitize_html(html)
        assert result is not None
        assert "jana.levitina@gmail.com" in result
        assert "[email" not in result
        assert "cdn-cgi" not in result

    def test_cfemail_data_span_form_decoded(self) -> None:
        html = (
            '<p>Contact: <span class="__cf_email__" '
            'data-cfemail="d5bfb4bbb4fbb9b0a3bca1bcbbb495b2b8b4bcb9fbb6bab8">'
            "[email&#160;protected]</span></p>"
        )
        result = sanitize_html(html)
        assert result is not None
        assert "jana.levitina@gmail.com" in result
        assert "[email" not in result

    def test_cfemail_absent_leaves_html_unchanged(self) -> None:
        html = "<p>No obfuscated email here.</p>"
        result = sanitize_html(html)
        assert result == html

    def test_cfemail_malformed_hex_passes_through(self) -> None:
        # A malformed/garbage hex payload must not raise — the placeholder
        # anchor is left as-is (nh3 then strips the disallowed class/href
        # down to a bare anchor).
        html = (
            '<a href="/cdn-cgi/l/email-protection#zz" class="__cf_email__">'
            "[email protected]</a>"
        )
        result = sanitize_html(html)
        assert result is not None
        assert "[email protected]" in result


class TestSanitizeHtmlOrganizerBoundary:
    """The organizer-submission boundary passes a narrower allowlist via the
    tags/attrs params (#267) — default (ingestion) calls must be unaffected."""

    def _organizer_clean(self, html: str) -> str | None:
        return sanitize_html(
            html,
            tags=ORGANIZER_HTML_SANITIZE_ALLOWED_TAGS,
            attrs=ORGANIZER_HTML_SANITIZE_ALLOWED_ATTRS,
        )

    def test_span_stripped_under_organizer_allowlist(self) -> None:
        html = "<p>Hello <span>World</span></p>"
        result = self._organizer_clean(html)
        assert result is not None
        assert "<span>" not in result
        assert "World" in result

    def test_span_preserved_under_default_ingestion_allowlist(self) -> None:
        # Default (no tags/attrs) call site — proves the override is opt-in
        # and every existing (non-organizer) call site is unaffected.
        html = "<p>Hello <span>World</span></p>"
        result = sanitize_html(html)
        assert result is not None
        assert "<span>World</span>" in result

    def test_link_title_attr_stripped_under_organizer_allowlist(self) -> None:
        # Default ingestion attrs allow a["title"]; the organizer boundary
        # only allows a["href"].
        html = '<a href="https://example.com" title="Test">Link</a>'
        result = self._organizer_clean(html)
        assert result is not None
        assert 'href="https://example.com"' in result
        assert "title=" not in result

    def test_link_title_attr_preserved_under_default_allowlist(self) -> None:
        html = '<a href="https://example.com" title="Test">Link</a>'
        result = sanitize_html(html)
        assert result is not None
        assert 'title="Test"' in result

    def test_disallowed_tag_stripped_alongside_allowed_ones(self) -> None:
        html = "<p>Keep <strong>this</strong></p><span>drop this wrapper</span>"
        result = self._organizer_clean(html)
        assert result is not None
        assert "<strong>this</strong>" in result
        assert "<span>" not in result
        assert "drop this wrapper" in result

    def test_underline_and_blockquote_preserved(self) -> None:
        html = "<blockquote><u>Underlined quote</u></blockquote>"
        result = self._organizer_clean(html)
        assert result is not None
        assert "<blockquote>" in result
        assert "<u>Underlined quote</u>" in result

    def test_rel_noopener_survives_organizer_allowlist(self) -> None:
        # Regression: an attribute_filter naively enforcing the attrs map
        # would strip nh3's own injected rel="noopener noreferrer" since
        # "rel" is absent from ORGANIZER_HTML_SANITIZE_ALLOWED_ATTRS.
        html = '<a href="https://example.com" target="_blank">Link</a>'
        result = self._organizer_clean(html)
        assert result is not None
        assert 'rel="noopener noreferrer"' in result
        assert "target=" not in result

    def test_i_tag_stripped_under_organizer_allowlist(self) -> None:
        # <i> is in the default ingestion allowlist but not the organizer one
        # (organizer offers <em> for italics via Tiptap, not raw <i>).
        html = "<i>slanted</i>"
        result = self._organizer_clean(html)
        assert result is not None
        assert "<i>" not in result
        assert "slanted" in result


class TestOrganizerHtmlAllowlistSync:
    """Guards ORGANIZER_HTML_SANITIZE_ALLOWED_TAGS/ATTRS against silent drift —
    this set must track the Tiptap toolbar's exact extension list: bold,
    italic, underline, bulletList, orderedList, link, heading (levels 3-4
    only), blockquote. No color extension, so no style/class attrs anywhere.
    A future toolbar change must update both the constant and this test."""

    def test_allowed_tags_match_tiptap_extension_list(self) -> None:
        assert ORGANIZER_HTML_SANITIZE_ALLOWED_TAGS == frozenset(
            {"p", "br", "strong", "em", "u", "ul", "ol", "li", "a", "h3", "h4", "blockquote"}
        )

    def test_allowed_attrs_match_tiptap_extension_list(self) -> None:
        assert ORGANIZER_HTML_SANITIZE_ALLOWED_ATTRS == {"a": {"href"}}


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
