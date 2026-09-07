"""Tests for email/styles.py — dark/light style-selection seam."""

from app.email.styles import DARK_STYLES, LIGHT_STYLES, get_email_styles


class TestGetEmailStyles:
    def test_dark_returns_dark_styles_unchanged(self):
        assert get_email_styles("dark") is DARK_STYLES

    def test_light_returns_light_styles(self):
        assert get_email_styles("light") is LIGHT_STYLES

    def test_none_returns_light_styles(self):
        assert get_email_styles(None) is LIGHT_STYLES

    def test_system_returns_light_styles(self):
        assert get_email_styles("system") is LIGHT_STYLES

    def test_dark_and_light_page_backgrounds_differ(self):
        assert DARK_STYLES.s_page != LIGHT_STYLES.s_page
        assert "#13161e" in DARK_STYLES.s_page
        assert "#fdfcfa" in LIGHT_STYLES.s_page

    def test_light_css_uses_deepened_accent_light_hover(self):
        assert "#a3701e" in LIGHT_STYLES.css
        assert "#e8a838" not in LIGHT_STYLES.css

    def test_dark_css_matches_todays_hover_color(self):
        assert "#e8a838" in DARK_STYLES.css
