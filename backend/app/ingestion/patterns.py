"""Regex builders shared by the ingestion content filters and geocoders."""

import re


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
