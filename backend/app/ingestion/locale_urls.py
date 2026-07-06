"""Locale discovery for per-locale detail-page fetches.

Detects which locale a page represents (URL path segment, <html lang>) and
maps hreflang alternate links to absolute per-locale URLs.
"""

from typing import Any
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from app.constants import LOCALIZED_TEXT_HREFLANG_NORMALIZE

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
    from urllib.parse import urljoin

    def _str_attr(tag: Any, name: str) -> str:
        val = tag.get(name) or ""
        if isinstance(val, list):
            return val[0] if val else ""
        return val

    result: dict[str, str] = {}
    for tag in soup.find_all("link", rel="alternate"):
        lang = _str_attr(tag, "hreflang")
        if not lang:
            continue
        lang_norm = LOCALIZED_TEXT_HREFLANG_NORMALIZE.get(lang.lower(), lang.lower())
        if lang_norm not in target_locales:
            continue
        href = _str_attr(tag, "href")
        if href:
            result[lang_norm] = urljoin(base_url, href)
    if not result:
        # Fallback: language-switcher <a hreflang="…"> anchors
        for tag in soup.find_all("a", hreflang=True):
            lang = _str_attr(tag, "hreflang")
            lang_norm = LOCALIZED_TEXT_HREFLANG_NORMALIZE.get(lang.lower(), lang.lower())
            if lang_norm not in target_locales:
                continue
            href = _str_attr(tag, "href")
            if href and lang_norm not in result:
                result[lang_norm] = urljoin(base_url, href)
    return result
