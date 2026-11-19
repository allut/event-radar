"""Tests for app.email.links — the backend counterpart of the frontend's
localizedPath (frontend/src/lib/urlLocale.ts): ET bare, en/ru prefixed (#499)."""

import pytest

from app.email import links


@pytest.mark.parametrize(
    ("path", "locale", "expected"),
    [
        ("/auth/verify", "et", "/auth/verify"),
        ("/auth/verify", "en", "/en/auth/verify"),
        ("/auth/verify", "ru", "/ru/auth/verify"),
        ("/", "et", "/"),
        ("/", "en", "/en"),
        ("/", "ru", "/ru"),
        # Unknown locale resolves like t() (to DEFAULT_USER_LOCALE), so the
        # link matches the language the email body rendered in.
        ("/events/1", "de", "/en/events/1"),
    ],
)
def test_localized_path(path, locale, expected):
    assert links.localized_path(path, locale) == expected


@pytest.mark.parametrize(
    ("locale", "expected"),
    [
        ("et", "https://radar.example/unsubscribe"),
        ("en", "https://radar.example/en/unsubscribe"),
        ("ru", "https://radar.example/ru/unsubscribe"),
    ],
)
def test_frontend_url_prefixes_frontend_base(monkeypatch, locale, expected):
    monkeypatch.setattr(links.settings, "FRONTEND_URL", "https://radar.example")
    assert links.frontend_url("/unsubscribe", locale) == expected


def test_frontend_url_explicit_base_overrides_settings(monkeypatch):
    monkeypatch.setattr(links.settings, "FRONTEND_URL", "https://radar.example")
    assert (
        links.frontend_url("/events/1", "ru", "https://other.example")
        == "https://other.example/ru/events/1"
    )
