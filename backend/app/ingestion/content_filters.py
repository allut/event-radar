"""Ingest-time keyword prefilters (Layer 1 of the three-layer content gates).

Word-boundary keyword matching that sets Event.is_explicit / Event.is_non_event
before any LLM call — see CLAUDE.md "Content Safety" and "Non-Event Filter".
"""

import re

from app.constants import (
    CONTENT_FILTER_WHITESPACE_COLLAPSE_RE,
    EXPLICIT_KEYWORDS,
    NON_EVENT_TITLE_KEYWORDS,
    NON_EVENT_VENUE_KEYWORDS,
)
from app.ingestion.sanitize import html_to_text

def _alternation_pattern(keywords: frozenset[str]) -> re.Pattern[str]:
    """One word-boundary alternation regex for a keyword group.

    A single-pass alternation is far cheaper than searching the text once per
    keyword (K separately-compiled regexes over the same text, O(K*L)) — the
    regex engine's alternation matching finds the same word-boundary hits in
    one pass over the text.
    """
    return re.compile(
        r"\b(?:" + "|".join(re.escape(kw) for kw in keywords) + r")\b",
        re.IGNORECASE,
    )


_EXPLICIT_KEYWORD_PATTERN = _alternation_pattern(EXPLICIT_KEYWORDS)


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


_NON_EVENT_TITLE_PATTERN = _alternation_pattern(NON_EVENT_TITLE_KEYWORDS)
_NON_EVENT_VENUE_PATTERN = _alternation_pattern(NON_EVENT_VENUE_KEYWORDS)


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
