"""Ingest-time keyword prefilters (Layer 1 of the three-layer content gates).

Word-boundary keyword matching that sets Event.is_explicit / Event.is_non_event
before any LLM call — see CLAUDE.md "Content Safety" and "Non-Event Filter".
"""

import re

from app.constants import (
    EXPLICIT_KEYWORDS,
    NON_EVENT_TITLE_KEYWORDS,
    NON_EVENT_VENUE_KEYWORDS,
)
from app.ingestion.sanitize import html_to_text

_EXPLICIT_KEYWORD_PATTERNS = [
    re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
    for kw in EXPLICIT_KEYWORDS
]


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
    text = re.sub(r"\s+", " ", text)
    return any(pattern.search(text) for pattern in _EXPLICIT_KEYWORD_PATTERNS)


_NON_EVENT_TITLE_PATTERNS = [
    re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
    for kw in NON_EVENT_TITLE_KEYWORDS
]
_NON_EVENT_VENUE_PATTERNS = [
    re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE)
    for kw in NON_EVENT_VENUE_KEYWORDS
]


def is_non_event_text(title: str | None, venue_name: str | None) -> bool:
    """Word-boundary match flagging non-event listings (Event.is_non_event).

    Scoped narrower than is_explicit_text: NON_EVENT_TITLE_KEYWORDS run against
    the title only (descriptions routinely mention "gift cards available" as a
    payment option — a false positive), and NON_EVENT_VENUE_KEYWORDS run
    against the venue name only (online-only webinars/recordings). Layer 2
    (LLM "non_event" classification flag) catches what this misses.
    """
    title_text = (html_to_text(title) or "") if title else ""
    if any(p.search(title_text) for p in _NON_EVENT_TITLE_PATTERNS):
        return True
    venue_text = (html_to_text(venue_name) or "") if venue_name else ""
    return any(p.search(venue_text) for p in _NON_EVENT_VENUE_PATTERNS)
