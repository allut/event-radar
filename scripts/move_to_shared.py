"""Move backend constants into shared/app-config.json `scalars`, and repoint both stacks.

Usage:
    python scripts/move_to_shared.py <domain> NAME [NAME ...] [--dry-run]

For each NAME defined in backend/app/constants/<domain>.py it adds the value to
`scalars`, removes the backend definition, regenerates the _generated/ files, and
repoints every backend `from app.constants.<domain> import NAME` to the generated
module. The comments above a removed definition are printed, not moved.

It checks every name before writing anything, and refuses the whole run on a value
`scalars` can't hold or a consumer it can't rewrite. A name that already moved counts
as done, so a second run with the same names changes nothing.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GENERATED_PY = "app._generated.shared_constants"
GENERATED_FILES = ("backend/app/_generated/shared_constants.py", "frontend/src/_generated/sharedConstants.ts")
BACKEND_ROOTS = ("backend/app", "backend/tests", "backend/scripts")
PY_LINE_MAX = 88  # backend/ruff.toml line-length
TS_LINE_MAX = 100
FRONTEND_ROOTS = ("frontend/src", "frontend/functions", "frontend/scripts")
FRONTEND_CONSTANTS = "frontend/src/constants"
FRONTEND_GENERATED = "frontend/src/_generated/sharedConstants"
# Pages Functions load these as unbundled ESM, so their imports carry `.js`.
FRONTEND_JS_EXTENSION_ROOTS = ("frontend/src/constants", "frontend/functions")


class Refused(Exception):
    def __init__(self, reasons: list[str]) -> None:
        super().__init__("\n".join(reasons))
        self.reasons = reasons


@dataclass
class Workspace:
    """Pending file contents, so a file several steps edit is written once."""

    root: Path
    pending: dict[Path, str] = field(default_factory=dict)
    original: dict[Path, str] = field(default_factory=dict)

    def read(self, path: Path) -> str:
        if path in self.pending:
            return self.pending[path]
        return path.read_text(encoding="utf-8")

    def write(self, path: Path, text: str) -> None:
        self.original.setdefault(path, path.read_text(encoding="utf-8"))
        self.pending[path] = text

    def changed(self) -> list[Path]:
        return sorted(p for p, text in self.pending.items() if text != self.original[p])

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


@dataclass
class Report:
    moved: list[str] = field(default_factory=list)
    already: list[str] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)
    renames: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------


def _scalar_value(node: ast.expr) -> object:
    """The `scalars` value for a definition's right-hand side; raises ValueError."""
    try:
        value = ast.literal_eval(node)
    except ValueError:
        raise ValueError("not a literal") from None
    if isinstance(value, bool):
        raise ValueError("a bool, which scalars can't hold")
    if isinstance(value, (int, str)):
        return value
    if isinstance(value, (tuple, list)):
        if not value:
            raise ValueError("an empty list, which scalars can't hold")
        if all(isinstance(v, str) for v in value):
            return list(value)
        raise ValueError("a list with non-str items, which scalars can't hold")
    raise ValueError(f"a {type(value).__name__}, which scalars can't hold")


def _definitions(tree: ast.Module) -> dict[str, ast.Assign | ast.AnnAssign]:
    defs: dict[str, ast.Assign | ast.AnnAssign] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            defs[node.targets[0].id] = node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            defs[node.target.id] = node
    return defs


# ---------------------------------------------------------------------------
# shared/app-config.json
# ---------------------------------------------------------------------------


def _group_anchor(keys: list[str], name: str) -> str | None:
    """The last of `keys` sharing the most leading `_`-separated words with `name`, so a
    new key joins its name group; None when no key shares even the first word."""
    words = name.split("_")

    def shared(key: str) -> int:
        count = 0
        for a, b in zip(key.split("_"), words):
            if a != b:
                break
            count += 1
        return count

    best = max((shared(k) for k in keys), default=0)
    return [k for k in keys if shared(k) == best][-1] if best else None


def _add_scalars(text: str, additions: dict[str, object]) -> str:
    """Add each of `additions` to the `scalars` block after its name group (or at the
    end), keeping the file's hand formatting."""
    for name, value in additions.items():
        lines = text.splitlines(keepends=True)
        start = next(i for i, line in enumerate(lines) if line.strip() == '"scalars": {')
        indent = lines[start][: len(lines[start]) - len(lines[start].lstrip())]
        close = next(i for i in range(start + 1, len(lines)) if lines[i].startswith(indent + "}"))
        key_re = re.compile(rf'{re.escape(indent)}  "([^"]+)":')
        key_lines = {m.group(1): i for i in range(start + 1, close) if (m := key_re.match(lines[i]))}
        keys = list(key_lines)
        entry = f"{indent}  {json.dumps(name)}: {json.dumps(value, ensure_ascii=False)}"
        anchor = _group_anchor(keys, name)
        if anchor is not None and anchor != keys[-1]:
            lines.insert(key_lines[keys[keys.index(anchor) + 1]], entry + ",\n")
        else:
            last = max(i for i in range(start + 1, close) if lines[i].strip())
            body = lines[last].rstrip("\n")
            if not body.endswith(","):
                lines[last] = body + ",\n"
            lines.insert(close, entry + "\n")
        text = "".join(lines)
    scalars = json.loads(text)["scalars"]
    if any(scalars.get(k) != v for k, v in additions.items()):
        raise RuntimeError("shared/app-config.json: the added scalars didn't read back; is `scalars` hand-formatted?")
    return text


# ---------------------------------------------------------------------------
# Line edits
# ---------------------------------------------------------------------------


def _blank(line: str) -> bool:
    return not line.strip()


def _remove_lines(lines: list[str], start: int, end: int) -> list[str]:
    """Drop lines[start:end], leaving the longer of the two blank runs at the join."""
    head = _rstrip_blank(lines[:start])
    tail = _lstrip_blank(lines[end:])
    if not head:
        return tail
    keep = max(start - len(head), len(lines) - end - len(tail))
    return head + ["\n"] * keep + tail


def _rstrip_blank(lines: list[str]) -> list[str]:
    end = len(lines)
    while end and _blank(lines[end - 1]):
        end -= 1
    return lines[:end]


def _lstrip_blank(lines: list[str]) -> list[str]:
    start = 0
    while start < len(lines) and _blank(lines[start]):
        start += 1
    return lines[start:]


def _comment_block_above(lines: list[str], index: int, marker: str) -> list[tuple[int, str]]:
    """The `marker` comment lines directly above lines[index], as (1-based line, text)."""
    block = []
    i = index - 1
    while i >= 0 and lines[i].lstrip().startswith(marker):
        block.append((i + 1, lines[i].rstrip("\n")))
        i -= 1
    return block[::-1]


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------


def _python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for top in BACKEND_ROOTS:
        base = root / top
        if base.is_dir():
            files.extend(
                p for p in base.rglob("*.py")
                if "_generated" not in p.parts and "__pycache__" not in p.parts
            )
    return sorted(files)


def _stmt_scopes(tree: ast.Module) -> dict[int, int]:
    """id(statement) -> id(the statement list holding it)."""
    scopes: dict[int, int] = {}
    for node in [tree, *ast.walk(tree)]:
        for name in ("body", "orelse", "finalbody", "handlers"):
            stmts = getattr(node, name, None)
            if isinstance(stmts, list):
                for stmt in stmts:
                    scopes[id(stmt)] = id(stmts)
    return scopes


def _render_py_import(
    indent: str, module: str, aliases: list[ast.alias], comment: str, multiline: bool = False
) -> list[str]:
    parts = [a.name if a.asname is None else f"{a.name} as {a.asname}" for a in aliases]
    suffix = f"  {comment}" if comment else ""
    one = f"{indent}from {module} import {', '.join(parts)}{suffix}"
    if not multiline and len(one) <= PY_LINE_MAX:
        return [one + "\n"]
    return [f"{indent}from {module} import ({suffix}\n", *[f"{indent}    {p},\n" for p in parts], f"{indent})\n"]


def _import_comment(lines: list[str], node: ast.stmt) -> tuple[str, list[int]]:
    """The comment on an import's first line, and the lines of any comment inside it."""
    first = lines[node.lineno - 1]
    comment = first[first.index("#"):].rstrip("\n") if "#" in first else ""
    inner = [i + 1 for i in range(node.lineno, node.end_lineno or node.lineno) if "#" in lines[i]]
    return comment, inner


def _merged(existing: list[ast.alias], added: list[ast.alias]) -> list[ast.alias]:
    names = [a.name for a in existing]
    new = [a for a in added if (a.name, a.asname) not in {(e.name, e.asname) for e in existing}]
    if names == sorted(names):
        return sorted([*existing, *new], key=lambda a: a.name)
    return [*existing, *new]


@dataclass
class _PyFile:
    path: Path
    tree: ast.Module
    lines: list[str]


def _parse_backend(ws: Workspace) -> list[_PyFile]:
    parsed = []
    for path in _python_files(ws.root):
        text = ws.read(path)
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        parsed.append(_PyFile(path, tree, text.splitlines(keepends=True)))
    return parsed


def _module_aliases(tree: ast.Module, module: str) -> set[str]:
    """Local names bound to `module` itself, by `from <package> import <leaf>` or `import ... as`."""
    package, _, leaf = module.rpartition(".")
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == package and node.level == 0:
            aliases.update(a.asname or a.name for a in node.names if a.name == leaf)
        elif isinstance(node, ast.Import):
            aliases.update(a.asname for a in node.names if a.name == module and a.asname)
    return aliases


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return None if base is None else f"{base}.{node.attr}"
    return None


def _relayed_names(ws: Workspace, files: list[_PyFile], module: str, names: set[str]) -> dict[str, set[str]]:
    """Other constants modules -> the moved names they import from `module`. A consumer
    importing one of those through them would read a generated name via app.constants."""
    constants_dir = ws.root / "backend" / "app" / "constants"
    relays: dict[str, set[str]] = {}
    for f in files:
        if f.path.parent != constants_dir or f"app.constants.{f.path.stem}" == module:
            continue
        for node in f.tree.body:
            if isinstance(node, ast.ImportFrom) and node.module == module and node.level == 0:
                relays.setdefault(f"app.constants.{f.path.stem}", set()).update(
                    a.asname or a.name for a in node.names if a.name in names
                )
    return relays


def _backend_refusals(ws: Workspace, files: list[_PyFile], module: str, names: set[str]) -> list[str]:
    reasons = []
    relays = _relayed_names(ws, files, module, names)
    dotted_names = {f"{module}.{name}" for name in names}
    for f in files:
        prefixes = _module_aliases(f.tree, module) | {module}
        for node in ast.walk(f.tree):
            if isinstance(node, ast.Attribute) and node.attr in names and _dotted(node.value) in prefixes:
                reasons.append(f"{ws.rel(f.path)}:{node.lineno}: {node.attr} is read as a module attribute; rewrite it by hand")
            if isinstance(node, ast.Call):
                args = [*node.args, *(k.value for k in node.keywords)]
                if any(_dotted(a) in prefixes for a in args):
                    reasons.extend(
                        f"{ws.rel(f.path)}:{node.lineno}: {a.value} is named in a string; rewrite it by hand"
                        for a in args if isinstance(a, ast.Constant) and a.value in names
                    )
            if isinstance(node, ast.Constant) and node.value in dotted_names:
                name = str(node.value).rpartition(".")[2]
                reasons.append(f"{ws.rel(f.path)}:{node.lineno}: {name} is named in a string; rewrite it by hand")
            if isinstance(node, ast.ImportFrom) and node.module in relays and node.level == 0:
                reasons.extend(
                    f"{ws.rel(f.path)}:{node.lineno}: {a.name} is imported through {node.module}; "
                    "import it from the generated module by hand"
                    for a in node.names if a.name in relays[node.module]
                )
            if isinstance(node, ast.ImportFrom) and node.module == module and node.level == 0:
                if any(a.name in names for a in node.names):
                    _, inner = _import_comment(f.lines, node)
                    reasons.extend(
                        f"{ws.rel(f.path)}:{line}: a comment inside the import; edit it by hand"
                        for line in inner
                    )
    return reasons


def _repoint_backend(ws: Workspace, f: _PyFile, module: str, names: set[str]) -> None:
    scopes = _stmt_scopes(f.tree)
    old: dict[int, list[ast.ImportFrom]] = {}
    target: dict[int, ast.ImportFrom] = {}
    for node in ast.walk(f.tree):
        if not isinstance(node, ast.ImportFrom) or node.level != 0:
            continue
        scope = scopes[id(node)]
        if node.module == module and any(a.name in names for a in node.names):
            old.setdefault(scope, []).append(node)
        elif node.module == GENERATED_PY:
            target.setdefault(scope, node)
    if not old:
        return

    edits: list[tuple[int, int, list[str]]] = []
    for scope, imports in old.items():
        imports.sort(key=lambda n: n.lineno)
        moving = [a for n in imports for a in n.names if a.name in names]
        into = target.get(scope)
        for i, node in enumerate(imports):
            indent = " " * node.col_offset
            comment, _ = _import_comment(f.lines, node)
            kept = [a for a in node.names if a.name not in names]
            span = (node.lineno - 1, node.end_lineno or node.lineno)
            multiline = (node.end_lineno or node.lineno) > node.lineno
            replacement = _render_py_import(indent, module, kept, comment, multiline) if kept else []
            if into is None and i == 0:
                fresh = sorted(moving, key=lambda a: a.name)
                replacement = _render_py_import(indent, GENERATED_PY, fresh, "" if kept else comment) + replacement
            edits.append((*span, replacement))
        if into is not None:
            indent = " " * into.col_offset
            comment, _ = _import_comment(f.lines, into)
            multiline = (into.end_lineno or into.lineno) > into.lineno
            rendered = _render_py_import(indent, GENERATED_PY, _merged(into.names, moving), comment, multiline)
            edits.append((into.lineno - 1, into.end_lineno or into.lineno, rendered))

    lines = list(f.lines)
    for start, end, replacement in sorted(edits, key=lambda e: e[0], reverse=True):
        lines[start:end] = replacement
    ws.write(f.path, "".join(lines))


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

_TS_IMPORT = re.compile(
    r"^(?P<indent>[ \t]*)import[ \t]+(?P<type>type[ \t]+)?\{(?P<names>[^}]*)\}[ \t]*from[ \t]*"
    r"(?P<q>['\"])(?P<spec>[^'\"]+)(?P=q);?(?P<comment>[ \t]*//[^\n]*)?[ \t]*\n?",
    re.M,
)
_TS_REEXPORT = re.compile(r"^export[ \t]+(?:type[ \t]+)?\{(?P<names>[^}]*)\}[ \t]*from[ \t]*['\"](?P<spec>[^'\"]+)['\"]", re.M)
_TS_NAMESPACE_IMPORT = re.compile(r"^import[ \t]+\*[ \t]+as[ \t]+(?P<alias>[\w$]+)[ \t]+from[ \t]*['\"](?P<spec>[^'\"]+)['\"]", re.M)
_TS_DEFAULT_AND_NAMED = re.compile(
    r"^import[ \t]+[\w$]+[ \t]*,[ \t]*\{(?P<names>[^}]*)\}[ \t]*from[ \t]*['\"](?P<spec>[^'\"]+)['\"]", re.M
)
_TS_EXPORT_CONST = re.compile(r"^export const (?P<name>[A-Za-z_$][\w$]*)\b[^=\n]*=", re.M)
_TS_STRING_ITEM = re.compile(r"\s*'((?:[^'\\]|\\.)*)'\s*")


def _ts_statement_end(text: str, start: int) -> int:
    """The index just past the `;` ending the statement at `start`, skipping strings,
    comments and brackets."""
    depth = 0
    i = start
    while i < len(text):
        c = text[i]
        if c in "'\"`":
            i += 1
            while i < len(text) and text[i] != c:
                i += 2 if text[i] == "\\" else 1
        elif text.startswith("//", i):
            i = text.find("\n", i)
            if i < 0:
                return len(text)
            continue
        elif text.startswith("/*", i):
            i = text.find("*/", i) + 1
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == ";" and depth == 0:
            return i + 1
        i += 1
    return len(text)


def _ts_code_only(text: str) -> str:
    """`text` with comments and string contents blanked, for finding identifiers."""
    out = []
    i = 0
    while i < len(text):
        c = text[i]
        if c in "'\"`":
            j = i + 1
            while j < len(text) and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            out.append(c + " " * max(0, min(j, len(text)) - i - 1) + c)
            i = j + 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            j = len(text) if j < 0 else j
            out.append(" " * (j - i))
            i = j
        elif text.startswith("/*", i):
            j = text.find("*/", i)
            j = len(text) if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", text[i:j]))
            i = j
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _ts_literal(source: str) -> object:
    """An int, a single-quoted string, or an array of them, from TS source; else None."""
    source = re.sub(r"\s+as\s+const\s*$", "", source.strip())
    if re.fullmatch(r"-?\d(?:_?\d)*", source):
        return int(source)
    item = _TS_STRING_ITEM.fullmatch(source)
    if item:
        return item.group(1)
    if source.startswith("[") and source.endswith("]"):
        inner = source[1:-1].strip().rstrip(",")
        items = [_TS_STRING_ITEM.fullmatch(part) for part in inner.split(",")] if inner else []
        if items and all(items):
            return [m.group(1) for m in items if m]
    return None


@dataclass
class _TsDef:
    path: Path
    name: str
    start: int
    end: int
    value: object
    line: int


def _ts_definitions(ws: Workspace, path: Path) -> list[_TsDef]:
    text = ws.read(path)
    defs = []
    for m in _TS_EXPORT_CONST.finditer(text):
        semicolon = _ts_statement_end(text, m.end())
        newline = text.find("\n", semicolon)
        end = len(text) if newline < 0 else newline + 1
        value_source = text[m.end():semicolon].rstrip().rstrip(";")
        defs.append(_TsDef(path, m.group("name"), m.start(), end, _ts_literal(value_source), text.count("\n", 0, m.start()) + 1))
    return defs


def _frontend_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for top in FRONTEND_ROOTS:
        base = root / top
        if base.is_dir():
            files.extend(
                p for p in base.rglob("*")
                if p.suffix in (".ts", ".tsx")
                and "node_modules" not in p.parts and "_generated" not in p.parts
            )
    return sorted(files)


def _resolve_spec(path: Path, spec: str) -> str | None:
    """The importing `spec`, as an extensionless absolute path; None for a package."""
    if not spec.startswith("."):
        return None
    target = os.path.normpath(path.parent / spec)
    return re.sub(r"\.(js|ts|tsx)$", "", target)


def _generated_spec(ws: Workspace, path: Path) -> str:
    rel = os.path.relpath(ws.root / FRONTEND_GENERATED, path.parent).replace(os.sep, "/")
    if not rel.startswith("."):
        rel = "./" + rel
    uses_js = any(path.is_relative_to(ws.root / top) for top in FRONTEND_JS_EXTENSION_ROOTS)
    return rel + (".js" if uses_js else "")


def _ts_parts(names: str) -> list[str]:
    return [part.strip() for part in names.split(",") if part.strip()]


def _ts_part_name(part: str) -> str:
    return re.sub(r"^type\s+", "", part).split()[0]


def _render_ts_import(indent: str, type_kw: str, parts: list[str], spec: str, comment: str, multiline: bool) -> str:
    one = f"{indent}import {type_kw}{{ {', '.join(parts)} }} from '{spec}';"
    if not multiline and len(one) <= TS_LINE_MAX:
        return one + comment + "\n"
    body = "".join(f"{indent}  {p},\n" for p in parts)
    return f"{indent}import {type_kw}{{\n{body}{indent}}} from '{spec}';{comment}\n"


def _merged_parts(existing: list[str], added: list[str]) -> list[str]:
    keys = [_ts_part_name(p) for p in existing]
    new = [p for p in added if p not in existing]
    if keys == sorted(keys):
        return sorted([*existing, *new], key=_ts_part_name)
    return [*existing, *new]


def _frontend_refusals(ws: Workspace, files: list[Path], constants: set[str], names: set[str]) -> list[str]:
    reasons = []
    for path in files:
        text = ws.read(path)
        for m in _TS_IMPORT.finditer(text):
            if _resolve_spec(path, m.group("spec")) not in constants:
                continue
            parts = _ts_parts(m.group("names"))
            if any(_ts_part_name(p) in names for p in parts) and ("//" in m.group("names") or "/*" in m.group("names")):
                line = text.count("\n", 0, m.start()) + 1
                reasons.append(f"{ws.rel(path)}:{line}: a comment inside the import; edit it by hand")
        for pattern, what in ((_TS_REEXPORT, "re-exported"), (_TS_DEFAULT_AND_NAMED, "imported alongside a default import")):
            for m in pattern.finditer(text):
                if _resolve_spec(path, m.group("spec")) in constants:
                    line = text.count("\n", 0, m.start()) + 1
                    reasons.extend(
                        f"{ws.rel(path)}:{line}: {name} is {what}; rewrite it by hand"
                        for name in sorted({_ts_part_name(p) for p in _ts_parts(m.group("names"))} & names)
                    )
        for m in _TS_NAMESPACE_IMPORT.finditer(text):
            if _resolve_spec(path, m.group("spec")) in constants:
                line = text.count("\n", 0, m.start()) + 1
                code = _ts_code_only(text)
                reasons.extend(
                    f"{ws.rel(path)}:{line}: {name} is read through a namespace import; rewrite it by hand"
                    for name in sorted(names)
                    if re.search(rf"(?<![\w$]){re.escape(m.group('alias'))}\s*\.\s*{re.escape(name)}(?![\w$])", code)
                )
    return reasons


def _repoint_frontend(ws: Workspace, path: Path, constants: set[str], names: set[str], local: set[str]) -> None:
    """Move `names` imported from a frontend constants file, plus `local` (names the file
    itself still uses after losing their definition), onto the generated import."""
    text = ws.read(path)
    generated = _resolve_spec(path, _generated_spec(ws, path))
    edits: list[tuple[int, int, str]] = []
    moving: dict[str, list[str]] = {"": [], "type ": []}
    first_old: dict[str, re.Match[str]] = {}
    target: dict[str, re.Match[str]] = {}
    for m in _TS_IMPORT.finditer(text):
        kind = "type " if m.group("type") else ""
        resolved = _resolve_spec(path, m.group("spec"))
        if resolved == generated:
            target.setdefault(kind, m)
            continue
        if resolved not in constants:
            continue
        parts = _ts_parts(m.group("names"))
        leaving = [p for p in parts if _ts_part_name(p) in names]
        if not leaving:
            continue
        moving[kind].extend(leaving)
        first_old.setdefault(kind, m)
        kept = [p for p in parts if _ts_part_name(p) not in names]
        multiline = "\n" in m.group("names")
        comment = m.group("comment") or ""
        replacement = _render_ts_import(m.group("indent"), kind, kept, m.group("spec"), comment, multiline) if kept else ""
        edits.append((m.start(), m.end(), replacement))
    moving[""].extend(sorted(n for n in local if n not in moving[""]))

    for kind, parts in moving.items():
        if not parts:
            continue
        into = target.get(kind)
        if into is not None:
            merged = _merged_parts(_ts_parts(into.group("names")), parts)
            multiline = "\n" in into.group("names")
            rendered = _render_ts_import(into.group("indent"), kind, merged, into.group("spec"), into.group("comment") or "", multiline)
            edits.append((into.start(), into.end(), rendered))
            continue
        fresh = _render_ts_import("", kind, sorted(parts, key=_ts_part_name), _generated_spec(ws, path), "", False)
        old = first_old.get(kind)
        if old is not None:
            edits = [(s, e, r + fresh) if s == old.start() else (s, e, r) for s, e, r in edits]
        else:
            imports = list(_TS_IMPORT.finditer(text))
            at = imports[-1].end() if imports else 0
            edits.append((at, at, fresh if imports else fresh + "\n"))

    for start, end, replacement in sorted(edits, key=lambda e: e[0], reverse=True):
        text = text[:start] + replacement + text[end:]
    ws.write(path, text)


def _remove_ts_definitions(ws: Workspace, path: Path, defs: list[_TsDef], report: Report) -> set[str]:
    """Drop `defs` from `path`, and return the removed names the file still uses."""
    text = ws.read(path)
    lines = text.splitlines(keepends=True)
    spans = [(text.count("\n", 0, d.start), text.count("\n", 0, d.end) + (not text.endswith("\n", 0, d.end))) for d in defs]
    for start, _ in sorted(spans):
        for lineno, comment in _comment_block_above(lines, start, "//"):
            report.comments.append(f"{ws.rel(path)}:{lineno}: {comment}")
    for start, end in sorted(spans, reverse=True):
        lines = _remove_lines(lines, start, end)
    text = "".join(lines)
    ws.write(path, text)
    code = _ts_code_only(text)
    return {d.name for d in defs if re.search(rf"(?<![\w$.]){re.escape(d.name)}(?![\w$])", code)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _run_generator(root: Path) -> None:
    script = root / "scripts" / "generate_shared.py"
    check = subprocess.run([sys.executable, str(script), "--check"], cwd=root, capture_output=True, text=True)
    if check.returncode == 0:
        return
    result = subprocess.run([sys.executable, str(script)], cwd=root, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"generate_shared.py failed:\n{result.stderr}")


def _plan(ws: Workspace, domain: str, names: list[str], report: Report) -> None:
    root = ws.root
    config_path = root / "shared" / "app-config.json"
    constants_path = root / "backend" / "app" / "constants" / f"{domain}.py"
    module = f"app.constants.{domain}"
    scalars = json.loads(ws.read(config_path))["scalars"]
    reasons: list[str] = []

    if not constants_path.exists():
        raise Refused([f"{ws.rel(constants_path)}: no such file"])
    constants_text = ws.read(constants_path)
    tree = ast.parse(constants_text)
    defs = _definitions(tree)
    additions: dict[str, object] = {}
    removals: list[ast.stmt] = []
    for name in names:
        node = defs.get(name)
        if node is None:
            if name in scalars:
                report.already.append(name)
            else:
                reasons.append(f"{name}: not defined at the top level of {ws.rel(constants_path)}")
            continue
        assert node.value is not None
        try:
            value = _scalar_value(node.value)
        except ValueError as exc:
            reasons.append(f"{name}: {exc}")
            continue
        if name in scalars and scalars[name] != value:
            reasons.append(f"{name}: scalars already holds {scalars[name]!r}, not {value!r}")
            continue
        uses = sorted(
            n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Load)
        )
        if uses:
            reasons.extend(f"{ws.rel(constants_path)}:{line}: {name} is used in its own constants file; move it by hand" for line in uses)
            continue
        if name not in scalars:
            additions[name] = value
        removals.append(node)
        report.moved.append(name)

    requested = set(names)
    values = {**scalars, **additions}
    backend_files = _parse_backend(ws)
    reasons.extend(_backend_refusals(ws, backend_files, module, requested))

    frontend_files = _frontend_files(root)
    constants_dir = root / FRONTEND_CONSTANTS
    ts_constants = sorted(p for p in constants_dir.glob("*.ts") if not p.name.endswith(".test.ts")) if constants_dir.is_dir() else []
    ts_copies: dict[Path, list[_TsDef]] = {}
    for path in ts_constants:
        for d in _ts_definitions(ws, path):
            if d.name in requested and d.name in values:
                if d.value is None:
                    reasons.append(f"{ws.rel(path)}:{d.line}: {d.name} is not a literal; move it by hand")
                elif d.value != values[d.name]:
                    reasons.append(
                        f"{ws.rel(path)}:{d.line}: {d.name} is {d.value!r} here, {values[d.name]!r} in the backend"
                    )
                else:
                    ts_copies.setdefault(path, []).append(d)
            elif d.value is not None:
                report.renames.extend(
                    f"{ws.rel(path)}:{d.line}: {d.name} has the value of {name}"
                    for name in names
                    if name in values and values[name] == d.value
                )
    copy_modules = {os.path.normpath(p.with_suffix("")) for p in ts_copies}
    copied = {d.name for copies in ts_copies.values() for d in copies}
    reasons.extend(_frontend_refusals(ws, frontend_files, copy_modules, copied))
    if reasons:
        raise Refused(reasons)

    ws.write(config_path, _add_scalars(ws.read(config_path), additions))

    lines = constants_text.splitlines(keepends=True)
    for stmt in sorted(removals, key=lambda n: n.lineno):
        for lineno, text in _comment_block_above(lines, stmt.lineno - 1, "#"):
            report.comments.append(f"{ws.rel(constants_path)}:{lineno}: {text}")
    for stmt in sorted(removals, key=lambda n: n.lineno, reverse=True):
        lines = _remove_lines(lines, stmt.lineno - 1, stmt.end_lineno or stmt.lineno)
    ws.write(constants_path, "".join(lines))

    for f in backend_files:
        _repoint_backend(ws, f, module, requested)

    local = {path: _remove_ts_definitions(ws, path, copies, report) for path, copies in ts_copies.items()}
    if ts_copies:
        for path in frontend_files:
            _repoint_frontend(ws, path, copy_modules, copied, local.get(path, set()))


def _ignored(root: Path, rels: list[str]) -> set[str]:
    result = subprocess.run(
        ["git", "check-ignore", "--stdin"], cwd=root, input="\n".join(rels), capture_output=True, text=True
    )
    return set(result.stdout.split())


def _print_report(ws: Workspace, report: Report, changed: list[str], dry_run: bool) -> None:
    if report.moved:
        print(f"moved to shared/ scalars: {', '.join(report.moved)}")
    if report.already:
        print(f"already in shared/ scalars: {', '.join(report.already)}")
    if report.comments:
        print("comments above the removed definitions; place them by hand:")
        for line in report.comments:
            print(f"  {line}")
    if changed:
        ignored = _ignored(ws.root, changed)
        print("would change:" if dry_run else "changed:")
        for rel in changed:
            print(f"  {rel}  (gitignored)" if rel in ignored else f"  {rel}")
    else:
        print("nothing to change.")
    if report.renames:
        print("possible cross-stack renames, not rewritten:")
        for line in report.renames:
            print(f"  {line}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Move backend constants into shared/ scalars.")
    parser.add_argument("domain", help="the backend constants module, e.g. promotions")
    parser.add_argument("names", nargs="+", metavar="NAME")
    parser.add_argument("--dry-run", action="store_true", help="print the report and planned edits; write nothing")
    parser.add_argument("--root", type=Path, default=REPO, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    ws = Workspace(args.root.resolve())
    report = Report()
    try:
        _plan(ws, args.domain, args.names, report)
    except Refused as exc:
        print("refused, nothing written:", file=sys.stderr)
        for reason in exc.reasons:
            print(f"  {reason}", file=sys.stderr)
        return 1

    changed = ws.changed()
    if args.dry_run:
        for path in changed:
            rel = ws.rel(path)
            sys.stdout.writelines(difflib.unified_diff(
                ws.original[path].splitlines(keepends=True),
                ws.pending[path].splitlines(keepends=True),
                f"a/{rel}", f"b/{rel}",
            ))
        rels = [ws.rel(p) for p in changed]
        if any(rel == "shared/app-config.json" for rel in rels):
            rels.extend(GENERATED_FILES)
        _print_report(ws, report, sorted(rels), dry_run=True)
        return 0

    generated = [ws.root / rel for rel in GENERATED_FILES]
    before = {p: p.read_bytes() if p.exists() else None for p in generated}
    for path in changed:
        path.write_text(ws.pending[path], encoding="utf-8")
    try:
        _run_generator(ws.root)
    except RuntimeError as exc:
        for path in changed:
            path.write_text(ws.original[path], encoding="utf-8")
        for path, content in before.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(content)
        print(f"error: {exc}\nrestored every file this run edited.", file=sys.stderr)
        return 1
    regenerated = [p for p in generated if (p.read_bytes() if p.exists() else None) != before[p]]
    _print_report(ws, report, sorted(ws.rel(p) for p in [*changed, *regenerated]), dry_run=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
