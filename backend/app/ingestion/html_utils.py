"""Generic BeautifulSoup helpers shared across ingestion modules.

Kept separate from html_base.py (which owns adapter-specific scraping logic)
because locale_urls.py is imported by html_base.py — a shared low-level
module avoids a circular import between the two.
"""

from bs4 import Tag


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
