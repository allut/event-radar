"""Generic BeautifulSoup helpers shared across ingestion modules.

Kept separate from html_base.py (which owns adapter-specific scraping logic)
because locale_urls.py is imported by html_base.py — a shared low-level
module avoids a circular import between the two.
"""

from bs4 import BeautifulSoup, Tag

from app.constants import LOCALIZED_TEXT_MAX_DESC_CHARS, LOCALIZED_TEXT_MAX_TITLE_CHARS
from app.ingestion.sanitize import html_to_text, sanitize_html


def attr_str(tag: Tag, name: str) -> str:
    """Return a single-string attribute value.

    bs4 types attribute values as ``str | list[str]`` (multi-valued attributes
    like ``class`` parse as lists). The attributes we read here (href, src,
    data-srcset, style, hreflang) are single-valued, so collapse any list to
    its first element.
    """
    value = tag.get(name)
    if isinstance(value, list):
        return value[0] if value else ""
    return value or ""


def og_title(soup: BeautifulSoup) -> str | None:
    """Return og:title content, or None if absent."""
    tag = soup.find("meta", property="og:title")
    if tag and isinstance(tag, Tag):
        content = tag.get("content")
        if isinstance(content, str):
            return content.strip() or None
    return None


def localized_description(soup: BeautifulSoup, selector: str) -> str | None:
    """Sanitized detail-page description, truncated to LOCALIZED_TEXT_MAX_DESC_CHARS."""
    desc_tag = soup.select_one(selector)
    if not desc_tag:
        return None
    html = sanitize_html(desc_tag.decode_contents())
    if not html:
        return None
    if len(html) <= LOCALIZED_TEXT_MAX_DESC_CHARS:
        return html
    return (html_to_text(html) or "")[:LOCALIZED_TEXT_MAX_DESC_CHARS] or None


def og_title_localized_text(
    soup: BeautifulSoup, *, site_name: str, title_suffix: str, desc_selector: str
) -> tuple[str | None, str | None]:
    """(title, description) for a source whose detail pages carry no JSON-LD Event
    block — og:title with the site suffix stripped, <h1> fallback."""
    raw_title = og_title(soup)
    if raw_title:
        if raw_title == site_name or raw_title.startswith(site_name + " -"):
            # Site-level page (homepage) — og:title is the venue/site name, not an event
            title = None
        else:
            title = raw_title.removesuffix(title_suffix).strip() or None
    else:
        h1 = soup.find("h1")
        title = h1.get_text(strip=True) if h1 else None
    title = title[:LOCALIZED_TEXT_MAX_TITLE_CHARS] if title else None

    return title, localized_description(soup, desc_selector)
