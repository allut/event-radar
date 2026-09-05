"""Tests for email/magic_link.py — HTML/text builders."""

from app.email.magic_link import build_magic_link_html, build_magic_link_text
from app.i18n import t


class TestBuildMagicLinkHtml:
    def test_starts_with_doctype(self):
        html = build_magic_link_html("https://example.com/auth/verify?token=abc", 15, "en")
        assert html.startswith("<!DOCTYPE html>")

    def test_verify_url_escaped_in_cta_href(self):
        html = build_magic_link_html(
            "https://example.com/auth/verify?token=a&b", 15, "en"
        )
        assert 'href="https://example.com/auth/verify?token=a&amp;b"' in html

    def test_ttl_minutes_interpolated(self):
        html = build_magic_link_html("https://example.com/verify?token=x", 15, "en")
        assert "{ttl_minutes}" not in html
        assert "15 minutes" in html

    def test_en_strings_present(self):
        html = build_magic_link_html("https://example.com/verify?token=x", 15, "en")
        assert t("email.magic_link.heading", "en") in html
        assert "Click below to sign in" in html
        assert t("email.magic_link.cta", "en") in html
        assert t("email.magic_link.ignore_note", "en") in html

    def test_et_strings_present(self):
        html = build_magic_link_html("https://example.com/verify?token=x", 15, "et")
        assert t("email.magic_link.heading", "et") in html
        assert t("email.magic_link.cta", "et") in html
        assert t("email.magic_link.ignore_note", "et") in html

    def test_ru_strings_present(self):
        html = build_magic_link_html("https://example.com/verify?token=x", 15, "ru")
        assert t("email.magic_link.heading", "ru") in html
        assert t("email.magic_link.cta", "ru") in html
        assert t("email.magic_link.ignore_note", "ru") in html


class TestBuildMagicLinkHtmlTheme:
    def test_dark_theme_preference_keeps_todays_colors(self):
        html = build_magic_link_html(
            "https://example.com/verify?token=x", 15, "en", "dark"
        )
        assert "#13161e" in html

    def test_light_theme_preference_uses_light_colors(self):
        html = build_magic_link_html(
            "https://example.com/verify?token=x", 15, "en", "light"
        )
        assert "#fdfcfa" in html

    def test_unset_theme_preference_defaults_to_light(self):
        html = build_magic_link_html("https://example.com/verify?token=x", 15, "en")
        assert "#fdfcfa" in html


class TestBuildMagicLinkText:
    def test_contains_raw_url(self):
        text = build_magic_link_text("https://example.com/verify?token=x&y", 15, "en")
        assert "https://example.com/verify?token=x&y" in text

    def test_no_html_tags(self):
        text = build_magic_link_text("https://example.com/verify?token=x", 15, "en")
        assert "<" not in text

    def test_ttl_minutes_interpolated(self):
        text = build_magic_link_text("https://example.com/verify?token=x", 15, "en")
        assert "{ttl_minutes}" not in text
        assert "15 minutes" in text
