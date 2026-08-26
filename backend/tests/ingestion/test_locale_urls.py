"""Tests for the shared locale-variant fetch loop (fetch_locale_variants)."""
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from bs4 import BeautifulSoup

from app.ingestion.locale_urls import fetch_locale_variants
from tests.ingestion.conftest import soup as _soup

_LOCALES = frozenset({"en", "et", "ru"})


def _base_soup(host: str = "example.test") -> BeautifulSoup:
    return _soup(
        f"""<html lang="en"><head>
        <link rel="alternate" hreflang="et" href="https://{host}/et/event">
        <link rel="alternate" hreflang="ru" href="https://{host}/ru/event">
        </head><body><h1>Base</h1></body></html>"""
    )


def _response(url: str, html: str) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.url = httpx.URL(url)
    resp.text = html
    return resp


def _extract(soup: BeautifulSoup, _locale: str):
    h1 = soup.find("h1")
    title = h1.get_text(strip=True) if h1 else None
    return title, None, None


async def _no_wait() -> None:
    return None


class TestFetchLocaleVariants:
    @pytest.mark.asyncio
    async def test_fetches_each_wanted_locale(self):
        fetch = AsyncMock(
            side_effect=[
                _response("https://example.test/et/event", "<h1>ET title</h1>"),
                _response("https://example.test/ru/event", "<h1>RU title</h1>"),
            ]
        )
        titles, _descs, _infos = await fetch_locale_variants(
            MagicMock(),
            _base_soup(),
            "https://example.test/en/event",
            _LOCALES,
            _extract,
            fetch=fetch,
            wait=_no_wait,
            source_label="test",
        )
        assert titles == {"et": "ET title", "ru": "RU title"}
        assert fetch.await_count == 2

    @pytest.mark.asyncio
    async def test_off_host_redirect_rejected(self):
        """A locale URL that redirects to another host must be discarded —
        the guard the Fienta copy of this loop was missing."""
        fetch = AsyncMock(
            side_effect=[
                _response("https://evil.test/et/event", "<h1>evil</h1>"),
                _response("https://example.test/ru/event", "<h1>RU title</h1>"),
            ]
        )
        titles, _descs, _infos = await fetch_locale_variants(
            MagicMock(),
            _base_soup(),
            "https://example.test/en/event",
            _LOCALES,
            _extract,
            fetch=fetch,
            wait=_no_wait,
            source_label="test",
        )
        assert titles == {"ru": "RU title"}

    @pytest.mark.asyncio
    async def test_site_root_redirect_rejected(self):
        fetch = AsyncMock(
            return_value=_response("https://example.test/", "<h1>homepage</h1>")
        )
        titles, descs, _infos = await fetch_locale_variants(
            MagicMock(),
            _base_soup(),
            "https://example.test/en/event",
            _LOCALES,
            _extract,
            fetch=fetch,
            wait=_no_wait,
            source_label="test",
        )
        assert titles == {} and descs == {}

    @pytest.mark.asyncio
    async def test_cross_host_variant_url_skipped_without_fetch(self):
        """An hreflang link pointing at a different host is never fetched."""
        soup = _soup(
            """<html lang="en"><head>
            <link rel="alternate" hreflang="et" href="https://other.test/et/event">
            </head></html>"""
        )
        fetch = AsyncMock()
        titles, _descs, _infos = await fetch_locale_variants(
            MagicMock(),
            soup,
            "https://example.test/en/event",
            _LOCALES,
            _extract,
            fetch=fetch,
            wait=_no_wait,
            source_label="test",
        )
        assert titles == {}
        fetch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_own_locale_reuses_base_soup(self):
        soup = _soup(
            """<html lang="en"><head>
            <link rel="alternate" hreflang="en" href="https://example.test/en/event">
            </head><body><h1>Base EN</h1></body></html>"""
        )
        fetch = AsyncMock()
        titles, _descs, _infos = await fetch_locale_variants(
            MagicMock(),
            soup,
            "https://example.test/en/event",
            _LOCALES,
            _extract,
            fetch=fetch,
            wait=_no_wait,
            source_label="test",
        )
        assert titles == {"en": "Base EN"}
        fetch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_http_error_skips_locale_and_continues(self):
        fetch = AsyncMock(
            side_effect=[
                httpx.RequestError("boom"),
                _response("https://example.test/ru/event", "<h1>RU title</h1>"),
            ]
        )
        titles, _descs, _infos = await fetch_locale_variants(
            MagicMock(),
            _base_soup(),
            "https://example.test/en/event",
            _LOCALES,
            _extract,
            fetch=fetch,
            wait=_no_wait,
            source_label="test",
        )
        assert titles == {"ru": "RU title"}

    @pytest.mark.asyncio
    async def test_unexpected_extract_error_reraises_after_loop(self):
        """An unexpected (non-httpx) exception from the extract callback must
        still surface (never swallow exceptions in fetch_raw() — see
        html_base.py/fienta.py's _fetch_detail for the same invariant), but
        only after every locale has been attempted — one bad locale must not
        abort the others."""

        def _flaky_extract(soup: BeautifulSoup, locale: str):
            if locale == "ru":
                raise ValueError("boom")
            return _extract(soup, locale)

        fetch = AsyncMock(
            side_effect=[
                _response("https://example.test/et/event", "<h1>ET title</h1>"),
                _response("https://example.test/ru/event", "<h1>RU title</h1>"),
            ]
        )
        with pytest.raises(ValueError, match="boom"):
            await fetch_locale_variants(
                MagicMock(),
                _base_soup(),
                "https://example.test/en/event",
                _LOCALES,
                _flaky_extract,
                fetch=fetch,
                wait=_no_wait,
                source_label="test",
            )
        # Both locales were attempted (et succeeded, ru raised) — the ru
        # failure didn't short-circuit et's fetch.
        assert fetch.await_count == 2

    @pytest.mark.asyncio
    async def test_wanted_locales_filters_fetches(self):
        fetch = AsyncMock(
            return_value=_response("https://example.test/et/event", "<h1>ET</h1>")
        )
        titles, _descs, _infos = await fetch_locale_variants(
            MagicMock(),
            _base_soup(),
            "https://example.test/en/event",
            _LOCALES,
            _extract,
            fetch=fetch,
            wait=_no_wait,
            source_label="test",
            wanted_locales={"et"},
        )
        assert titles == {"et": "ET"}
        assert fetch.await_count == 1
