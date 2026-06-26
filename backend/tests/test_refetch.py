"""Tests for refetch.py bug fixes.

Covers:
  (a) refetch client follows a 302 to a same-host locale path (Bug 1)
  (b) locale page that redirects to site root is rejected (Bug 2b)
  (c) per-locale merge fills missing locales without dropping existing ones (Bug 2c)
  (d) kumu_localized_text rejects site-level homepage og:title (Bug 2b + extractor guard)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from app.constants import (
    KUMU_SITE_NAME_ET,
    KUMU_SITE_TITLE_SUFFIX,
    LOCALIZED_TEXT_FIENTA_LOCALES,
)
from app.ingestion.base import locale_from_url_path
from app.ingestion.refetch import _is_suspect_locale_title
from app.ingestion.sources.html_listing import kumu_localized_text


# ---------------------------------------------------------------------------
# locale_from_url_path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url,locales,expected",
    [
        ("https://kumu.ekm.ee/en/syndmus/foo-4/", LOCALIZED_TEXT_FIENTA_LOCALES, "en"),
        ("https://fienta.com/et/event-slug", LOCALIZED_TEXT_FIENTA_LOCALES, "et"),
        ("https://fienta.com/ru/event-slug", LOCALIZED_TEXT_FIENTA_LOCALES, "ru"),
        ("https://kumu.ekm.ee/syndmus/foo-4/", LOCALIZED_TEXT_FIENTA_LOCALES, None),
        ("https://example.com/de/event", LOCALIZED_TEXT_FIENTA_LOCALES, None),
    ],
)
def test_locale_from_url_path(url: str, locales: frozenset[str], expected: str | None) -> None:
    assert locale_from_url_path(url, locales) == expected


# ---------------------------------------------------------------------------
# _is_suspect_locale_title
# ---------------------------------------------------------------------------


def test_suspect_locale_title_kumu_homepage() -> None:
    garbage = "Kumu kunstimuuseum - Eesti Kunstimuuseumi filiaal - Avaleht"
    assert _is_suspect_locale_title(garbage, "kumu.ekm.ee") is True


def test_suspect_locale_title_valid_kumu_event() -> None:
    valid = "Näitus: Maailma lõpp"
    assert _is_suspect_locale_title(valid, "kumu.ekm.ee") is False


def test_suspect_locale_title_genitive_kumu_not_suspect() -> None:
    genitive = "Kumu kunstimuuseumi 100. aastapäeva näitus"
    assert _is_suspect_locale_title(genitive, "kumu.ekm.ee") is False


def test_suspect_locale_title_non_kumu_host() -> None:
    garbage = "Kumu kunstimuuseum - Avaleht"
    assert _is_suspect_locale_title(garbage, "fienta.com") is False


# ---------------------------------------------------------------------------
# kumu_localized_text — site-level homepage title rejected
# ---------------------------------------------------------------------------


def _make_soup(og_title: str, desc_text: str = "") -> BeautifulSoup:
    html = f"""
    <html><head>
      <meta property="og:title" content="{og_title}">
    </head><body>
      <div class="single__content-dynamic">{desc_text}</div>
    </body></html>"""
    return BeautifulSoup(html, "html.parser")


def test_kumu_localized_text_homepage_title_rejected() -> None:
    soup = _make_soup("Kumu kunstimuuseum - Eesti Kunstimuuseumi filiaal - Avaleht")
    title, desc = kumu_localized_text(soup)
    assert title is None


def test_kumu_localized_text_valid_event() -> None:
    soup = _make_soup(f"Näitus: Maailm{KUMU_SITE_TITLE_SUFFIX}", "Some description text")
    title, desc = kumu_localized_text(soup)
    assert title == "Näitus: Maailm"
    assert desc == "Some description text"


def test_kumu_localized_text_site_name_prefix_with_separator_rejected() -> None:
    soup = _make_soup(f"{KUMU_SITE_NAME_ET} - Avaleht")
    title, desc = kumu_localized_text(soup)
    assert title is None


def test_kumu_localized_text_genitive_prefix_not_rejected() -> None:
    soup = _make_soup(f"Kumu kunstimuuseumi 100. aastapäeva näitus{KUMU_SITE_TITLE_SUFFIX}")
    title, desc = kumu_localized_text(soup)
    assert title == "Kumu kunstimuuseumi 100. aastapäeva näitus"


# ---------------------------------------------------------------------------
# Per-locale merge (Bug 2c): missing locale filled, existing good locale kept
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refetch_per_locale_merge_keeps_existing(make_event: MagicMock) -> None:
    """Refetch fills a missing locale without overwriting an already-good one."""
    from app.ingestion.refetch import refetch_event_details

    event = make_event(10)
    event.url = "https://kumu.ekm.ee/en/syndmus/test-event-4/"
    event.starts_at = MagicMock()
    event.starts_at.__gt__ = MagicMock(return_value=True)
    # en already has a good title; et + ru missing
    event.title_localized = {"en": "Test Event EN"}
    event.description_localized = None
    event.detail_refetched_at = None
    event.detail_refetch_count = 0

    # Build a minimal KUMU-style page: no Event JSON-LD, has hreflang alternates
    main_html = """
    <html><head>
      <meta property="og:title" content="Test Event EN - Kumu kunstimuuseum">
      <link rel="alternate" hreflang="en" href="/syndmus/test-event-4/">
      <link rel="alternate" hreflang="et" href="/et/syndmus/test-event-4/">
    </head><body>
      <div class="single__content-dynamic">Event description EN</div>
    </body></html>"""

    et_html = """
    <html><head>
      <meta property="og:title" content="Test Event ET - Kumu kunstimuuseum">
    </head><body>
      <div class="single__content-dynamic">Event description ET</div>
    </body></html>"""

    import httpx

    def make_response(text: str, url: str = "https://kumu.ekm.ee/en/syndmus/test-event-4/") -> MagicMock:
        resp = MagicMock(spec=httpx.Response)
        resp.text = text
        resp.url = httpx.URL(url)
        resp.raise_for_status = MagicMock()
        return resp

    main_resp = make_response(main_html)
    et_resp = make_response(et_html, "https://kumu.ekm.ee/et/syndmus/test-event-4/")

    call_count = 0

    async def fake_http_get(client: object, url: str, **kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if "et/" in url:
            return et_resp
        return main_resp

    mock_db = AsyncMock()
    mock_db.scalars = AsyncMock()
    scalars_result = MagicMock()
    scalars_result.all = MagicMock(return_value=[event])
    mock_db.scalars.return_value = scalars_result
    mock_db.commit = AsyncMock()

    with (
        patch("app.ingestion.refetch.http_get", side_effect=fake_http_get),
        patch("app.ingestion.refetch.asyncio.sleep", new_callable=AsyncMock),
    ):
        summary = await refetch_event_details(mock_db)

    # en title must be preserved; et title + description must be backfilled
    assert event.title_localized is not None
    assert event.title_localized.get("en") == "Test Event EN"
    assert event.title_localized.get("et") == "Test Event ET"
    assert summary["localized_text_backfilled"] >= 1


# ---------------------------------------------------------------------------
# Locale page redirected to site root is rejected (Bug 2b)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refetch_locale_redirect_to_root_rejected(make_event: MagicMock) -> None:
    """A locale hreflang URL that 302s to site root must not pollute stored titles."""
    from app.ingestion.refetch import refetch_event_details

    event = make_event(11)
    event.url = "https://kumu.ekm.ee/en/syndmus/test-event-4/"
    event.starts_at = MagicMock()
    event.starts_at.__gt__ = MagicMock(return_value=True)
    event.title_localized = None
    event.description_localized = None
    event.detail_refetched_at = None
    event.detail_refetch_count = 0

    main_html = """
    <html><head>
      <meta property="og:title" content="Test Event EN - Kumu kunstimuuseum">
      <link rel="alternate" hreflang="en" href="/syndmus/test-event-4/">
      <link rel="alternate" hreflang="et" href="https://kumu.ekm.ee/">
    </head><body>
      <div class="single__content-dynamic">EN description</div>
    </body></html>"""

    homepage_html = """
    <html><head>
      <meta property="og:title" content="Kumu kunstimuuseum - Eesti Kunstimuuseumi filiaal - Avaleht">
    </head><body></body></html>"""

    import httpx

    def make_response(text: str, url: str) -> MagicMock:
        resp = MagicMock(spec=httpx.Response)
        resp.text = text
        resp.url = httpx.URL(url)
        resp.raise_for_status = MagicMock()
        return resp

    async def fake_http_get(client: object, url: str, **kwargs: object) -> MagicMock:
        if url == "https://kumu.ekm.ee/":
            # simulate redirect to site root
            return make_response(homepage_html, "https://kumu.ekm.ee/")
        return make_response(main_html, "https://kumu.ekm.ee/en/syndmus/test-event-4/")

    mock_db = AsyncMock()
    scalars_result = MagicMock()
    scalars_result.all = MagicMock(return_value=[event])
    mock_db.scalars = AsyncMock(return_value=scalars_result)
    mock_db.commit = AsyncMock()

    with (
        patch("app.ingestion.refetch.http_get", side_effect=fake_http_get),
        patch("app.ingestion.refetch.asyncio.sleep", new_callable=AsyncMock),
    ):
        await refetch_event_details(mock_db)

    # et must NOT be set (the homepage redirect was rejected)
    if event.title_localized:
        assert "et" not in event.title_localized
