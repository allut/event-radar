"""Tests for email/styles.py — dark/light/system style-selection seam."""

from app.email.styles import (
    DARK_STYLES,
    LIGHT_STYLES,
    SYSTEM_STYLES,
    get_email_styles,
)

_DARK_MEDIA_QUERY = "@media (prefers-color-scheme:dark)"


class TestGetEmailStyles:
    def test_dark_returns_dark_styles_unchanged(self):
        assert get_email_styles("dark") is DARK_STYLES

    def test_light_returns_light_styles(self):
        assert get_email_styles("light") is LIGHT_STYLES

    def test_none_returns_system_styles(self):
        assert get_email_styles(None) is SYSTEM_STYLES

    def test_system_returns_system_styles(self):
        assert get_email_styles("system") is SYSTEM_STYLES

    def test_dark_and_light_page_backgrounds_differ(self):
        assert DARK_STYLES.s_page != LIGHT_STYLES.s_page
        assert "#13161e" in DARK_STYLES.s_page
        assert "#fdfcfa" in LIGHT_STYLES.s_page

    def test_light_css_uses_deepened_accent_light_hover(self):
        assert "#a3701e" in LIGHT_STYLES.css
        assert "#e8a838" not in LIGHT_STYLES.css

    def test_dark_css_matches_todays_hover_color(self):
        assert "#e8a838" in DARK_STYLES.css


class TestColorScheme:
    def test_dark_declares_dark(self):
        assert DARK_STYLES.color_scheme == "dark"

    def test_light_declares_light(self):
        assert LIGHT_STYLES.color_scheme == "light"

    def test_system_declares_light_dark(self):
        assert SYSTEM_STYLES.color_scheme == "light dark"


class TestSystemDarkOverride:
    def test_system_css_has_dark_override_and_dark_bg(self):
        assert _DARK_MEDIA_QUERY in SYSTEM_STYLES.css
        assert "#13161e" in SYSTEM_STYLES.css

    def test_system_css_is_light_base(self):
        assert "#a3701e" in SYSTEM_STYLES.css

    def test_dark_css_has_no_override_block(self):
        assert _DARK_MEDIA_QUERY not in DARK_STYLES.css

    def test_light_css_has_no_override_block(self):
        assert _DARK_MEDIA_QUERY not in LIGHT_STYLES.css
