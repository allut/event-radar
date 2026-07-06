"""Split a single HTML field that concatenates two+ languages into per-locale segments.

Some sources expose only one page per event but the body itself switches
language mid-document (an Estonian description followed by an "ENG:"-tagged
translation, or a language switch with no marker at all at a paragraph
boundary). Marker regexes are too fragile to catch the unmarked cases, so this
runs per-block language detection instead: split the (already-sanitized) HTML
into block-level chunks, detect each chunk's language, group by locale, and
reconstruct one HTML segment per locale. Wired into ingestion (``app.
ingestion.adapter.SourceAdapter.run``) and the one-off backfill script
(``scripts/backfill_language_split.py``) to fill in whichever ``*_localized``
locale keys are still missing — never to overwrite a locale obtained from a
real per-locale page fetch.
"""

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag
from lingua import Language, LanguageDetectorBuilder

from app.constants import (
    LANGUAGE_SPLIT_MIN_BLOCK_CHARS,
    LANGUAGE_SPLIT_MIN_LOCALE_SHARE,
    VALID_LOCALES,
)

# Russian is the only VALID_LOCALES member written in Cyrillic — en/et are
# both Latin-script. A block dominated by Cyrillic characters cannot
# genuinely be en/et; a short block that reads that way (a Latin-alphabet
# name embedded in an otherwise-Russian sentence, e.g. "Лектор - фармацевт,
# Tatjana Tšernoglazova") is a real lingua misdetection observed against
# production data, not a language switch — treated as undetermined so it
# carries forward the surrounding block's locale instead of fracturing a
# monolingual Russian description.
_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")
_SCRIPT_CHAR_RE = re.compile(r"[Ѐ-ӿA-Za-zÀ-ɏ]")
_CYRILLIC_DOMINANCE_THRESHOLD = 0.2

# Container tags that already carry their own block-level spacing when
# rendered — each one is a single detection unit. Matches
# HTML_SANITIZE_ALLOWED_TAGS' block-level subset (ul/ol are unwrapped into
# their li children below, so they aren't listed here directly).
_BLOCK_CONTAINER_TAGS = frozenset({"p", "h3", "h4", "li", "blockquote"})
_LIST_CONTAINER_TAGS = frozenset({"ul", "ol"})

_LINGUA_LANGUAGE_BY_LOCALE = {
    "en": Language.ENGLISH,
    "et": Language.ESTONIAN,
    "ru": Language.RUSSIAN,
}


def _get_detector() -> object:
    languages = [_LINGUA_LANGUAGE_BY_LOCALE[locale] for locale in sorted(VALID_LOCALES)]
    return LanguageDetectorBuilder.from_languages(*languages).build()


_DETECTOR = None


def _detector() -> object:
    global _DETECTOR
    if _DETECTOR is None:
        _DETECTOR = _get_detector()
    return _DETECTOR


@dataclass
class _Block:
    html: str
    text: str
    # "container": a p/li/h3/h4/blockquote tag, already has its own block
    # spacing when rendered. "line": bare text/inline-markup that sat between
    # <br> tags at the top level — needs an explicit <br> when rejoined with
    # a sibling "line" block.
    kind: str


def _flush_line_run(nodes: list, blocks: list[_Block]) -> None:
    """Split a run of top-level non-container nodes at <br> boundaries into line blocks."""
    current: list = []
    for node in nodes:
        if isinstance(node, Tag) and node.name == "br":
            _append_line_block(current, blocks)
            current = []
        else:
            current.append(node)
    _append_line_block(current, blocks)


def _append_line_block(nodes: list, blocks: list[_Block]) -> None:
    if not nodes:
        return
    html = "".join(str(n) for n in nodes)
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    if text:
        blocks.append(_Block(html, text, "line"))


def _extract_blocks(html: str) -> list[_Block]:
    soup = BeautifulSoup(html, "html.parser")
    blocks: list[_Block] = []
    pending_line_nodes: list = []

    for node in list(soup.contents):
        if isinstance(node, Tag) and node.name in _BLOCK_CONTAINER_TAGS:
            _flush_line_run(pending_line_nodes, blocks)
            pending_line_nodes = []
            text = node.get_text(" ", strip=True)
            if text:
                blocks.append(_Block(str(node), text, "container"))
        elif isinstance(node, Tag) and node.name in _LIST_CONTAINER_TAGS:
            _flush_line_run(pending_line_nodes, blocks)
            pending_line_nodes = []
            for li in node.find_all("li", recursive=False):
                text = li.get_text(" ", strip=True)
                if text:
                    blocks.append(_Block(str(li), text, "container"))
        else:
            pending_line_nodes.append(node)
    _flush_line_run(pending_line_nodes, blocks)
    return blocks


def _cyrillic_dominant(text: str) -> bool:
    script_chars = _SCRIPT_CHAR_RE.findall(text)
    if not script_chars:
        return False
    cyrillic_chars = _CYRILLIC_RE.findall(text)
    return len(cyrillic_chars) / len(script_chars) > _CYRILLIC_DOMINANCE_THRESHOLD


def _detect_locale(text: str) -> str | None:
    if len(text) < LANGUAGE_SPLIT_MIN_BLOCK_CHARS:
        return None
    language = _detector().detect_language_of(text)  # type: ignore[attr-defined]
    if language is None:
        return None
    for locale, lang in _LINGUA_LANGUAGE_BY_LOCALE.items():
        if lang == language:
            if locale != "ru" and _cyrillic_dominant(text):
                return None
            return locale
    return None


def _assign_locales(blocks: list[_Block]) -> list[str | None]:
    """Detect each block's locale, then carry the nearest determined locale into
    the too-short-to-detect blocks around it (backward-fill the head, forward-fill
    the rest) so short blocks aren't orphaned from their surrounding paragraph."""
    detected = [_detect_locale(b.text) for b in blocks]

    # Backward-fill leading undetermined blocks from the first determined one.
    first_known = next((loc for loc in detected if loc is not None), None)
    filled: list[str | None] = list(detected)
    for i, loc in enumerate(filled):
        if loc is not None:
            break
        filled[i] = first_known

    # Forward-fill everything else from the nearest preceding determined block.
    last_known = filled[0]
    for i, loc in enumerate(filled):
        if loc is not None:
            last_known = loc
        else:
            filled[i] = last_known
    return filled


def split_by_language(html: str | None) -> dict[str, str]:
    """Split ``html`` into per-locale HTML segments if it is genuinely bilingual.

    Returns ``{}`` when the text doesn't confidently split into at least two
    locales each covering more than ``LANGUAGE_SPLIT_MIN_LOCALE_SHARE`` of the
    total detected text — e.g. a monolingual description, or one with only a
    single stray foreign phrase.
    """
    if not html or not html.strip():
        return {}

    blocks = _extract_blocks(html)
    if not blocks:
        return {}

    locales = _assign_locales(blocks)
    if all(loc is None for loc in locales):
        return {}

    total_chars = sum(len(b.text) for b in blocks)
    if total_chars == 0:
        return {}

    segments: dict[str, list[_Block]] = {}
    for block, locale in zip(blocks, locales, strict=True):
        if locale is None:
            continue
        segments.setdefault(locale, []).append(block)

    shares = {
        locale: sum(len(b.text) for b in locale_blocks) / total_chars
        for locale, locale_blocks in segments.items()
    }
    qualifying = {
        locale for locale, share in shares.items() if share > LANGUAGE_SPLIT_MIN_LOCALE_SHARE
    }
    if len(qualifying) < 2:
        return {}

    result: dict[str, str] = {}
    for locale in qualifying:
        pieces: list[str] = []
        prev_kind: str | None = None
        for block in segments[locale]:
            if prev_kind == "line" and block.kind == "line":
                pieces.append("<br>")
            pieces.append(block.html)
            prev_kind = block.kind
        result[locale] = "".join(pieces)
    return result


def fill_missing_locales(
    localized: dict[str, str] | None, source_text: str | None
) -> dict[str, str] | None:
    """Merge locales split out of ``source_text`` into ``localized``, without
    overwriting any locale key already present (a real per-locale page fetch is
    higher quality than a heuristic split). Returns ``localized`` unchanged
    (including ``None``) if nothing new was found."""
    split = split_by_language(source_text)
    if not split:
        return localized
    merged = dict(localized) if localized else {}
    changed = False
    for locale, text in split.items():
        if locale not in merged:
            merged[locale] = text
            changed = True
    return merged if changed else localized
