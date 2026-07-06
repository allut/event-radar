"""Deterministic price parsing/extraction from listing text.

Fienta price_from_string grammar, EUR-amount scanning, booking-fee stripping,
and the price-context digest fed to the LLM classify prompt.
"""

import re
from typing import Any

from bs4 import BeautifulSoup

from app.constants import (
    CURRENCY_AMOUNT_RE,
    DEFAULT_CURRENCY,
    PRICE_CONTEXT_MAX_CHARS,
    PRICE_FEE_CLAUSE_RE,
    PRICE_FEE_KEYWORDS,
    PRICE_FROM_STRING_RE,
)

def normalize_currency(raw: Any, has_price: bool) -> str | None:
    """Coerce a raw currency value; fall back to DEFAULT_CURRENCY only when a price exists."""
    if raw:
        return str(raw)
    return DEFAULT_CURRENCY if has_price else None


_PRICE_FROM_STRING_RE = re.compile(PRICE_FROM_STRING_RE, re.IGNORECASE)


def parse_price_from_string(
    value: str | None,
) -> tuple[float | None, float | None, str | None, bool]:
    """Parse a Fienta listing price_from_string into
    (price_min, price_max, currency, has_free_tier).

    Grammar (verified across all 803 live rows): optional "From ", a number, a 3-letter
    currency; optional ", free" suffix; or the literal "Free"; or None/empty.
    price_min/price_max bound the PAID amount(s); has_free_tier flags a paid listing
    that also has a free option (e.g. members/companions) alongside the paid tier.
      - "10 EUR"           -> (10, 10, "EUR", False)  exact price, min == max
      - "From 28 EUR"      -> (28, None, "EUR", False) open-ended, no listing ceiling
      - "From 6 EUR, free" -> (6, None, "EUR", True)   paid from 6, free tier also exists
      - "40 EUR, free"     -> (40, 40, "EUR", True)    paid 40, free tier also exists
      - "Free"             -> (0, 0, None, False)       genuinely free, no paid tier
      - None / unparseable -> (None, None, None, False)
    """
    if not value:
        return (None, None, None, False)
    text = value.strip()
    has_free = text.lower() == "free" or text.lower().endswith(", free")
    m = _PRICE_FROM_STRING_RE.search(text)
    if not m:
        return (0.0, 0.0, None, False) if has_free else (None, None, None, False)
    amount = float(m.group(1).replace(",", "."))
    currency = m.group(2).upper()
    # The optional "From " prefix is captured inside the match, so test the raw
    # string's start rather than text[:m.start()] (which would be empty here).
    is_from = text.lower().startswith("from")
    ceiling = None if is_from else amount
    return (amount, ceiling, currency, has_free)


_CURRENCY_AMOUNT_RE = re.compile(CURRENCY_AMOUNT_RE, re.IGNORECASE)

_PRICE_FEE_CLAUSE_RE = re.compile(
    PRICE_FEE_CLAUSE_RE.format(
        keywords="|".join(re.escape(kw) for kw in sorted(PRICE_FEE_KEYWORDS, key=len, reverse=True))
    ),
    re.IGNORECASE,
)


def strip_fee_amounts(text: str | None) -> str | None:
    """Remove booking/service/agent-fee clauses from free text.

    Strips patterns like "agenditasu 3,20 €" or "teenustasu 1.40€/ pilet" so
    a downstream price extractor doesn't treat the fee as a ticket price.
    Real prices that trail in the same run survive ("agenditasu 3,20 € Pilet 45 €"
    → " Pilet 45 €"). No-op when no fee keyword is present.
    """
    if not text:
        return text
    return _PRICE_FEE_CLAUSE_RE.sub("", text)


def eur_amounts_from_text(value: str | None) -> list[float]:
    """Return every €/EUR amount found in text (duplicates included), or [] if none.

    Only matches amounts adjacent to a € symbol or EUR code (so durations, years, and
    other stray numbers are ignored). Handles European "12,50" and US "12.50" decimals.
    """
    if not value:
        return []
    return [
        float((m.group(1) or m.group(2)).replace(",", "."))
        for m in _CURRENCY_AMOUNT_RE.finditer(value)
    ]


def eur_price_bounds_from_text(value: str | None) -> tuple[float | None, float | None]:
    """Return (min, max) of all €/EUR amounts in text, or (None, None) if none found."""
    amounts = eur_amounts_from_text(value)
    if not amounts:
        return (None, None)
    return (min(amounts), max(amounts))


def price_context_digest(*texts: str | None) -> str:
    """Return only the lines carrying a €/EUR amount from the given raw HTML texts,
    joined and capped at ``PRICE_CONTEXT_MAX_CHARS``.

    Full ``description_orig``/``important_info`` can run past the LLM prompt's
    per-field char caps (e.g. IMPORTANT_INFO_MAX_CHARS), truncating away distant
    price tiers (see VAN GOGH: paid tiers up to €52 sit past the 1200-char cut).
    Distilling to price-bearing lines first lets the full tier list reach the
    prompt within a small, fixed budget regardless of surrounding prose length.
    Each text is converted from HTML and fee clauses (agenditasu, service fee,
    etc.) are stripped before scanning, mirroring the prompt-field pipeline.
    """
    lines: list[str] = []
    for text in texts:
        if not text:
            continue
        # Newline-separated (not html_to_text's space-joined) so each block/line
        # can be scanned and kept/dropped independently.
        raw_plain = BeautifulSoup(text, "html.parser").get_text(separator="\n", strip=True)
        plain = strip_fee_amounts(raw_plain) or ""
        for line in plain.splitlines():
            line = line.strip()
            if line and _CURRENCY_AMOUNT_RE.search(line):
                lines.append(line)

    # Cap by whole lines rather than a raw character slice — an arbitrary
    # mid-string cut can truncate a price literal (e.g. "€15" -> "€1"), which
    # would otherwise feed a spurious amount into the validation set built
    # from this digest (see _validate_llm_prices).
    kept: list[str] = []
    total_len = 0
    for line in lines:
        added_len = len(line) + (1 if kept else 0)  # +1 for the joining "\n"
        if total_len + added_len > PRICE_CONTEXT_MAX_CHARS:
            break
        kept.append(line)
        total_len += added_len
    return "\n".join(kept)
