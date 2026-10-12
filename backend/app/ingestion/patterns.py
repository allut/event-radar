"""Regex builders shared by the ingestion content filters and geocoders."""

import re

from app.constants.core import SQL_REGEX_WORD_BOUNDARY


def alternation_pattern(keywords: frozenset[str]) -> re.Pattern[str]:
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


def _sql_case_fold_char(ch: str) -> str:
    """``[õÕ]`` for a non-ASCII cased letter, the escaped char otherwise.
    ``~*`` folds non-ASCII letters only under a Unicode-aware collation; under
    ``C`` it leaves ``Õ`` unmatched by ``õ``, so the pattern spells out both."""
    lower, upper = ch.lower(), ch.upper()
    if ch.isascii() or lower == upper or len(lower) != 1 or len(upper) != 1:
        return re.escape(ch)
    return f"[{lower}{upper}]"


def sql_alternation_pattern(keywords: frozenset[str]) -> str:
    """Postgres-regex twin of ``alternation_pattern`` (``\\y`` word boundaries
    instead of ``\\b``); case-insensitivity comes from the ``~*`` operator the
    caller applies, not an inline flag. Non-ASCII letters carry both cases
    themselves, so the match doesn't depend on the database's collation."""
    body = "|".join("".join(_sql_case_fold_char(ch) for ch in kw) for kw in keywords)
    return f"{SQL_REGEX_WORD_BOUNDARY}(?:{body}){SQL_REGEX_WORD_BOUNDARY}"

