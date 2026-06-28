"""Unit tests for sanitize_html and html_to_text helpers."""

import pytest

from app.ingestion.base import html_to_text, sanitize_html


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
