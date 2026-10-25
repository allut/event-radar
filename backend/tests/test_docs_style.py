"""Docs guard: the mechanical house-style rules and pointer resolution both ways.

The rules themselves live in docs/writing-docs.md. `test_docs_follow_house_style`
checks the ones a regex can judge without false positives;
`test_code_doc_pointers_resolve` checks that every pointer from code into a doc
still names a file, `§N` section and heading that exist;
`test_doc_code_cites_resolve` checks that every backticked repo path and
`path::symbol` cite in a governed doc still names a tracked file and a symbol in it.
"""

from __future__ import annotations

import fnmatch
import re
import subprocess
from functools import cache
from pathlib import Path


REPO = Path(__file__).parent.parent.parent

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

CODE_SPAN = re.compile(r"`([^`\n]+)`")
# A span counts as a repo path only when it ends in one of these or in `/`, so
# `Europe/Tallinn` and `openai/gpt-oss-120b` never read as paths. A leading `/`
# is a route or an absolute path, and a lone `.module.css` is an extension.
CITE_PATH = re.compile(
    r"^(?!/)(?!\.[\w.]+$)[\w.*\[\]{},/-]+"
    r"(?:\.(?:py|tsx?|jsx?|css|md|json|toml|ya?ml|sh|html|ini|txt)|/)$"
)
BRACES = re.compile(r"\{([^{}]*)\}")
# Paths a doc names on purpose that no commit tracks: gitignored or absent
# files, build output, runtime state and the `Name.*` folder-convention
# placeholders. A new entry needs the same reason.
UNTRACKED_CITES = {
    "backend/.env",
    "backend/logs/",
    "backend/pyproject.toml",
    ".playwright-mcp/",
    "app-shell.html",
    "robots.txt",
    "index.json",
    "prerender-chain-state/",
    "Name.tsx",
    "Name.module.css",
    "Name.test.tsx",
    "Name.test.ts",
}
UNTRACKED_PREFIXES = ("dist/",)


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
    start, kind = 0, ""
    buf: list[str] = []

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


def test_docs_follow_house_style() -> None:
    failures: list[str] = []
    for name in _governed_docs():
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


@cache
def _tracked() -> tuple[frozenset[str], frozenset[str]]:
    """(tracked files, every directory that holds one)."""
    result = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    )
    files = frozenset(result.stdout.splitlines())
    dirs = frozenset(f.rsplit("/", i)[0] for f in files for i in range(1, f.count("/") + 1))
    return files, dirs


def _expand_braces(path: str) -> list[str]:
    """`a/{b,c}.py` → `a/b.py`, `a/c.py`."""
    m = BRACES.search(path)
    if not m:
        return [path]
    return [
        expanded
        for alt in m.group(1).split(",")
        for expanded in _expand_braces(path[: m.start()] + alt + path[m.end() :])
    ]


def _resolve_cite_path(path: str) -> list[str]:
    """Tracked files or directories the cited path names, by exact path or by
    a trailing-segment match (`fienta.py`, `geocode/nominatim.py`)."""
    files, dirs = _tracked()
    candidates = dirs if path.endswith("/") else files
    path = path.rstrip("/")
    if "*" in path:
        return [c for c in candidates if fnmatch.fnmatch(c, path) or fnmatch.fnmatch(c, "*/" + path)]
    return [c for c in candidates if c == path or c.endswith("/" + path)]


def _defines(file: str, symbol: str) -> bool:
    try:
        text = (REPO / file).read_text(encoding="utf-8")
    except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
        return False
    return re.search(rf"(?<![\w$]){re.escape(symbol)}(?![\w$])", text) is not None


def _cite_failures(name: str, text: str) -> list[str]:
    failures: list[str] = []
    for no, line in _prose_lines(text):
        for span in CODE_SPAN.findall(line):
            path, _, symbol = span.strip().partition("::")
            # A brace with no comma is a placeholder, such as `{locale}`.
            if not CITE_PATH.match(path) or re.search(r"\{[^,}]*\}", path):
                continue
            for expanded in _expand_braces(path):
                if expanded in UNTRACKED_CITES or expanded.startswith(UNTRACKED_PREFIXES):
                    continue
                where = f"{name}:{no}: `{span}`"
                matches = _resolve_cite_path(expanded)
                if not matches:
                    failures.append(f"{where} — no tracked path {expanded!r}")
                    continue
                if not symbol:
                    continue
                bare = re.sub(r"\(.*$", "", symbol).split(".")[-1].strip()
                if not any(_defines(m, bare) for m in matches):
                    failures.append(f"{where} — {bare!r} not found in {', '.join(sorted(matches))}")
    return failures


def test_doc_code_cites_resolve() -> None:
    failures: list[str] = []
    for name in _governed_docs():
        failures.extend(_cite_failures(name, (REPO / name).read_text(encoding="utf-8")))
    assert not failures, (
        "Doc→code cites that no longer resolve (fix the cite in the same commit as "
        "the rename; a deliberately untracked path goes in UNTRACKED_CITES):\n"
        + "\n".join(failures)
    )
