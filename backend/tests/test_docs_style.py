"""Docs guard: the mechanical house-style rules and code→doc pointer resolution.

The rules themselves live in docs/writing-docs.md. `test_docs_follow_house_style`
checks the ones a regex can judge without false positives;
`test_code_doc_pointers_resolve` checks that every pointer from code into a doc
still names a file, `§N` section and heading that exist.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


REPO = Path(__file__).parent.parent.parent

# Ratchet: docs not yet rewritten to the house style, exempt from the style test
# (never from the pointer test). Each rewrite removes its doc in the same commit;
# the list only shrinks.
NOT_YET_REWRITTEN = {
    "docs/conventions.md",
    "docs/data-model.md",
    "docs/frontend.md",
    "docs/organizer-portal.md",
}

MAX_UNIT_WORDS = 60
MAX_BANNER_WORDS = 30
MAX_TOTAL_WORDS = {"CLAUDE.md": 1500, "README.md": 1500}
BANNER_PREFIX = "What's in here:"

FENCE = re.compile(r"^\s*(```|~~~)")
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*\s*$")
NUMBERED_HEADING = re.compile(r"^##\s+(\d+)\.\s")
TABLE_ROW = re.compile(r"^\s*\|")
RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
QUOTE = re.compile(r"^\s*>")
COMMENT_INLINE = re.compile(r"<!--.*?-->")
ADMONITION_TAG = re.compile(r"^\[!\w+\]$")
PATH_LINE_CITE = re.compile(
    r"[\w./-]+\.(?:py|tsx?|jsx?|css|md|json|toml|ya?ml|sh|html|sql|ini|txt):\d+\b"
)

# A doc pointer, then an optional `§N`, then optional quoted heading names
# chained by `,`/`and`/`or`/`/` — all on one line.
POINTER = re.compile(
    r"(?<![\w./-])((?:docs/[\w/-]+|CLAUDE|README|CONTEXT)\.md)"
    r"(?:\s+§(\d+))?"
    r'((?:\s*(?:,|and|or|/)?\s*"[^"\n]+")*)'
)
QUOTED = re.compile(r'"([^"\n]+)"')


def _governed_docs() -> list[str]:
    docs = sorted(f"docs/{p.name}" for p in (REPO / "docs").glob("*.md"))
    return ["CLAUDE.md", "README.md", *docs]


def _prose_lines(text: str) -> list[tuple[int, str]]:
    """(line number, line) outside fenced code blocks and HTML comments."""
    out: list[tuple[int, str]] = []
    in_fence = in_comment = False
    for no, line in enumerate(text.splitlines(), start=1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if in_comment:
            if "-->" not in line:
                continue
            line, in_comment = line.split("-->", 1)[1], False
        line = COMMENT_INLINE.sub("", line)
        if "<!--" in line:
            line, in_comment = line.split("<!--", 1)[0], True
        out.append((no, line))
    return out


def _units(text: str) -> list[tuple[int, str]]:
    """Split prose into the units the cap applies to: bullets, paragraphs and
    blockquotes (a GitHub admonition is one blockquote). Headings, table rows
    and horizontal rules are skipped."""
    units: list[tuple[int, str]] = []
    start, buf, kind = 0, [], ""

    def flush() -> None:
        nonlocal buf, kind
        if buf:
            units.append((start, " ".join(buf)))
        buf, kind = [], ""

    for no, line in _prose_lines(text):
        if not line.strip() or HEADING.match(line) or TABLE_ROW.match(line) or RULE.match(line):
            flush()
            continue
        if QUOTE.match(line):
            if kind != "quote":
                flush()
                start, kind = no, "quote"
            buf.append(re.sub(r"^\s*(>\s?)+", "", line))
        elif LIST_ITEM.match(line):
            flush()
            start, kind = no, "item"
            buf.append(LIST_ITEM.sub("", line, count=1))
        else:
            if not buf:
                start, kind = no, "para"
            buf.append(line.strip())
    flush()
    return units


def _word_count(unit: str) -> int:
    return sum(1 for tok in unit.split() if not ADMONITION_TAG.match(tok))


def _style_failures(name: str, text: str) -> list[str]:
    failures: list[str] = []
    for no, unit in _units(text):
        words = _word_count(unit)
        if words > MAX_UNIT_WORDS:
            failures.append(
                f"{name}:{no}: {words} words in one bullet/paragraph "
                f"(cap {MAX_UNIT_WORDS}) — split it: {unit[:60]}…"
            )
    for no, line in _prose_lines(text):
        for cite in PATH_LINE_CITE.finditer(line):
            failures.append(
                f"{name}:{no}: line-number cite {cite.group(0)!r} — use path::symbol"
            )
    if name.startswith("docs/"):
        failures.extend(_banner_failures(name, text))
    limit = MAX_TOTAL_WORDS.get(name)
    if limit is not None and len(text.split()) > limit:
        failures.append(f"{name}: {len(text.split())} words (limit {limit})")
    return failures


def _banner_failures(name: str, text: str) -> list[str]:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 2 or not lines[0].startswith("# "):
        return [f"{name}: must open with an H1 title"]
    banner = lines[1]
    if not banner.startswith(BANNER_PREFIX):
        return [f"{name}: line after the H1 must be the {BANNER_PREFIX!r} banner"]
    words = len(banner.split())
    if words > MAX_BANNER_WORDS:
        return [f"{name}: banner is {words} words (cap {MAX_BANNER_WORDS})"]
    return []


def test_ratchet_lists_only_existing_docs() -> None:
    stale = NOT_YET_REWRITTEN - set(_governed_docs())
    assert not stale, f"NOT_YET_REWRITTEN names docs that don't exist: {stale}"


def test_docs_follow_house_style() -> None:
    failures: list[str] = []
    for name in _governed_docs():
        if name in NOT_YET_REWRITTEN:
            continue
        failures.extend(_style_failures(name, (REPO / name).read_text(encoding="utf-8")))
    assert not failures, "House-style violations (see docs/writing-docs.md):\n" + "\n".join(
        failures
    )


def _headings(doc: Path) -> tuple[list[str], set[str]]:
    """(normalised heading texts, `§N` numbers) for a doc."""
    texts: list[str] = []
    numbers: set[str] = set()
    for _, line in _prose_lines(doc.read_text(encoding="utf-8")):
        if m := NUMBERED_HEADING.match(line):
            numbers.add(m.group(1))
        if m := HEADING.match(line):
            texts.append(re.sub(r"^\d+\.\s*", "", m.group(1)).lower())
    return texts, numbers


def _heading_exists(quoted: str, texts: list[str]) -> bool:
    """The quoted name is a whole heading, or its leading words."""
    q = quoted.lower()
    return any(t == q or (t.startswith(q) and not t[len(q)].isalnum()) for t in texts)


def _code_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    )
    return [
        f
        for f in result.stdout.splitlines()
        if not f.endswith(".md")
        and not f.startswith("docs/")
        and "/_generated/" not in f
        # This guard names the docs as string literals, which read as pointers.
        and f != "backend/tests/test_docs_style.py"
    ]


def test_code_doc_pointers_resolve() -> None:
    failures: list[str] = []
    cache: dict[str, tuple[list[str], set[str]]] = {}
    for path in _code_files():
        try:
            text = (REPO / path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        for no, line in enumerate(text.splitlines(), start=1):
            for m in POINTER.finditer(line):
                target, section, chain = m.group(1), m.group(2), m.group(3)
                where = f"{path}:{no}: {m.group(0).strip()!r}"
                doc = REPO / target
                if not doc.is_file():
                    failures.append(f"{where} — {target} doesn't exist")
                    continue
                if not section and not chain:
                    continue
                texts, numbers = cache.setdefault(target, _headings(doc))
                if section and section not in numbers:
                    failures.append(f"{where} — {target} has no '## {section}.' heading")
                for quoted in QUOTED.findall(chain):
                    if not _heading_exists(quoted, texts):
                        failures.append(f"{where} — {target} has no heading {quoted!r}")
    assert not failures, (
        "Code→doc pointers that no longer resolve (fix the pointer or the heading "
        "in the same commit):\n" + "\n".join(failures)
    )
