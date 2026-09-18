"""Tests for email/styles.py — the one email bundle (ADR 0003)."""

from app.email.styles import EMAIL_STYLES, get_email_styles

_DARK_MEDIA_QUERY = "@media (prefers-color-scheme:dark)"


class TestGetEmailStyles:
    def test_returns_the_one_bundle(self):
        assert get_email_styles() is EMAIL_STYLES

    def test_light_base_background(self):
        assert "#fdfcfa" in EMAIL_STYLES.s_page

    def test_css_is_light_base_hover_color(self):
        assert "#a3701e" in EMAIL_STYLES.css


class TestColorScheme:
    def test_declares_light_dark(self):
        assert EMAIL_STYLES.color_scheme == "light dark"


class TestDarkOverride:
    def test_css_has_dark_override_and_dark_bg(self):
        assert _DARK_MEDIA_QUERY in EMAIL_STYLES.css
        assert "#13161e" in EMAIL_STYLES.css
