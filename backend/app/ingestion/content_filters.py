"""Ingest-time keyword prefilters (Layer 1 of the three-layer content gates).

Word-boundary keyword matching that sets Event.is_explicit / Event.is_non_event
before any LLM call.
"""

import re
from collections.abc import Iterable

from app.constants.ingestion import (
    CONTENT_FILTER_WHITESPACE_COLLAPSE_RE,
    EXPLICIT_KEYWORDS,
    NON_EVENT_TITLE_KEYWORDS,
    NON_EVENT_VENUE_KEYWORDS,
)
from app.ingestion.sanitize import html_to_text
from app.ingestion.patterns import alternation_pattern

_EXPLICIT_KEYWORD_PATTERN = alternation_pattern(EXPLICIT_KEYWORDS)


def is_explicit_text(*parts: str | None) -> bool:
    """Word-boundary match of EXPLICIT_KEYWORDS against the joined text parts.

    Used at ingest time to flag sexually-explicit listings (Event.is_explicit)
    before they ever reach the LLM. HTML tags are stripped before matching so
    stored HTML descriptions are scanned correctly. Whitespace runs (including
    literal newlines within a single text node, not just HTML-tag breaks) are
    collapsed to a single space so multi-word keywords (e.g. "anal sex") still
    match across them — a miss here has no Layer-2 backstop, since flagged and
    unflagged-but-explicit events both skip straight past the LLM call.
    """
    text = " ".join(html_to_text(p) or "" for p in parts if p)
    text = re.sub(CONTENT_FILTER_WHITESPACE_COLLAPSE_RE, " ", text)
    return bool(_EXPLICIT_KEYWORD_PATTERN.search(text))


_NON_EVENT_TITLE_PATTERN = alternation_pattern(NON_EVENT_TITLE_KEYWORDS)
_NON_EVENT_VENUE_PATTERN = alternation_pattern(NON_EVENT_VENUE_KEYWORDS)


def is_non_event_text(title: str | None, venue_name: str | None) -> bool:
    """Word-boundary match flagging non-event listings (Event.is_non_event).

    Scoped narrower than is_explicit_text: NON_EVENT_TITLE_KEYWORDS run against
    the title only (descriptions routinely mention "gift cards available" as a
    payment option — a false positive), and NON_EVENT_VENUE_KEYWORDS run
    against the venue name only (online-only webinars/recordings). Layer 2
    (LLM "non_event" classification flag) catches what this misses.
    """
    title_text = (html_to_text(title) or "") if title else ""
    if _NON_EVENT_TITLE_PATTERN.search(title_text):
        return True
    venue_text = (html_to_text(venue_name) or "") if venue_name else ""
    return bool(_NON_EVENT_VENUE_PATTERN.search(venue_text))


def localized_text_values(*maps: dict[str, str] | None) -> list[str]:
    """Flatten ``*_localized`` locale->text maps into their text values so the
    explicit filter can scan EN/RU content too — users in those locales (and
    the digest) are served ``resolve_title()``-style localized text, which the
    Estonian-only ``*_orig`` scan never saw (OWASP audit M-5)."""
    return [text for m in maps if m for text in m.values() if isinstance(text, str) and text]


def content_flags(
    title: str | None,
    description: str | None,
    venue_name: str | None,
    important_info: str | None,
    extra_explicit_texts: Iterable[str | None] = (),
) -> tuple[bool, bool]:
    """(is_explicit, is_non_event) computed together, converting each distinct
    field's HTML to plain text exactly once.

    is_explicit_text() and is_non_event_text() called separately (as every
    call site did before Big-O audit #5, item 2.3) each re-run html_to_text —
    a fresh BeautifulSoup parse — on title and venue_name, since both filters
    need them. Call sites needing both flags (adapter.py, refetch.py) should
    use this instead.
    """
    title_text = (html_to_text(title) or "") if title else ""
    description_text = (html_to_text(description) or "") if description else ""
    venue_text = (html_to_text(venue_name) or "") if venue_name else ""
    important_info_text = (html_to_text(important_info) or "") if important_info else ""

    extra_text = [
        (html_to_text(t) or "") for t in extra_explicit_texts if t and isinstance(t, str)
    ]
    explicit_input = " ".join(
        t
        for t in (title_text, description_text, venue_text, important_info_text, *extra_text)
        if t
    )
    explicit_input = re.sub(CONTENT_FILTER_WHITESPACE_COLLAPSE_RE, " ", explicit_input)
    is_explicit = bool(_EXPLICIT_KEYWORD_PATTERN.search(explicit_input))

    is_non_event = bool(_NON_EVENT_TITLE_PATTERN.search(title_text)) or bool(
        _NON_EVENT_VENUE_PATTERN.search(venue_text)
    )
    return is_explicit, is_non_event
