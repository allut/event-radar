"""Locale discovery and per-locale detail-page fetching.

Detects which locale a page represents (URL path segment, <html lang>), maps
hreflang alternate links to absolute per-locale URLs, and owns the shared
locale-variant fetch loop (``fetch_locale_variants``) used by the HTML-listing
base adapter, the Fienta adapter, and the daily detail refetch.
"""

import logging
from collections.abc import Awaitable, Callable
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from app.constants import LOCALIZED_TEXT_HREFLANG_NORMALIZE
from app.ingestion.html_utils import attr_str

log = logging.getLogger(__name__)

# extract(soup, locale) -> (title, description, important_info); any may be None.
LocaleExtractor = Callable[
    [BeautifulSoup, str], tuple[str | None, str | None, str | None]
]


async def fetch_locale_variants(
    client: httpx.AsyncClient,
    base_soup: BeautifulSoup,
    base_url: str,
    target_locales: frozenset[str],
    extract: LocaleExtractor,
    *,
    fetch: Callable[..., Awaitable[httpx.Response]],
    wait: Callable[[], Awaitable[None]],
    source_label: str,
    base_locale: str | None = None,
    wanted_locales: set[str] | None = None,
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Fetch each locale-variant page and extract per-locale text.

    Returns ``(titles, descriptions, important_infos)`` keyed by locale. The
    page's own locale (``base_locale``, else detected from the URL path /
    <html lang>) and any variant URL equal to ``base_url`` reuse ``base_soup``
    instead of re-fetching. Every real fetch waits via ``wait()`` first (rate
    limiting) and applies the SSRF/garbage guards uniformly: variant URLs on a
    different host are skipped up front, and a response that redirected
    off-host or to the site root is rejected.

    ``fetch`` is the caller's own ``http_get`` binding, passed in (rather than
    imported here) so tests patching the caller module's ``http_get`` still
    intercept locale fetches.
    """
    base_host = urlsplit(base_url).hostname
    own_locale = (
        base_locale
        or locale_from_url_path(base_url, target_locales)
        or locale_from_html_lang(base_soup, target_locales)
    )
    locale_urls = localized_detail_urls(base_soup, base_url, target_locales)
    locale_urls = {
        locale: loc_url
        for locale, loc_url in locale_urls.items()
        if urlsplit(loc_url).hostname == base_host
        and (wanted_locales is None or locale in wanted_locales)
    }

    titles: dict[str, str] = {}
    descs: dict[str, str] = {}
    infos: dict[str, str] = {}
    for locale, loc_url in locale_urls.items():
        if locale == own_locale or loc_url == base_url:
            # This page IS the locale variant — reuse the in-memory soup.
            title, desc, info = extract(base_soup, locale)
        else:
            try:
                await wait()
                resp = await fetch(client, loc_url)
                final = urlsplit(str(resp.url))
                if final.hostname != base_host:
                    log.debug(
                        "%s: locale fetch redirected off-host locale=%s url=%s",
                        source_label, locale, loc_url,
                    )
                    continue
                if final.path in ("/", ""):
                    log.debug(
                        "%s: locale page is site root locale=%s url=%s",
                        source_label, locale, loc_url,
                    )
                    continue
                title, desc, info = extract(
                    BeautifulSoup(resp.text, "html.parser"), locale
                )
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                log.debug(
                    "%s: locale fetch failed locale=%s url=%s: %s",
                    source_label, locale, loc_url, exc,
                )
                continue
            except Exception as exc:
                log.warning(
                    "%s: locale fetch unexpected error locale=%s url=%s: %s",
                    source_label, locale, loc_url, exc,
                )
                continue
        if title:
            titles[locale] = title
        if desc:
            descs[locale] = desc
        if info:
            infos[locale] = info
    return titles, descs, infos


def locale_from_url_path(url: str, locales: frozenset[str]) -> str | None:
    """Return the locale code found as a path segment in url, or None.

    Detects locale from URL structure (e.g. ``/en/event-slug`` → ``"en"``).
    Used to identify which locale an already-loaded page represents so
    callers can reuse its soup instead of re-fetching by URL equality.
    """
    path = urlsplit(url).path
    for segment in path.strip("/").split("/"):
        if segment.lower() in locales:
            return segment.lower()
    return None


def locale_from_html_lang(soup: BeautifulSoup, locales: frozenset[str]) -> str | None:
    """Return the page's <html lang> locale if it is one of `locales`, else None."""
    html_tag = soup.find("html")
    lang = html_tag.get("lang") if html_tag else None
    if isinstance(lang, list):
        lang = lang[0] if lang else None
    if not lang:
        return None
    lang = lang.lower()
    norm = LOCALIZED_TEXT_HREFLANG_NORMALIZE.get(lang, lang.split("-")[0])
    return norm if norm in locales else None


def localized_detail_urls(
    soup: BeautifulSoup,
    base_url: str,
    target_locales: frozenset[str],
) -> dict[str, str]:
    """Return a ``{locale: absolute_url}`` map for each wanted locale found in the page.

    Reads ``<link rel="alternate" hreflang="…" href="…">`` tags and normalises
    hreflang values via LOCALIZED_TEXT_HREFLANG_NORMALIZE.  Falls back to
    ``<a>`` language-switcher anchors whose ``hreflang`` attribute is set.
    Only locales present in ``target_locales`` are returned.
    """
    result: dict[str, str] = {}
    for tag in soup.find_all("link", rel="alternate"):
        lang = attr_str(tag, "hreflang")
        if not lang:
            continue
        lang_norm = LOCALIZED_TEXT_HREFLANG_NORMALIZE.get(lang.lower(), lang.lower())
        if lang_norm not in target_locales:
            continue
        href = attr_str(tag, "href")
        if href:
            result[lang_norm] = urljoin(base_url, href)
    if not result:
        # Fallback: language-switcher <a hreflang="…"> anchors
        for tag in soup.find_all("a", hreflang=True):
            lang = attr_str(tag, "hreflang")
            lang_norm = LOCALIZED_TEXT_HREFLANG_NORMALIZE.get(lang.lower(), lang.lower())
            if lang_norm not in target_locales:
                continue
            href = attr_str(tag, "href")
            if href and lang_norm not in result:
                result[lang_norm] = urljoin(base_url, href)
    return result
